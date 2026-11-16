# @spec: 001-document-ingestion-and-qa-cli
"""Hermetic end-to-end harness: the real CLI, pipeline, chunker and renderer over in-memory fakes.

Only the Azure adapters (blob folder, Document Intelligence, embeddings, search, chat model) are
replaced. Everything between the command line and those ports is production code.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from tests.fakes import FakeBlobSource, FakeEmbedder, InMemoryChunkStore
from workplace_agent import cli
from workplace_agent.cli import app
from workplace_agent.config import get_settings
from workplace_agent.errors import FailureReason, ParseError
from workplace_agent.ingestion.chunker import PAGE_BREAK
from workplace_agent.ingestion.models import PageSpan, ParsedDocument
from workplace_agent.retrieval.models import AnswerSentence, RetrievedChunk, StructuredAnswer

PAGE_SEP = "\f"
AZURE_VARS = (
    "STORAGE_ACCOUNT_URL",
    "DOCINTEL_ENDPOINT",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "SEARCH_ENDPOINT",
)


def pdf(*pages: str) -> bytes:
    """A fake 'PDF': the pages joined by a form feed."""
    return PAGE_SEP.join(pages).encode()


class PagedParser:
    """Turns fake PDF bytes into a ParsedDocument with a real page map."""

    def __init__(self) -> None:
        self.offline = False

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        if data.startswith(b"PROTECTED"):
            raise ParseError(FailureReason.PASSWORD_PROTECTED)
        if data.startswith(b"JUNK"):
            raise ParseError(FailureReason.NOT_READABLE_PDF)
        if self.offline and data.startswith(b"NET"):
            raise ParseError(FailureReason.TEMPORARY)
        pages = data.decode().split(PAGE_SEP)
        markdown = ""
        spans: list[PageSpan] = []
        for number, text in enumerate(pages, start=1):
            start = len(markdown)
            markdown += text + (f"\n\n{PAGE_BREAK}\n\n" if number < len(pages) else "\n")
            spans.append(PageSpan(number, start, len(markdown)))
        return ParsedDocument(markdown=markdown, page_spans=spans)


class ExtractiveChat:
    """Answers with the passage sentence containing the needle; not-found if none contains it."""

    def __init__(self) -> None:
        self.needles: dict[str, str] = {}  # question substring -> needle
        self.missing: dict[str, str] = {}  # question substring -> missing part
        self.cite_all_matches = False

    def answer(self, question: str, passages: list[RetrievedChunk]) -> StructuredAnswer:
        for key, needle in self.needles.items():
            if key not in question:
                continue
            hits = [i for i, p in enumerate(passages, start=1) if needle in p.content]
            if not hits:
                return StructuredAnswer(False)
            if not self.cite_all_matches:
                hits = hits[:1]
            sentence = AnswerSentence(f"The answer is {needle}.", hits)
            missing = next((m for k, m in self.missing.items() if k in question), None)
            return StructuredAnswer(True, [sentence], missing)
        return StructuredAnswer(False)


class World:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.blobs = FakeBlobSource()
        self.parser = PagedParser()
        self.embedder = FakeEmbedder()
        self.store = InMemoryChunkStore()
        self.chat = ExtractiveChat()
        self.runner = CliRunner()
        monkeypatch.setattr(
            cli,
            "build_ingest_adapters",
            lambda s: (self.blobs, self.parser, self.embedder, self.store),
        )
        monkeypatch.setattr(
            cli, "build_ask_adapters", lambda s: (self.embedder, self.store, self.chat)
        )

    def put(self, name: str, data: bytes) -> None:
        self.blobs.files[name] = data

    def remove(self, name: str) -> None:
        del self.blobs.files[name]

    def run(self, *args: str) -> Result:
        return self.runner.invoke(app, list(args))

    def sources(self, result: Result) -> list[str]:
        return re.findall(r"^\[\d+\] .+$", result.stdout, flags=re.MULTILINE)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    monkeypatch.chdir(tmp_path)
    for var in AZURE_VARS:
        monkeypatch.setenv(var, "x")
    monkeypatch.setenv("EVAL_PATH", str(tmp_path / "missing.jsonl"))
    get_settings.cache_clear()
    yield World(monkeypatch)
    get_settings.cache_clear()
