from workplace_agent.ingestion.chunker import (
    PAGE_BREAK,
    chunk_document,
    count_tokens,
    embed_text,
)
from workplace_agent.ingestion.models import PageSpan, ParsedDocument


def make_doc(markdown: str, uncovered: list[tuple[int, str]] | None = None) -> ParsedDocument:
    """Pages are delimited by PageBreak markers, which live inside the page spans."""
    spans: list[PageSpan] = []
    start = 0
    for page, part in enumerate(markdown.split(PAGE_BREAK), start=1):
        end = start + len(part) + (len(PAGE_BREAK) if page < markdown.count(PAGE_BREAK) + 1 else 0)
        spans.append(PageSpan(page, start, min(end, len(markdown))))
        start = end
    return ParsedDocument(markdown=markdown, page_spans=spans, uncovered_lines=uncovered or [])


def test_multi_page_text_sections_and_pages() -> None:
    md = (
        "# Handbook\n\n## Leave\n\n" + "Leave text on page one. " * 40 + f"\n\n{PAGE_BREAK}\n\n"
        "## Conduct\n\nConduct text on page two.\n"
    )
    chunks = chunk_document(make_doc(md))

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].section == "Handbook > Leave"
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 1)
    assert chunks[-1].section == "Handbook > Conduct"
    assert (chunks[-1].page_start, chunks[-1].page_end) == (2, 2)
    assert all(PAGE_BREAK not in c.content for c in chunks)


def test_table_continued_on_next_page_shares_chunk_with_page_range() -> None:
    header = "| Item | Limit |\n| --- | --- |\n"
    md = (
        "# Policy\n\nIntro.\n\n"
        f"{PAGE_BREAK}\n\n{header}| Hotel | 150 |\n\n"
        f"{PAGE_BREAK}\n\n| Meals | 60 |\n| Taxi | 40 |\n"
    )
    chunks = chunk_document(make_doc(md))

    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 3)
    assert "| Hotel | 150 |" in chunks[0].content
    assert "| Taxi | 40 |" in chunks[0].content
    assert PAGE_BREAK not in chunks[0].content


def test_oversized_table_splits_by_rows_with_header_repeated() -> None:
    header = "| Item | Limit |\n| --- | --- |"
    rows = [f"| Item number {i} with words | {i} |" for i in range(200)]
    md = "## Rates\n\n" + header + "\n" + "\n".join(rows) + "\n"
    chunks = chunk_document(make_doc(md), max_tokens=100, overlap_tokens=10)

    table_chunks = [c for c in chunks if "| Item number" in c.content]
    assert len(table_chunks) > 1
    for chunk in table_chunks:
        assert count_tokens(chunk.content) <= 100
        assert "| Item | Limit |" in chunk.content
        body = [ln for ln in chunk.content.splitlines() if ln.startswith("| Item number")]
        assert all(ln.endswith("|") for ln in body)  # no row cut in half
    seen = [ln for c in table_chunks for ln in c.content.splitlines() if "Item number" in ln]
    assert seen == rows


def test_token_cap_and_overlap_for_long_paragraph() -> None:
    sentences = [f"Sentence number {i} says something useful about policy." for i in range(300)]
    md = "# Long\n\n" + " ".join(sentences) + "\n"
    chunks = chunk_document(make_doc(md), max_tokens=512, overlap_tokens=64)

    assert len(chunks) > 1
    assert all(count_tokens(c.content) <= 512 for c in chunks)


def test_paragraph_windows_overlap() -> None:
    paras = [f"Paragraph {i}. " + "word " * 25 for i in range(40)]
    md = "# T\n\n" + "\n\n".join(paras) + "\n"
    chunks = chunk_document(make_doc(md), max_tokens=120, overlap_tokens=40)

    assert len(chunks) > 2
    assert all(count_tokens(c.content) <= 120 for c in chunks)
    last_para_of_first = chunks[0].content.split("\n\n")[-1]
    assert last_para_of_first in chunks[1].content


def test_last_page_content_is_kept() -> None:
    md = (
        f"# A\n\nFirst.\n\n{PAGE_BREAK}\n\nMiddle.\n\n"
        f"{PAGE_BREAK}\n\n## End\n\nLast sentence at Lake Bled.\n"
    )
    chunks = chunk_document(make_doc(md))

    last = chunks[-1]
    assert "Lake Bled" in last.content
    assert last.page_end == 3


def test_uncovered_lines_become_image_text_chunks_on_their_page() -> None:
    doc = make_doc("# A\n\nBody.\n", uncovered=[(1, "Secret code 7741")])
    chunks = chunk_document(doc)

    assert chunks[-1].section == "Image text"
    assert (chunks[-1].page_start, chunks[-1].page_end) == (1, 1)
    assert chunks[-1].content == "Secret code 7741"
    assert chunks[-1].chunk_index == len(chunks) - 1


def test_embed_text_format() -> None:
    assert embed_text("Doc", "A > B", "body") == "Doc > A > B\nbody"


def test_block_crossing_a_page_boundary_gets_page_range() -> None:
    md = "# A\n\nA paragraph that runs across the page boundary.\n"
    cut = md.index("across")
    doc = ParsedDocument(markdown=md, page_spans=[PageSpan(4, 0, cut), PageSpan(5, cut, len(md))])
    chunk = chunk_document(doc)[0]
    assert (chunk.page_start, chunk.page_end) == (4, 5)
