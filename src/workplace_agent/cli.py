import logging
import sys
from pathlib import Path
from time import perf_counter

import typer
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient

from workplace_agent.azure_clients import (
    AZURE_RETRY_OPTIONS,
    build_docintel_client,
    build_openai_client,
    build_search_client,
    build_search_index_client,
)
from workplace_agent.config import Settings, get_settings
from workplace_agent.errors import AppError
from workplace_agent.ingestion.blobs import AzureBlobSource
from workplace_agent.ingestion.embedder import AzureOpenAIEmbedder
from workplace_agent.ingestion.index import SearchChunkStore
from workplace_agent.ingestion.models import IngestSummary
from workplace_agent.ingestion.parser import DocumentIntelligenceParser
from workplace_agent.ingestion.pipeline import NO_DOCUMENTS_MESSAGE, run_ingest
from workplace_agent.ports import BlobSource, ChatModel, ChunkStore, DocumentParser, Embedder
from workplace_agent.retrieval.answer import AskResult
from workplace_agent.retrieval.answer import ask as answer_question
from workplace_agent.retrieval.chat import AzureChatModel
from workplace_agent.retrieval.evaluation import (
    EvalError,
    count_warning,
    format_result_line,
    format_totals,
    format_verdict,
    load_questions,
    run_evaluation,
)
from workplace_agent.retrieval.search import is_library_empty
from workplace_agent.telemetry import configure_tracing, flush_tracing

EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
LIBRARY_EMPTY_MESSAGE = "The library has no documents yet. Run ingest first."

app = typer.Typer(help="Document ingestion and grounded Q&A over Azure.", no_args_is_help=True)


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code)


def _require_azure(settings: Settings) -> None:
    try:
        settings.require_azure()
    except AppError as exc:
        raise _fail(str(exc), EXIT_CONFIG) from exc


def build_ask_adapters(settings: Settings) -> tuple[Embedder, ChunkStore, ChatModel]:
    client = build_openai_client(settings)
    return (
        AzureOpenAIEmbedder(client, settings.azure_openai_embedding_deployment or ""),
        SearchChunkStore(
            build_search_index_client(settings),
            build_search_client(settings),
            settings.search_index_name,
        ),
        AzureChatModel(client, settings.azure_openai_chat_deployment or ""),
    )


def build_ingest_adapters(
    settings: Settings,
) -> tuple[BlobSource, DocumentParser, Embedder, ChunkStore]:
    container = ContainerClient(
        settings.storage_account_url or "",
        settings.blob_container,
        DefaultAzureCredential(),
        **AZURE_RETRY_OPTIONS,
    )
    return (
        AzureBlobSource(container),
        DocumentIntelligenceParser(build_docintel_client(settings)),
        AzureOpenAIEmbedder(
            build_openai_client(settings), settings.azure_openai_embedding_deployment or ""
        ),
        SearchChunkStore(
            build_search_index_client(settings),
            build_search_client(settings),
            settings.search_index_name,
        ),
    )


def format_summary(summary: IngestSummary) -> list[str]:
    if not (summary.new or summary.updated or summary.unchanged or summary.failed):
        lines = [NO_DOCUMENTS_MESSAGE] if not summary.skipped_non_pdf else []
    else:
        lines = []
    lines += [
        f"new: {summary.new}",
        f"updated: {summary.updated}",
        f"unchanged: {summary.unchanged}",
        f"removed: {summary.removed}",
        f"failed: {len(summary.failed)}",
    ]
    lines += [f"  {name}: {reason.value}" for name, reason in summary.failed]
    if summary.skipped_non_pdf:
        lines.append("skipped (not a PDF):")
        lines += [f"  {name}" for name in summary.skipped_non_pdf]
    lines.append(f"passages in library: {summary.total_passages}")
    return lines


def _setup_logging() -> None:
    """Per-document JSON lines on stderr; Azure SDK HTTP logging stays at WARNING."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    for noisy in ("azure", "openai", "httpx", "httpx2", "httpcore", "opentelemetry"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def ingest() -> None:
    """Ingest documents into the search index."""
    settings = get_settings()
    _require_azure(settings)
    _setup_logging()
    configure_tracing(settings)
    blobs, parser, embedder, store = build_ingest_adapters(settings)
    try:
        summary = run_ingest(blobs, parser, embedder, store, settings)
    finally:
        flush_tracing()
    for line in format_summary(summary):
        typer.echo(line)
    if summary.failed:
        typer.echo(f"Ingest finished with {len(summary.failed)} failed document(s).")
        raise typer.Exit(EXIT_FAILURE)
    typer.echo("Ingest finished successfully.")


@app.command()
def ask(question: str | None = typer.Argument(None)) -> None:
    """Ask a question grounded in the ingested documents."""
    if question is None or not question.strip():
        raise _fail("Please type a question.", EXIT_USAGE)
    settings = get_settings()
    _require_azure(settings)
    _setup_logging()
    configure_tracing(settings)
    embedder, store, chat = build_ask_adapters(settings)
    if is_library_empty(store):
        raise _fail(LIBRARY_EMPTY_MESSAGE, EXIT_FAILURE)
    try:
        result = answer_question(
            question.strip(), embedder=embedder, store=store, chat=chat, top_k=settings.top_k
        )
    finally:
        flush_tracing()
    typer.echo(result.text)


@app.command()
def eval() -> None:
    """Run the evaluation questions."""
    settings = get_settings()
    try:
        questions = load_questions(Path(settings.eval_path))
    except EvalError as exc:
        raise _fail(str(exc), EXIT_FAILURE) from exc
    _require_azure(settings)
    _setup_logging()
    configure_tracing(settings)
    embedder, store, chat = build_ask_adapters(settings)
    if is_library_empty(store):
        raise _fail(LIBRARY_EMPTY_MESSAGE, EXIT_FAILURE)
    if (warning := count_warning(len(questions))) is not None:
        typer.echo(warning, err=True)

    def ask_fn(question: str) -> AskResult:
        return answer_question(
            question, embedder=embedder, store=store, chat=chat, top_k=settings.top_k
        )

    try:
        report = run_evaluation(
            questions,
            ask_fn,
            perf_counter,
            on_result=lambda i, r: typer.echo(format_result_line(i, r)),
        )
    finally:
        flush_tracing()
    for line in format_totals(report):
        typer.echo(line)
    typer.echo(format_verdict(report))
    if not report.passed:
        raise typer.Exit(EXIT_FAILURE)
