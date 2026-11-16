import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from workplace_agent.errors import AppError
from workplace_agent.retrieval.answer import NOT_FOUND_MESSAGE, AskResult

NO_QUESTIONS_MESSAGE = "No evaluation questions found."
EXPECTED_QUESTION_COUNT = 20
UNANSWERABLE = "none"
HIT_RATE_TARGET = 0.90
CITATION_TARGET = 0.90
P95_TARGET_SECONDS = 8.0

type AskFn = Callable[[str], AskResult]


class EvalError(AppError):
    """The evaluation set is missing, empty or malformed."""


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    question: str
    expected_title: str

    @property
    def is_answerable(self) -> bool:
        return self.expected_title != UNANSWERABLE


@dataclass(frozen=True, slots=True)
class QuestionResult:
    question: EvalQuestion
    found: bool
    cited: bool | None  # None means n/a (unanswerable)
    seconds: float


@dataclass(frozen=True, slots=True)
class EvalReport:
    results: list[QuestionResult]
    hit_rate: float
    citation_presence: float
    p95: float
    p50: float

    @property
    def hit_rate_met(self) -> bool:
        return self.hit_rate >= HIT_RATE_TARGET

    @property
    def citation_met(self) -> bool:
        return self.citation_presence >= CITATION_TARGET

    @property
    def p95_met(self) -> bool:
        return self.p95 <= P95_TARGET_SECONDS

    @property
    def passed(self) -> bool:
        return self.hit_rate_met and self.citation_met and self.p95_met


def load_questions(path: Path) -> list[EvalQuestion]:
    """Read the JSON Lines evaluation set.

    Raises:
        EvalError: file missing, no questions, or a malformed line (names the line number).
    """
    if not path.is_file():
        raise EvalError(NO_QUESTIONS_MESSAGE)
    questions: list[EvalQuestion] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalError(f"Invalid evaluation question on line {number}: {exc.msg}") from exc
        question = data.get("question") if isinstance(data, dict) else None
        title = data.get("expected_title") if isinstance(data, dict) else None
        if not isinstance(question, str) or not isinstance(title, str) or not question.strip():
            raise EvalError(
                f"Invalid evaluation question on line {number}: "
                'expected {"question": str, "expected_title": str}'
            )
        questions.append(EvalQuestion(question, title))
    if not questions:
        raise EvalError(NO_QUESTIONS_MESSAGE)
    return questions


def count_warning(count: int) -> str | None:
    if count == EXPECTED_QUESTION_COUNT:
        return None
    return f"Warning: expected {EXPECTED_QUESTION_COUNT} evaluation questions, found {count}."


def nearest_rank(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile: the value at rank ceil(p/100 * n) in sorted order."""
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[rank - 1]


def judge(question: EvalQuestion, result: AskResult) -> tuple[bool, bool | None]:
    """Return (found, cited); cited is None (n/a) for unanswerable questions."""
    if question.is_answerable:
        return question.expected_title in result.retrieved_titles, result.validated_cite_count >= 1
    return result.text == NOT_FOUND_MESSAGE, None


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def run_evaluation(
    questions: list[EvalQuestion],
    ask_fn: AskFn,
    clock: Callable[[], float],
    on_result: Callable[[int, QuestionResult], None] | None = None,
) -> EvalReport:
    results: list[QuestionResult] = []
    for index, question in enumerate(questions, start=1):
        start = clock()
        answer = ask_fn(question.question)
        seconds = clock() - start
        found, cited = judge(question, answer)
        item = QuestionResult(question, found, cited, seconds)
        results.append(item)
        if on_result is not None:
            on_result(index, item)
    answerable = [r for r in results if r.question.is_answerable]
    times = [r.seconds for r in results]
    return EvalReport(
        results=results,
        hit_rate=_ratio(sum(r.found for r in answerable), len(answerable)),
        citation_presence=_ratio(sum(bool(r.cited) for r in answerable), len(answerable)),
        p95=nearest_rank(times, 95),
        p50=nearest_rank(times, 50),
    )


def _yes_no(value: bool | None) -> str:
    return "n/a" if value is None else ("yes" if value else "no")


def format_result_line(index: int, result: QuestionResult) -> str:
    return (
        f"[{index:2d}] found={_yes_no(result.found)} cited={_yes_no(result.cited):<3} "
        f"{result.seconds:4.1f}s  {result.question.question}"
    )


def _label(met: bool) -> str:
    return "meets target" if met else "below target"


def format_totals(report: EvalReport) -> list[str]:
    return [
        f"hit rate: {report.hit_rate * 100:.1f}% ({_label(report.hit_rate_met)}, target ≥ 90%)",
        f"citation presence: {report.citation_presence * 100:.1f}% "
        f"({_label(report.citation_met)}, target ≥ 90%)",
        f"p95 response time: {report.p95:.1f}s ({_label(report.p95_met)}, target ≤ 8.0s)",
        f"p50 response time: {report.p50:.1f}s (for information)",
    ]


def format_verdict(report: EvalReport) -> str:
    if report.passed:
        return "Evaluation passed."
    missed = [
        name
        for name, met in (
            ("hit rate", report.hit_rate_met),
            ("citation presence", report.citation_met),
            ("p95", report.p95_met),
        )
        if not met
    ]
    return f"Evaluation failed: {', '.join(missed)}"
