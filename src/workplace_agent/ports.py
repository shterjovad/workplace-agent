from typing import Protocol

from workplace_agent.ingestion.models import Chunk, IndexedDocState, ParsedDocument
from workplace_agent.retrieval.models import RetrievedChunk, StructuredAnswer


class BlobSource(Protocol):
    def list_names(self) -> list[str]: ...

    def download(self, name: str) -> bytes: ...


class DocumentParser(Protocol):
    def parse(self, name: str, data: bytes) -> ParsedDocument:
        """Raises ParseError on failure."""
        ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ChunkStore(Protocol):
    def ensure_index(self) -> None: ...

    def get_states(self) -> list[IndexedDocState]: ...

    def upsert(self, chunks: list[Chunk]) -> None: ...

    def delete_ids(self, ids: list[str]) -> None: ...

    def ids_for_doc(self, doc_id: str) -> list[str]: ...

    def document_count(self) -> int: ...

    def hybrid_search(self, text: str, vector: list[float], top: int) -> list[RetrievedChunk]: ...


class ChatModel(Protocol):
    def answer(self, question: str, passages: list[RetrievedChunk]) -> StructuredAnswer: ...
