import httpx2
import openai
import pytest
from azure.core.exceptions import HttpResponseError

from tests.fakes import FakeBlobSource, FakeEmbedder, FakeParser, InMemoryChunkStore
from workplace_agent.config import Settings
from workplace_agent.errors import FailureReason, ParseError
from workplace_agent.ingestion.models import Chunk, IngestSummary
from workplace_agent.ingestion.pipeline import run_ingest

LONG = "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(12))


class LoggingStore(InMemoryChunkStore):
    def __init__(self) -> None:
        super().__init__()
        self.write_log: list[list[int]] = []

    def upsert(self, chunks: list[Chunk]) -> None:
        self.write_log.append([c.chunk_index for c in chunks])
        super().upsert(chunks)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, azure_openai_embedding_deployment="emb")


def ingest(files: dict[str, bytes], store: LoggingStore, settings: Settings) -> tuple:
    blobs = FakeBlobSource(files)
    summary = run_ingest(blobs, FakeParser(), FakeEmbedder(), store, settings)
    return summary, blobs


def test_first_run_counts_three_new(settings: Settings) -> None:
    store = LoggingStore()
    files = {f"{n}.pdf": LONG.encode() for n in "abc"}
    summary, _ = ingest(files, store, settings)
    assert (summary.new, summary.updated, summary.unchanged, summary.removed) == (3, 0, 0, 0)
    assert summary.failed == []
    assert summary.total_passages == len(store.chunks) > 3
    assert store.index_ensured


def test_chunk_zero_is_written_last(settings: Settings) -> None:
    store = LoggingStore()
    ingest({"a.pdf": LONG.encode()}, store, settings)
    assert len(store.write_log) == 2
    assert 0 not in store.write_log[0]
    assert store.write_log[1] == [0]


def test_non_pdf_skipped_and_never_downloaded(settings: Settings) -> None:
    store = LoggingStore()
    summary, blobs = ingest({"a.pdf": b"hello", "notes.DOCX": b"x", "b.txt": b"y"}, store, settings)
    assert summary.new == 1
    assert summary.skipped_non_pdf == ["b.txt", "notes.DOCX"]
    assert blobs.downloaded == ["a.pdf"]


def test_empty_folder_gives_zero_summary(settings: Settings) -> None:
    store = LoggingStore()
    summary, _ = ingest({}, store, settings)
    assert (summary.new, summary.unchanged, summary.total_passages) == (0, 0, 0)
    assert summary.failed == [] and summary.skipped_non_pdf == []


def test_rerun_counts_unchanged_and_writes_nothing(settings: Settings) -> None:
    store = LoggingStore()
    files = {"a.pdf": LONG.encode(), "b.pdf": b"short doc"}
    ingest(files, store, settings)
    writes = len(store.write_log)
    summary, _ = ingest(files, store, settings)
    assert (summary.new, summary.unchanged) == (0, 2)
    assert len(store.write_log) == writes


def _titles(store: LoggingStore) -> set[str]:
    return {c.title for c in store.chunks.values()}


def test_updated_document_replaces_old_content(settings: Settings) -> None:
    store = LoggingStore()
    ingest({"a.pdf": b"carry over limit is 5 days"}, store, settings)
    summary, _ = ingest({"a.pdf": b"carry over limit is 10 days"}, store, settings)
    assert (summary.new, summary.updated, summary.unchanged, summary.removed) == (0, 1, 0, 0)
    text = " ".join(c.content for c in store.chunks.values())
    assert "10 days" in text and "5 days" not in text


def test_shortened_document_prunes_stale_chunks(settings: Settings) -> None:
    store = LoggingStore()
    ingest({"a.pdf": LONG.encode()}, store, settings)
    before = sorted(store.chunks)
    short = "\n\n".join(LONG.split("\n\n")[:8])
    summary, _ = ingest({"a.pdf": short.encode()}, store, settings)
    assert summary.updated == 1
    after = sorted(store.chunks)
    assert 0 < len(after) < len(before)
    assert set(after) <= set(before)
    assert all(c.chunk_index < len(after) for c in store.chunks.values())
    assert "Paragraph 11" not in " ".join(c.content for c in store.chunks.values())


def test_updated_write_order_prunes_before_chunk_zero(settings: Settings) -> None:
    store = LoggingStore()
    ingest({"a.pdf": LONG.encode()}, store, settings)
    short = "\n\n".join(LONG.split("\n\n")[:8])
    events: list[str] = []
    orig_delete, orig_upsert = store.delete_ids, store.upsert
    store.delete_ids = lambda ids: (events.append("delete"), orig_delete(ids))[1]  # type: ignore[method-assign]
    store.upsert = lambda ch: (events.append(f"upsert{ch[0].chunk_index}"), orig_upsert(ch))[1]  # type: ignore[method-assign]
    ingest({"a.pdf": short.encode()}, store, settings)
    assert events[-2:] == ["delete", "upsert0"]


def test_renamed_document_is_removed_plus_new(settings: Settings) -> None:
    store = LoggingStore()
    ingest({"old.pdf": LONG.encode()}, store, settings)
    summary, _ = ingest({"new.pdf": LONG.encode()}, store, settings)
    assert (summary.new, summary.removed, summary.updated) == (1, 1, 0)
    assert _titles(store) == {"new"}


