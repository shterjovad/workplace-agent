from dataclasses import dataclass, field

from workplace_agent.errors import FailureReason


@dataclass(frozen=True, slots=True)
class BlobItem:
    name: str


@dataclass(frozen=True, slots=True)
class PageSpan:
    """Character range [start, end) of the markdown that belongs to a physical page."""

    page: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class TableInfo:
    start: int
    end: int
    pages: tuple[int, ...]


@dataclass(slots=True)
class ParsedDocument:
    markdown: str
    page_spans: list[PageSpan] = field(default_factory=list)
    tables: list[TableInfo] = field(default_factory=list)
    uncovered_lines: list[tuple[int, str]] = field(default_factory=list)  # (page, text)


@dataclass(slots=True, kw_only=True)
class Chunk:
    id: str
    doc_id: str
    title: str
    source_path: str
    page_start: int
    page_end: int
    section: str
    chunk_index: int
    content: str
    content_hash: str
    vector: list[float] | None = None


@dataclass(frozen=True, slots=True)
class IndexedDocState:
    doc_id: str
    source_path: str
    content_hash: str


@dataclass(slots=True)
class IngestSummary:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: list[tuple[str, FailureReason]] = field(default_factory=list)
    skipped_non_pdf: list[str] = field(default_factory=list)
    total_passages: int = 0
