# @spec: 001-document-ingestion-and-qa-cli
# @regression
"""Spec 2.1 / 2.4 against the deployed library: read-only `ask` calls plus local PDF checks.

Assumes the 12 sample documents in samples/documents are the ingested library. Nothing is
written to blob storage or the search index.
"""

import re
from pathlib import Path

import pytest
from pypdf import PdfReader
from typer.testing import CliRunner

from workplace_agent.cli import app
from workplace_agent.config import Settings, get_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.regression,
    pytest.mark.skipif(
        not (Settings().search_endpoint and Settings().azure_openai_endpoint),
        reason="Azure search/OpenAI endpoints not configured",
    ),
]

NOT_FOUND_MESSAGE = "I couldn't find this in the company documents."
DOCS = Path(__file__).parents[2] / "samples" / "documents"
SOURCE = re.compile(r"^\[(\d+)\] (.+), (?:p\. (\d+)|pp\. (\d+)–(\d+))$", re.MULTILINE)
runner = CliRunner()


def ask(question: str) -> str:
    get_settings.cache_clear()
    result = runner.invoke(app, ["ask", question])
    assert result.exit_code == 0, result.output
    return result.stdout.strip()


def test_carry_over_answer_is_cited_and_every_cited_page_contains_the_fact() -> None:
    out = ask("How many vacation days can I carry over?")
    body, _, _ = out.partition("\n\nSources:")
    assert len(re.sub(r"\[\d+\]", "", body).split()) <= 150
    sources = SOURCE.findall(out)
    assert sources, out
    assert len({(t, a, b, c) for _, t, a, b, c in sources}) == len(sources)  # no duplicates
    assert {n for n, *_ in sources} == set(re.findall(r"\[(\d+)\]", body))
    for _, title, single, first, _last in sources:
        page = int(single or first)
        text = PdfReader(DOCS / f"{title}.pdf").pages[page - 1].extract_text()
        assert "carry over up to 5 unused vacation days" in text, (title, page)
    assert "5" in body


@pytest.mark.parametrize(
    ("question", "fact", "source_line"),
    [
        ("Where is the annual company retreat held?", "Lake Bled", "Employee Handbook, p. 12"),
        (
            "What is the daily meal allowance for domestic trips?",
            "45",
            "Travel and Expenses Policy, p. 1",
        ),
        ("What is the helpdesk PIN reset code?", "7741", "IT Security Policy, p. 1"),
    ],
)
def test_facts_from_last_page_table_and_image_are_answered_with_their_page(
    question: str, fact: str, source_line: str
) -> None:
    out = ask(question)
    assert fact in out
    assert source_line in out


def test_unanswerable_question_gets_exact_not_found_reply() -> None:
    assert ask("What is the CEO's favourite food?") == NOT_FOUND_MESSAGE


def test_partly_answerable_question_names_the_missing_parking_part() -> None:
    out = ask("What are the meal and parking allowances?")
    body = out.partition("\n\nSources:")[0]
    assert "45" in body
    # The model words the missing part itself, so check the sentence shape, not the exact noun.
    assert re.search(
        r"I couldn't find information about [^.]*parking[^.]* in the company documents\.$", body
    ), body
