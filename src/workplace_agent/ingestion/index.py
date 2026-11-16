from datetime import UTC, datetime
from typing import Any

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchAlgorithmMetric,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from workplace_agent.ingestion.models import Chunk, IndexedDocState
from workplace_agent.retrieval.models import RetrievedChunk

EMBEDDING_DIMENSIONS = 1536
BATCH_SIZE = 1000
VECTOR_K = 50
VECTOR_FIELD = "content_vector"
VECTOR_PROFILE = "hnsw-cosine-profile"
VECTOR_ALGORITHM = "hnsw-cosine"


def build_index_definition(name: str) -> SearchIndex:
    string, int32 = SearchFieldDataType.STRING, SearchFieldDataType.INT32
    fields = [
        SimpleField(name="id", type=string, key=True),
        SimpleField(name="doc_id", type=string, filterable=True),
        SearchableField(name="title", type=string, filterable=True),
        SimpleField(name="source_path", type=string, filterable=True),
        SimpleField(name="page_start", type=int32, filterable=True),
        SimpleField(name="page_end", type=int32, filterable=True),
        SearchableField(name="section", type=string),
        SimpleField(name="chunk_index", type=int32, filterable=True, sortable=True),
        SearchableField(name="content", type=string),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.SINGLE),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name=VECTOR_PROFILE,
        ),
        SimpleField(name="content_hash", type=string, filterable=True),
        SimpleField(name="ingested_at", type=SearchFieldDataType.DATE_TIME_OFFSET),
    ]
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name=VECTOR_ALGORITHM,
                parameters=HnswParameters(metric=VectorSearchAlgorithmMetric.COSINE),
            )
        ],
        profiles=[
            VectorSearchProfile(name=VECTOR_PROFILE, algorithm_configuration_name=VECTOR_ALGORITHM)
        ],
    )
    return SearchIndex(name=name, fields=fields, vector_search=vector_search)


def _to_document(chunk: Chunk, ingested_at: str) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "source_path": chunk.source_path,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section": chunk.section,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "content_vector": chunk.vector,
        "content_hash": chunk.content_hash,
        "ingested_at": ingested_at,
    }


def _quote(value: str) -> str:
    return value.replace("'", "''")


class SearchChunkStore:
    def __init__(
        self, index_client: SearchIndexClient, search_client: SearchClient, index_name: str
    ) -> None:
        self._index_client = index_client
        self._search = search_client
        self._index_name = index_name

    def ensure_index(self) -> None:
        self._index_client.create_or_update_index(build_index_definition(self._index_name))

    def get_states(self) -> list[IndexedDocState]:
        results = self._search.search(
            search_text="*",
            filter="chunk_index eq 0",
            select=["doc_id", "source_path", "content_hash"],
            top=BATCH_SIZE,
        )
        return [IndexedDocState(r["doc_id"], r["source_path"], r["content_hash"]) for r in results]

    def upsert(self, chunks: list[Chunk]) -> None:
        ingested_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = [_to_document(c, ingested_at) for c in chunks[start : start + BATCH_SIZE]]
            self._search.merge_or_upload_documents(documents=batch)

    def delete_ids(self, ids: list[str]) -> None:
        for start in range(0, len(ids), BATCH_SIZE):
            self._search.delete_documents(
                documents=[{"id": i} for i in ids[start : start + BATCH_SIZE]]
            )

    def ids_for_doc(self, doc_id: str) -> list[str]:
        results = self._search.search(
            search_text="*", filter=f"doc_id eq '{_quote(doc_id)}'", select=["id"]
        )
        return [r["id"] for r in results]  # the SDK pages through continuation tokens

    def document_count(self) -> int:
        return int(self._search.get_document_count())

    def hybrid_search(self, text: str, vector: list[float], top: int) -> list[RetrievedChunk]:
        results = self._search.search(
            search_text=text,
            vector_queries=[
                VectorizedQuery(vector=vector, k_nearest_neighbors=VECTOR_K, fields=VECTOR_FIELD)
            ],
            top=top,
            select=["title", "page_start", "page_end", "section", "content"],
        )
        return [
            RetrievedChunk(
                title=r["title"],
                page_start=r["page_start"],
                page_end=r["page_end"],
                content=r["content"],
                score=float(r["@search.score"]),
                section=r.get("section") or "",
            )
            for r in results
        ]
