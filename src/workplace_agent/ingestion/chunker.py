"""Pure heading-aware chunker: Markdown + page map in, token-bounded chunks out.

Design notes:
- Offsets are Python ``str`` indices into ``ParsedDocument.markdown`` (unicodeCodePoint).
  Page lookups use the original offsets; ``<!-- PageBreak -->`` markers are never part of a
  block, so they are stripped from content without shifting anything.
- A heading closes the current chunk unless the chunk is "tiny" (< ``TINY_TOKENS``); tiny
  chunks are merged with the following section; the label is the first non-heading unit's.
- Tables are atomic units (never split mid-row). An oversized table is split by rows with its
  header repeated. Per-page continuation tables are separate blocks; they may share a chunk,
  which then spans several pages.
- Overlap carries trailing paragraph units (<= overlap tokens) into the next window.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from workplace_agent.ingestion.models import ParsedDocument
from workplace_agent.ingestion.parser import page_for_offset

PAGE_BREAK = "<!-- PageBreak -->"
IMAGE_TEXT_SECTION = "Image text"
TINY_TOKENS = 48

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_TABLE_SEPARATOR = re.compile(r"^\|[\s:|-]*-[\s:|-]*\|?\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class TextChunk:
    content: str
    section: str
    page_start: int
    page_end: int
    chunk_index: int


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    section: str
    page_start: int
    page_end: int
    is_heading: bool = False
    is_table: bool = False


type PagesFn = Callable[[int, int], tuple[int, int]]


@lru_cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def embed_text(title: str, section: str, content: str) -> str:
    head = f"{title} > {section}" if section else title
    return f"{head}\n{content}"


def chunk_document(
    doc: ParsedDocument, *, max_tokens: int = 512, overlap_tokens: int = 64
) -> list[TextChunk]:
    units = _build_units(doc, max_tokens)
    chunks = _pack(units, max_tokens, overlap_tokens)
    for page in sorted({p for p, _ in doc.uncovered_lines}):
        lines = [
            _Unit(text, IMAGE_TEXT_SECTION, page, page)
            for p, text in doc.uncovered_lines
            if p == page
        ]
        chunks.extend(_pack(lines, max_tokens, overlap_tokens))
    return [
        TextChunk(c.content, c.section, c.page_start, c.page_end, i) for i, c in enumerate(chunks)
    ]


# --- block parsing -------------------------------------------------------------------------


def _build_units(doc: ParsedDocument, max_tokens: int) -> list[_Unit]:
    spans = doc.page_spans
    last_page = 1

    def pages(start: int, end: int) -> tuple[int, int]:
        nonlocal last_page
        first = page_for_offset(spans, start) or last_page
        last = page_for_offset(spans, max(start, end - 1)) or first
        last_page = last
        return first, last

    units: list[_Unit] = []
    headings: list[tuple[int, str]] = []
    offset = 0
    para: list[tuple[int, str]] = []  # (offset, line)
    table: list[tuple[int, str]] = []

    def section() -> str:
        return " > ".join(text for _, text in headings)

    def flush_para() -> None:
        if not para:
            return
        start = para[0][0]
        text = "\n".join(line for _, line in para).strip()
        end = para[-1][0] + len(para[-1][1])
        first, last = pages(start, end)
        for piece in _split_text(text, max_tokens):
            units.append(_Unit(piece, section(), first, last))
        para.clear()

    def flush_table() -> None:
        if table:
            units.extend(_table_units(table, section(), max_tokens, pages))
            table.clear()

    for raw in doc.markdown.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        start, offset = offset, offset + len(raw)
        stripped = line.strip()
        if stripped.startswith("|"):
            flush_para()
            table.append((start, stripped))
            continue
        flush_table()
        if not stripped or stripped == PAGE_BREAK:
            flush_para()
        elif m := _HEADING.match(stripped):
            flush_para()
            level = len(m.group(1))
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, m.group(2)))
            first, last = pages(start, start + len(line))
            units.append(_Unit(stripped, section(), first, last, is_heading=True))
        else:
            para.append((start, stripped))
    flush_para()
    flush_table()
    return units


def _table_units(
    rows: list[tuple[int, str]], section: str, max_tokens: int, pages: PagesFn
) -> list[_Unit]:
    has_header = len(rows) >= 2 and bool(_TABLE_SEPARATOR.match(rows[1][1]))
    header = [line for _, line in rows[:2]] if has_header else []
    body = rows[2:] if has_header else rows

    def unit(lines: list[str], first_row: int, last_row: tuple[int, str]) -> _Unit:
        first, last = pages(first_row, last_row[0] + len(last_row[1]))
        return _Unit("\n".join(lines), section, first, last, is_table=True)

    whole = "\n".join(line for _, line in rows)
    if count_tokens(whole) <= max_tokens or not body:
        return [unit([line for _, line in rows], rows[0][0], rows[-1])]

    units: list[_Unit] = []
    current: list[tuple[int, str]] = []
    for row in body:
        candidate = "\n".join(header + [line for _, line in current + [row]])
        if current and count_tokens(candidate) > max_tokens:
            units.append(unit(header + [line for _, line in current], current[0][0], current[-1]))
            current = []
        current.append(row)
    if current:
        units.append(unit(header + [line for _, line in current], current[0][0], current[-1]))
    return units


# --- oversized paragraph splitting -----------------------------------------------------------


def _split_text(text: str, max_tokens: int) -> list[str]:
    """Split a paragraph into pieces of at most ``max_tokens``, preferring sentence bounds."""
    if count_tokens(text) <= max_tokens:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if count_tokens(sentence) > max_tokens:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_tokens(sentence, max_tokens))
            continue
        candidate = f"{current} {sentence}" if current else sentence
        if current and count_tokens(candidate) > max_tokens:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_tokens(text: str, max_tokens: int) -> list[str]:
    tokens = _encoding().encode(text)
    return [
        _encoding().decode(tokens[i : i + max_tokens]) for i in range(0, len(tokens), max_tokens)
    ]


# --- packing ---------------------------------------------------------------------------------


def _pack(units: list[_Unit], max_tokens: int, overlap_tokens: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    current: list[_Unit] = []
    fresh = 0  # index in `current` of the first non-overlap unit

    def joined(items: list[_Unit]) -> str:
        return "\n\n".join(u.text for u in items)

    def emit() -> None:
        body = current[fresh:]
        if not body:
            return
        chunks.append(
            TextChunk(
                content=joined(current),
                section=next((u for u in body if not u.is_heading), body[0]).section,
                page_start=min(u.page_start for u in current),
                page_end=max(u.page_end for u in current),
                chunk_index=0,
            )
        )

    for unit in units:
        if len(current) > fresh:
            fresh_tokens = count_tokens(joined(current[fresh:]))
            if unit.is_heading and fresh_tokens >= TINY_TOKENS:
                emit()
                current, fresh = [], 0
            elif count_tokens(joined([*current, unit])) > max_tokens:
                emit()
                current = _overlap_tail(current, overlap_tokens)
                fresh = len(current)
                if current and count_tokens(joined([*current, unit])) > max_tokens:
                    current, fresh = [], 0
        current.append(unit)
    emit()
    return chunks


def _overlap_tail(units: list[_Unit], overlap_tokens: int) -> list[_Unit]:
    tail: list[_Unit] = []
    total = 0
    for unit in reversed(units):
        if unit.is_heading or unit.is_table:
            break
        total += count_tokens(unit.text)
        if total > overlap_tokens:
            break
        tail.insert(0, unit)
    return tail
