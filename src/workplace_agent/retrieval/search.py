from workplace_agent.ports import ChunkStore, Embedder
from workplace_agent.retrieval.models import RetrievedChunk
from workplace_agent.telemetry import get_tracer

TOP_K = 5
tracer = get_tracer()


def is_library_empty(store: ChunkStore) -> bool:
    return store.document_count() == 0


def retrieve(
    question: str, embedder: Embedder, store: ChunkStore, top_k: int = TOP_K
) -> list[RetrievedChunk]:
    with tracer.start_as_current_span("embed"):
        vector = embedder.embed([question])[0]
    with tracer.start_as_current_span("search"):
        return store.hybrid_search(question, vector, top_k)
