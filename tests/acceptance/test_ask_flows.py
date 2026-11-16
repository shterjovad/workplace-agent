# @spec: 001-document-ingestion-and-qa-cli
# @regression
"""Spec 2.4: the `ask` command output contract (hermetic)."""

import re

import pytest

from tests.acceptance.conftest import World, pdf
from workplace_agent.retrieval.models import AnswerSentence, StructuredAnswer

NOT_FOUND_MESSAGE = "I couldn't find this in the company documents."

pytestmark = pytest.mark.regression

SOURCE_LINE = re.compile(r"^\[\d+\] .+, (p\. \d+|pp\. \d+–\d+)$")


def _body_and_sources(output: str) -> tuple[str, list[str]]:
    body, _, sources = output.strip().partition("\n\nSources:\n")
    return body, sources.splitlines()


def test_answer_has_cap_markers_on_every_sentence_and_wellformed_sources(world: World) -> None:
    world.put("HR Leave Policy.pdf", pdf("Employees may carry over up to 5 days."))
    world.run("ingest")
    wordy = " ".join(["word"] * 100) + "."
    world.chat.answer = lambda q, p: StructuredAnswer(  # type: ignore[method-assign]
        True,
        [
            AnswerSentence("Up to 5 days carry over.", [1]),
            AnswerSentence(wordy, [1]),
            AnswerSentence(wordy, [1]),  # pushes the answer past 150 words
        ],
    )
    result = world.run("ask", "How many vacation days can I carry over?")
    body, sources = _body_and_sources(result.stdout)
    assert result.exit_code == 0
    assert len(re.sub(r"\[\d+\]", "", body).split()) <= 150
    assert re.fullmatch(r"(?:[^\[\]]+?\. (?:\[\d+\])+ ?)+", body), body  # marker on every sentence
    assert sources and all(SOURCE_LINE.match(s) for s in sources)


def test_two_facts_on_the_same_page_list_the_source_once(world: World) -> None:
    section = "word " * 60
    page = (
        f"# Meals\n\n{section}\n\nMeal limit is EUR 45.\n\n"
        f"# Hotels\n\n{section}\n\nHotel cap is 150."
    )
    world.put("Travel.pdf", pdf(page))
    world.run("ingest")
    assert len({c.chunk_index for c in world.store.chunks.values()}) >= 2
    world.chat.answer = lambda q, p: StructuredAnswer(  # type: ignore[method-assign]
        True, [AnswerSentence("Meals EUR 45.", [1]), AnswerSentence("Hotels 150.", [2])]
    )
    result = world.run("ask", "meals and hotels")
    assert world.sources(result) == ["[1] Travel, p. 1"]


def test_unanswerable_question_gets_exact_not_found_and_no_sources(world: World) -> None:
    world.put("HR Leave Policy.pdf", pdf("Employees may carry over up to 5 days."))
    world.run("ingest")
    result = world.run("ask", "What is the CEO's favourite food?")
    assert result.exit_code == 0
    assert result.stdout.strip() == NOT_FOUND_MESSAGE
    assert "Sources" not in result.stdout


def test_partial_answer_names_the_missing_part_in_a_final_sentence(world: World) -> None:
    world.put("Travel.pdf", pdf("Meals are reimbursed up to EUR 45 per day."))
    world.chat.needles["meal"] = "EUR 45"
    world.chat.missing["meal"] = "the parking allowance"
    world.run("ingest")
    result = world.run("ask", "What are the meal and parking allowances?")
    body, sources = _body_and_sources(result.stdout)
    assert "EUR 45. [1]" in body
    assert body.endswith(
        "I couldn't find information about the parking allowance in the company documents."
    )
    assert sources == ["[1] Travel, p. 1"]
