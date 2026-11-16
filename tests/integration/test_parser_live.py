import os
from pathlib import Path

import pytest

from workplace_agent.azure_clients import build_docintel_client
from workplace_agent.config import Settings
from workplace_agent.ingestion.chunker import chunk_document, count_tokens
from workplace_agent.ingestion.models import ParsedDocument
from workplace_agent.ingestion.parser import DocumentIntelligenceParser, page_for_offset

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("DOCINTEL_ENDPOINT") or Settings().docintel_endpoint),
        reason="DOCINTEL_ENDPOINT not set",
    ),
]

DOCS = Path(__file__).parents[2] / "samples" / "documents"


@pytest.fixture(scope="module")
def parser() -> DocumentIntelligenceParser:
    return DocumentIntelligenceParser(build_docintel_client(Settings()))


def parse(parser: DocumentIntelligenceParser, name: str) -> ParsedDocument:
    return parser.parse(name, (DOCS / name).read_bytes())


def test_handbook_has_12_pages_and_last_sentence_on_page_12(
    parser: DocumentIntelligenceParser,
) -> None:
    doc = parse(parser, "Employee Handbook.pdf")
    assert {s.page for s in doc.page_spans} == set(range(1, 13))
    assert page_for_offset(doc.page_spans, doc.markdown.index("Lake Bled")) == 12


def test_travel_policy_tables_are_located_on_several_pages(
    parser: DocumentIntelligenceParser,
) -> None:
    doc = parse(parser, "Travel and Expenses Policy.pdf")
    pages = {p for t in doc.tables for p in t.pages}
    assert len(pages) > 1
    assert all(t.pages for t in doc.tables)


def test_image_text_is_captured_on_page_1(parser: DocumentIntelligenceParser) -> None:
    doc = parse(parser, "IT Security Policy.pdf")
    if "7741" in doc.markdown:
        assert page_for_offset(doc.page_spans, doc.markdown.index("7741")) == 1
    else:
        assert any(page == 1 and "7741" in text for page, text in doc.uncovered_lines)


def test_chunker_on_live_documents(parser: DocumentIntelligenceParser) -> None:
    handbook = chunk_document(parse(parser, "Employee Handbook.pdf"))
    travel = chunk_document(parse(parser, "Travel and Expenses Policy.pdf"))

    assert any(c.page_start == 12 for c in handbook)
    assert all(c.page_start <= c.page_end for c in handbook + travel)
    assert {c.page_start for c in travel} >= {1, 2, 3}
    assert all(count_tokens(c.content) <= 512 for c in handbook + travel)
    assert all("PageBreak" not in c.content for c in handbook + travel)
