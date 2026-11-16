from types import SimpleNamespace as NS
from typing import Any

import pytest

from workplace_agent.ingestion.models import PageSpan
from workplace_agent.ingestion.parser import build_parsed_document, page_for_offset


def span(offset: int, length: int) -> NS:
    return NS(offset=offset, length=length)


def fake_result() -> Any:
    content = "# Title\n\nPage one text\n\n<!-- PageBreak -->\n\nPage two text\n\n| a | b |\n"
    p2 = content.index("Page two")
    table_start = content.index("| a")
    return NS(
        content=content,
        pages=[
            NS(
                page_number=1,
                spans=[span(0, p2 - 10)],
                lines=[NS(content="Page one   text"), NS(content="Secret code 7741")],
            ),
            NS(
                page_number=2,
                spans=[span(p2 - 10, len(content) - (p2 - 10))],
                lines=[NS(content="Page two text"), NS(content="")],
            ),
        ],
        tables=[
            NS(
                spans=[span(table_start, len(content) - table_start)],
                bounding_regions=[NS(page_number=2), NS(page_number=3)],
            )
        ],
    )


def test_page_spans_sorted_and_mapped() -> None:
    result = fake_result()
    result.pages.reverse()
    doc = build_parsed_document(result)

    assert [s.page for s in doc.page_spans] == [1, 2]
    assert doc.page_spans[0].start == 0
    assert doc.page_spans[0].end == doc.page_spans[1].start


def test_page_for_offset_boundaries() -> None:
    spans = [PageSpan(1, 0, 10), PageSpan(2, 10, 25)]
    assert page_for_offset(spans, 0) == 1
    assert page_for_offset(spans, 9) == 1
    assert page_for_offset(spans, 10) == 2
    assert page_for_offset(spans, 24) == 2
    assert page_for_offset(spans, 25) is None


def test_tables_have_range_and_pages() -> None:
    doc = build_parsed_document(fake_result())
    assert len(doc.tables) == 1
    assert doc.markdown[doc.tables[0].start : doc.tables[0].end] == "| a | b |\n"
    assert doc.tables[0].pages == (2, 3)


def test_lines_missing_from_markdown_are_uncovered() -> None:
    doc = build_parsed_document(fake_result())
    # Whitespace differences and empty lines do not count; only the figure text is uncovered.
    assert doc.uncovered_lines == [(1, "Secret code 7741")]


@pytest.mark.parametrize("pages", [None, []])
def test_empty_result(pages: Any) -> None:
    doc = build_parsed_document(NS(content="", pages=pages, tables=None))
    assert doc.page_spans == []
    assert doc.tables == []
    assert doc.uncovered_lines == []
