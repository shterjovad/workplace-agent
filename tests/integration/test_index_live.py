import os
import time
import uuid
from collections.abc import Callable

import pytest

from workplace_agent.azure_clients import (
    build_openai_client,
    build_search_client,
    build_search_index_client,
)
from workplace_agent.config import Settings
from workplace_agent.ingestion.embedder import AzureOpenAIEmbedder
from workplace_agent.ingestion.index import SearchChunkStore
from workplace_agent.ingestion.models import Chunk

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("SEARCH_ENDPOINT") or Settings().search_endpoint),
        reason="SEARCH_ENDPOINT not set",
    ),
]


def wait_until(predicate: Callable[[], bool], timeout: float = 30, interval: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail(f"condition not met within {timeout}s")
        time.sleep(interval)


def test_index_roundtrip() -> None:
    settings = Settings()
    store = SearchChunkStore(
        build_search_index_client(settings),
        build_search_client(settings),
        settings.search_index_name,
    )
    store.ensure_index()
    embedder = AzureOpenAIEmbedder(
        build_openai_client(settings), settings.azure_openai_embedding_deployment or ""
    )
    vectors = embedder.embed(["remote work policy", "expense reimbursement"])
    assert [len(v) for v in vectors] == [1536, 1536]

    doc_id = f"itest-{uuid.uuid4().hex[:8]}"
    chunks = [
        Chunk(
            id=f"{doc_id}-{i}", doc_id=doc_id, title="itest", source_path="itest.pdf",
            page_start=1, page_end=1, section="s", chunk_index=i, content=f"text {i}",
            content_hash="hash", vector=vectors[i],
        )
        for i in range(2)
    ]  # fmt: skip
    ids = [c.id for c in chunks]
    try:
        store.upsert(chunks)
        # index visibility is eventually consistent: poll each read-after-write check
        wait_until(
            lambda: any(s.doc_id == doc_id and s.content_hash == "hash" for s in store.get_states())
        )
        wait_until(lambda: store.document_count() >= 2)
        wait_until(lambda: sorted(store.ids_for_doc(doc_id)) == sorted(ids))
        store.delete_ids(ids)
        wait_until(lambda: store.ids_for_doc(doc_id) == [])
    finally:
        store.delete_ids(ids)
