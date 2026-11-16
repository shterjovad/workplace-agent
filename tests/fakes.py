import hashlib
from dataclasses import replace

from workplace_agent.ingestion.models import Chunk, IndexedDocState, ParsedDocument
from workplace_agent.retrieval.models import RetrievedChunk, StructuredAnswer


class FakeBlobSource:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files: dict[str, bytes] = dict(files or {})
        self.downloaded: list[str] = []

    def list_names(self) -> list[str]:
        return sorted(self.files)

    def download(self, name: str) -> bytes:
        self.downloaded.append(name)
        return self.files[name]


class FakeParser:
    def __init__(
        self,
        results: dict[str, ParsedDocument | Exception] | None = None,
        default: ParsedDocument | None = None,
    ) -> None:
        self.results = results or {}
        self.default = default
        self.calls: list[str] = []

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        self.calls.append(name)
        result = self.results.get(name, self.default)
        if result is None:
            result = ParsedDocument(markdown=data.decode("utf-8", errors="replace"))
        if isinstance(result, Exception):
            raise result
        return result


class FakeEmbedder:
    def __init__(self, dims: int = 4) -> None:
        self.dims = dims
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[i] / 255 for i in range(self.dims)]


class InMemoryChunkStore:
    def __init__(self) -> None:
        self.chunks: dict[str, Chunk] = {}
        self.index_ensured = False

    def ensure_index(self) -> None:
        self.index_ensured = True

    def get_states(self) -> list[IndexedDocState]:
        return [
            IndexedDocState(c.doc_id, c.source_path, c.content_hash)
            for c in self.chunks.values()
            if c.chunk_index == 0
        ]

    def upsert(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            self.chunks[chunk.id] = replace(chunk)

    def delete_ids(self, ids: list[str]) -> None:
        for chunk_id in ids:
            self.chunks.pop(chunk_id, None)

    def ids_for_doc(self, doc_id: str) -> list[str]:
        return [c.id for c in self.chunks.values() if c.doc_id == doc_id]

    def document_count(self) -> int:
        return len(self.chunks)

    def hybrid_search(self, text: str, vector: list[float], top: int) -> list[RetrievedChunk]:
        words = set(text.lower().split())
        scored = [
            RetrievedChunk(
                title=c.title,
                page_start=c.page_start,
                page_end=c.page_end,
                content=c.content,
                score=float(len(words & set(c.content.lower().split()))),
            )
            for c in self.chunks.values()
        ]
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top]


class FakeChatModel:
    def __init__(self, answer: StructuredAnswer) -> None:
        self.preset = answer
        self.calls: list[tuple[str, list[RetrievedChunk]]] = []

    def answer(self, question: str, passages: list[RetrievedChunk]) -> StructuredAnswer:
        self.calls.append((question, list(passages)))
        return self.preset
