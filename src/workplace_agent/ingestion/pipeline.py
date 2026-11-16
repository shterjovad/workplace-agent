"""Ingest pipeline: blobs -> parse -> chunk -> embed -> index.

Each run diffs the index state (chunk 0 rows: doc_id, source_path, content_hash) against the
blobs: new / updated / unchanged / removed. State is read once at the start and runs are
sequential, so Azure Search's read-after-write lag does not affect correctness.
Each document is processed in its own try block; a failure is classified (see
``parser.classify_error``), recorded in ``summary.failed`` and the run continues. A failed
document never writes its commit marker (chunk 0): an updated document keeps its old content and
hash, and for a new document any partially written chunks are deleted so it still counts as new
when fixed. Retries (3 attempts, exponential backoff) live in the SDK clients.
"""

import hashlib
import json
import logging
import time

from workplace_agent.config import Settings
from workplace_agent.errors import FailureReason, ParseError
from workplace_agent.ingestion.chunker import chunk_document, embed_text
from workplace_agent.ingestion.models import Chunk, IndexedDocState, IngestSummary
from workplace_agent.ingestion.parser import classify_error
from workplace_agent.ports import BlobSource, ChunkStore, DocumentParser, Embedder
from workplace_agent.telemetry import get_tracer

NO_DOCUMENTS_MESSAGE = "No documents found in the document folder."
logger = logging.getLogger("workplace_agent.ingest")
tracer = get_tracer()


# Bump when the parser/chunker output changes so every document is re-ingested on the next run
# (it is part of the content hash).
PIPELINE_VERSION = "v1"


def pipeline_version(settings: Settings) -> str:
    return (
        f"{PIPELINE_VERSION};chunk={settings.chunk_max_tokens}/{settings.chunk_overlap_tokens};"
        f"embed={settings.azure_openai_embedding_deployment}"
    )


def content_hash(data: bytes, version: str) -> str:
    return hashlib.sha256(data + version.encode()).hexdigest()


def doc_id_for(name: str) -> str:
    return hashlib.sha1(name.encode()).hexdigest()[:16]  # noqa: S324 - identifier, not security


def _log(name: str, **fields: object) -> None:
    logger.info(json.dumps({"document": name, **fields}, ensure_ascii=False))


def _discard_partial(name: str, store: ChunkStore) -> None:
    """Remove chunks a failed NEW document may have written before its commit marker."""
    try:
        store.delete_ids(store.ids_for_doc(doc_id_for(name)))
    except Exception:
        logger.warning("Could not clean up partial chunks for %s", name, exc_info=True)


def run_ingest(
    blobs: BlobSource,
    parser: DocumentParser,
    embedder: Embedder,
    store: ChunkStore,
    settings: Settings,
) -> IngestSummary:
    summary = IngestSummary()
    store.ensure_index()
    states = {s.doc_id: s for s in store.get_states()}
    version = pipeline_version(settings)

    seen: set[str] = set()
    for name in blobs.list_names():
        if not name.lower().endswith(".pdf"):
            summary.skipped_non_pdf.append(name)
            _log(name, outcome="skipped_non_pdf")
            continue
        seen.add(doc_id_for(name))
        started = time.perf_counter()
        fields: dict[str, object]
        with tracer.start_as_current_span("ingest.document") as span:
            span.set_attribute("document.name", name)
            try:
                fields = _ingest_document(
                    name, blobs, parser, embedder, store, settings, version, states, summary
                )
            except Exception as exc:
                reason = classify_error(exc)
                summary.failed.append((name, reason))
                if doc_id_for(name) not in states:
                    _discard_partial(name, store)
                fields = {"outcome": "failed", "reason": reason.value}
            ms = round((time.perf_counter() - started) * 1000)
            span.set_attribute("outcome", str(fields["outcome"]))
            span.set_attribute("duration.ms", ms)
            if isinstance(chunk_count := fields.get("chunks"), int):
                span.set_attribute("chunks.count", chunk_count)
        _log(name, ms=ms, **fields)

    # Removed (or renamed: the old name's doc_id is gone) documents: delete every chunk by doc_id.
    for doc_id, state in states.items():
        if doc_id not in seen:
            store.delete_ids(store.ids_for_doc(doc_id))
            summary.removed += 1
            _log(state.source_path, outcome="removed")
    summary.total_passages = store.document_count()
    return summary


def _ingest_document(
    name: str,
    blobs: BlobSource,
    parser: DocumentParser,
    embedder: Embedder,
    store: ChunkStore,
    settings: Settings,
    version: str,
    states: dict[str, IndexedDocState],
    summary: IngestSummary,
) -> dict[str, object]:
    """Process one document; return its log fields (``outcome`` plus extras). Raises on failure."""
    data = blobs.download(name)
    digest = content_hash(data, version)
    doc_id = doc_id_for(name)
    existing = states.get(doc_id)
    if existing is not None and existing.content_hash == digest:
        summary.unchanged += 1
        return {"outcome": "unchanged"}
    title = name[: -len(".pdf")]
    with tracer.start_as_current_span("parse"):
        parsed = parser.parse(name, data)
    with tracer.start_as_current_span("chunk"):
        pieces = chunk_document(
            parsed,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
    with tracer.start_as_current_span("embed"):
        vectors = embedder.embed([embed_text(title, p.section, p.content) for p in pieces])
    chunks = [
        Chunk(
            id=f"{doc_id}-{p.chunk_index}",
            doc_id=doc_id,
            title=title,
            source_path=name,
            page_start=p.page_start,
            page_end=p.page_end,
            section=p.section,
            chunk_index=p.chunk_index,
            content=p.content,
            content_hash=digest,
            vector=v,
        )
        for p, v in zip(pieces, vectors, strict=True)
    ]
    if not chunks:
        raise ParseError(FailureReason.NOT_READABLE_PDF, "no text could be extracted")

    # Write protocol: chunks 1..n-1, prune stale ids, then chunk 0 (new hash) as commit marker.
    # A crash before chunk 0 leaves the old hash, so the next run sees "updated" and redoes it.
    with tracer.start_as_current_span("index"):
        if len(chunks) > 1:
            store.upsert(chunks[1:])
        new_ids = {c.id for c in chunks}
        stale = [i for i in store.ids_for_doc(doc_id) if i not in new_ids]
        if stale:
            store.delete_ids(stale)
        store.upsert(chunks[:1])
    if existing is None:
        summary.new += 1
        return {"outcome": "new", "chunks": len(chunks)}
    summary.updated += 1
    return {"outcome": "updated", "chunks": len(chunks), "pruned": len(stale)}
