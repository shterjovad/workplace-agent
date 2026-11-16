from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pytest_mock import MockerFixture

from tests.fakes import FakeChatModel, FakeEmbedder, InMemoryChunkStore
from workplace_agent import telemetry
from workplace_agent.config import Settings
from workplace_agent.ingestion.models import Chunk
from workplace_agent.retrieval.answer import ask
from workplace_agent.retrieval.models import AnswerSentence, StructuredAnswer

CONNECTION_STRING = "InstrumentationKey=00000000-0000-0000-0000-000000000000"


def test_tracing_stays_off_when_connection_string_unset(mocker: MockerFixture) -> None:
    configure = mocker.patch("azure.monitor.opentelemetry.configure_azure_monitor")
    settings = Settings(_env_file=None, applicationinsights_connection_string=None)

    assert telemetry.configure_tracing(settings) is False
    configure.assert_not_called()


def test_tracing_configured_once_when_connection_string_set(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(telemetry, "_configured", False)
    configure = mocker.patch("azure.monitor.opentelemetry.configure_azure_monitor")
    settings = Settings(_env_file=None, applicationinsights_connection_string=CONNECTION_STRING)

    assert telemetry.configure_tracing(settings) is True
    assert telemetry.configure_tracing(settings) is True
    configure.assert_called_once()
    assert configure.call_args.kwargs["connection_string"] == CONNECTION_STRING


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    trace.set_tracer_provider(provider)  # first setter wins; later calls are ignored
    # Bind this test's provider directly so ordering with other tests does not matter.
    from workplace_agent.retrieval import answer, search

    previous = answer.tracer, search.tracer
    answer.tracer = search.tracer = provider.get_tracer("workplace_agent")
    yield memory
    answer.tracer, search.tracer = previous


def test_ask_spans_carry_counts_and_no_text(exporter: InMemorySpanExporter) -> None:
    question = "secretquestion alpha"
    doc_text = "secretdocument alpha"
    answer_text = "secretanswer"
    store = InMemoryChunkStore()
    store.upsert(
        [
            Chunk(
                id="c0",
                doc_id="d",
                chunk_index=0,
                title="Leave",
                source_path="Leave.pdf",
                page_start=1,
                page_end=1,
                content=doc_text,
                content_hash="h",
                section="",
            )
        ]
    )
    chat = FakeChatModel(
        StructuredAnswer(
            True,
            [AnswerSentence(answer_text, [1])],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
    )

    ask(question, embedder=FakeEmbedder(), store=store, chat=chat, top_k=3)

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert {"ask", "embed", "search", "chat", "render"} <= spans.keys()
    root = spans["ask"].attributes or {}
    assert root["found"] is True
    assert root["usage.prompt_tokens"] == 10
    for span in spans.values():
        for value in (span.attributes or {}).values():
            for secret in ("secretquestion", "secretdocument", answer_text):
                assert secret not in str(value)
