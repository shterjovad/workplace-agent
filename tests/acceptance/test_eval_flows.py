# @spec: 001-document-ingestion-and-qa-cli
# @regression
"""Spec 2.5: `eval` over the real 20-question set (hermetic, fake adapters)."""

import json
import re
from pathlib import Path

import pytest

from tests.acceptance.conftest import World, pdf
from workplace_agent import cli
from workplace_agent.retrieval.models import AnswerSentence, RetrievedChunk, StructuredAnswer

pytestmark = pytest.mark.regression

QUESTIONS = Path(__file__).parents[2] / "eval" / "questions.jsonl"


def _entries() -> list[dict[str, str]]:
    return [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]


@pytest.fixture
def library(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """Each title's document contains its own questions; the model cites the top passage."""
    monkeypatch.setenv("EVAL_PATH", str(QUESTIONS))
    from workplace_agent.config import get_settings

    get_settings.cache_clear()
    by_title: dict[str, list[str]] = {}
    for entry in _entries():
        if entry["expected_title"] != "none":
            by_title.setdefault(entry["expected_title"], []).append(entry["question"])
    for title, questions in by_title.items():
        world.put(f"{title}.pdf", pdf("\n\n".join(questions)))
    assert world.run("ingest").exit_code == 0
    unanswerable = {e["question"] for e in _entries() if e["expected_title"] == "none"}

    def answer(question: str, passages: list[RetrievedChunk]) -> StructuredAnswer:
        if question in unanswerable:
            return StructuredAnswer(False)
        return StructuredAnswer(True, [AnswerSentence("Answer.", [1])])

    world.chat.answer = answer  # type: ignore[method-assign]
    return world


def test_eval_set_has_exactly_20_questions_with_3_unanswerable() -> None:
    entries = _entries()
    assert len(entries) == 20
    assert sum(e["expected_title"] == "none" for e in entries) == 3


def test_eval_prints_20_lines_and_four_labelled_totals(library: World) -> None:
    result = library.run("eval")
    out = result.stdout
    assert result.exit_code == 0, out
    assert len(re.findall(r"^\[\s*\d+\] found=", out, flags=re.MULTILINE)) == 20
    assert re.search(r"^hit rate: .*\(meets target", out, flags=re.MULTILINE)
    assert re.search(r"^citation presence: .*\(meets target", out, flags=re.MULTILINE)
    assert re.search(r"^p95 response time: .*\(meets target", out, flags=re.MULTILINE)
    assert re.search(r"^p50 response time: .*\(for information\)", out, flags=re.MULTILINE)


def test_unanswerable_question_line_shows_found_yes_cited_na(library: World) -> None:
    out = library.run("eval").stdout
    line = next(ln for ln in out.splitlines() if "CEO's favourite food" in ln)
    assert "found=yes" in line and "cited=n/a" in line


def test_slow_answers_mark_p95_below_target_and_fail_the_run(
    library: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter(range(0, 10_000, 9))  # every start/stop pair measures 9 seconds
    monkeypatch.setattr(cli, "perf_counter", lambda: float(next(ticks)))
    result = library.run("eval")
    assert "p95 response time: 9.0s (below target" in result.stdout
    assert result.exit_code == 1