def test_removed_document_is_deleted_completely(settings: Settings) -> None:
    store = LoggingStore()
    ingest({"a.pdf": LONG.encode(), "b.pdf": b"keep me"}, store, settings)
    summary, _ = ingest({"b.pdf": b"keep me"}, store, settings)
    assert (summary.removed, summary.unchanged, summary.new) == (1, 1, 0)
    assert _titles(store) == {"b"}


def test_emptied_folder_removes_everything(settings: Settings) -> None:
    store = LoggingStore()
    ingest({f"{n}.pdf": LONG.encode() for n in "abc"}, store, settings)
    summary, _ = ingest({}, store, settings)
    assert summary.removed == 3 and not store.chunks and summary.total_passages == 0
    from workplace_agent.cli import format_summary

    assert "No documents found in the document folder." in format_summary(summary)


def test_crash_before_chunk_zero_is_redone_next_run(settings: Settings) -> None:
    store = LoggingStore()
    ingest({"a.pdf": LONG.encode()}, store, settings)
    new_files = {"a.pdf": "\n\n".join(LONG.split("\n\n")[:8]).encode()}
    orig = store.upsert

    def flaky(chunks: list[Chunk]) -> None:
        if [c.chunk_index for c in chunks] == [0]:
            raise RuntimeError("boom")
        orig(chunks)

    store.upsert = flaky  # type: ignore[method-assign]
    failed, _ = ingest(new_files, store, settings)
    assert failed.failed == [("a.pdf", FailureReason.NOT_READABLE_PDF)]
    store.upsert = orig  # type: ignore[method-assign]
    summary, _ = ingest(new_files, store, settings)
    assert (summary.updated, summary.unchanged) == (1, 0)
    ids = sorted(store.chunks)
    assert all(int(i.split("-")[1]) < len(ids) for i in ids)
    assert "Paragraph 11" not in " ".join(c.content for c in store.chunks.values())


def _failures(summary: IngestSummary) -> dict[str, FailureReason]:
    return dict(summary.failed)


def test_mixed_batch_reports_failures_and_writes_nothing_for_them(settings: Settings) -> None:
    store = LoggingStore()
    files = {
        "a.pdf": LONG.encode(),
        "b.pdf": LONG.encode(),
        "Salary.pdf": b"protected",
        "Policy.pdf": b"not a pdf",
        "Notes.docx": b"docx",
    }
    parser = FakeParser(
        {
            "Salary.pdf": ParseError(FailureReason.PASSWORD_PROTECTED),
            "Policy.pdf": ParseError(FailureReason.NOT_READABLE_PDF),
        }
    )
    summary = run_ingest(FakeBlobSource(files), parser, FakeEmbedder(), store, settings)
    assert (summary.new, summary.updated, summary.unchanged) == (2, 0, 0)
    assert _failures(summary) == {
        "Policy.pdf": FailureReason.NOT_READABLE_PDF,
        "Salary.pdf": FailureReason.PASSWORD_PROTECTED,
    }
    assert summary.skipped_non_pdf == ["Notes.docx"]
    assert {c.source_path for c in store.chunks.values()} == {"a.pdf", "b.pdf"}


def test_failed_document_is_new_once_fixed(settings: Settings) -> None:
    store = LoggingStore()
    broken = FakeParser({"p.pdf": ParseError(FailureReason.NOT_READABLE_PDF)})
    first = run_ingest(FakeBlobSource({"p.pdf": b"junk"}), broken, FakeEmbedder(), store, settings)
    assert len(first.failed) == 1 and not store.chunks
    second, _ = ingest({"p.pdf": LONG.encode()}, store, settings)
    assert (second.new, second.updated, second.failed) == (1, 0, [])


class FailingEmbedder(FakeEmbedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise openai.APIConnectionError(request=httpx2.Request("POST", "https://x"))


def test_temporary_error_after_partial_write_leaves_no_chunks(settings: Settings) -> None:
    class FlakyStore(LoggingStore):
        def upsert(self, chunks: list[Chunk]) -> None:
            super().upsert(chunks)
            if 0 not in [c.chunk_index for c in chunks]:
                error = HttpResponseError(message="unavailable")
                error.status_code = 503
                raise error

    store = FlakyStore()
    summary = run_ingest(
        FakeBlobSource({"a.pdf": LONG.encode()}), FakeParser(), FakeEmbedder(), store, settings
    )
    assert summary.failed == [("a.pdf", FailureReason.TEMPORARY)]
    assert store.chunks == {}


def test_embedding_connection_error_is_temporary_and_batch_continues(settings: Settings) -> None:
    store = LoggingStore()
    summary = run_ingest(
        FakeBlobSource({"a.pdf": b"x"}), FakeParser(), FailingEmbedder(), store, settings
    )
    assert summary.failed == [("a.pdf", FailureReason.TEMPORARY)]
    assert store.chunks == {}


def test_failed_update_keeps_old_content(settings: Settings) -> None:
    store = LoggingStore()
    ingest({"a.pdf": b"old text"}, store, settings)
    parser = FakeParser({"a.pdf": ParseError(FailureReason.TEMPORARY)})
    summary = run_ingest(FakeBlobSource({"a.pdf": b"new"}), parser, FakeEmbedder(), store, settings)
    assert summary.failed == [("a.pdf", FailureReason.TEMPORARY)]
    assert [c.content for c in store.chunks.values()] == ["old text"]
