import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.fakes import FakeChatModel, FakeEmbedder, InMemoryChunkStore
from workplace_agent import cli
from workplace_agent.cli import app
from workplace_agent.config import get_settings
from workplace_agent.retrieval.answer import NOT_FOUND_MESSAGE, AskResult
from workplace_agent.retrieval.evaluation import (
    NO_QUESTIONS_MESSAGE,
    EvalError,
    EvalQuestion,
    count_warning,
    format_result_line,
    format_totals,
    format_verdict,
    judge,
    load_questions,
    nearest_rank,
    run_evaluation,
)
from workplace_agent.retrieval.models import AnswerSentence, StructuredAnswer

runner = CliRunner()

ANSWERABLE = EvalQuestion("How many vacation days?", "Vacation Policy")
UNANSWERABLE = EvalQuestion("What is the CEO's shoe size?", "none")


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class FakeClock:
    """Advances by the next scripted duration on every start/stop pair."""

    def __init__(self, durations: list[float]) -> None:
        self.durations = list(durations)
        self.now = 0.0
        self.starting = True

    def __call__(self) -> float:
        if self.starting:
            self.starting = False
        else:
            self.now += self.durations.pop(0)
            self.starting = True
        return self.now


def _run(
    answers: list[AskResult], durations: list[float], questions: list[EvalQuestion] | None = None
):
    qs = questions or [ANSWERABLE] * len(answers)
    it = iter(answers)
    return run_evaluation(qs, lambda _q: next(it), FakeClock(durations))


GOOD = AskResult("answer [1]", True, ["Vacation Policy"], 1)


# --- loader ---


def test_loader_missing_file(tmp_path: Path) -> None:
    with pytest.raises(EvalError, match=NO_QUESTIONS_MESSAGE):
        load_questions(tmp_path / "nope.jsonl")


def test_loader_empty_file(tmp_path: Path) -> None:
    with pytest.raises(EvalError, match=NO_QUESTIONS_MESSAGE):
        load_questions(_write(tmp_path / "q.jsonl", ["", "  "]))


def test_loader_skips_blank_lines(tmp_path: Path) -> None:
    line = json.dumps({"question": "Q?", "expected_title": "T"})
    questions = load_questions(_write(tmp_path / "q.jsonl", ["", line, "   ", line]))
    assert questions == [EvalQuestion("Q?", "T")] * 2


@pytest.mark.parametrize("bad", ["{not json", '{"question": "Q?"}', '["x"]'])
def test_loader_malformed_names_line_number(tmp_path: Path, bad: str) -> None:
    good = json.dumps({"question": "Q?", "expected_title": "T"})
    with pytest.raises(EvalError, match="line 3"):
        load_questions(_write(tmp_path / "q.jsonl", [good, "", bad]))


def test_count_warning_only_when_not_20() -> None:
    assert count_warning(20) is None
    assert "19" in (count_warning(19) or "")


# --- found / cited ---


def test_found_when_expected_title_in_retrieved() -> None:
    assert judge(ANSWERABLE, GOOD) == (True, True)


def test_not_found_when_title_missing_and_uncited() -> None:
    assert judge(ANSWERABLE, AskResult("x", True, ["Other"], 0)) == (False, False)


def test_unanswerable_not_found_reply_is_found_and_cited_na() -> None:
    assert judge(UNANSWERABLE, AskResult(NOT_FOUND_MESSAGE, False, ["A"], 0)) == (True, None)


def test_unanswerable_with_real_answer_is_not_found() -> None:
    assert judge(UNANSWERABLE, AskResult("It is 42 [1]", True, ["A"], 1)) == (False, None)


def test_result_line_shows_na_and_yes() -> None:
    report = _run([AskResult(NOT_FOUND_MESSAGE, False, [], 0)], [1.0], questions=[UNANSWERABLE])
    line = format_result_line(1, report.results[0])
    assert "found=yes" in line
    assert "cited=n/a" in line


# --- percentile ---


def test_nearest_rank_p95_of_20_is_19th_sorted() -> None:
    values = [float(v) for v in range(20, 0, -1)]
    assert nearest_rank(values, 95) == 19.0


def test_nearest_rank_p50_of_20_is_10th() -> None:
    assert nearest_rank([float(v) for v in range(1, 21)], 50) == 10.0


def test_nearest_rank_single_value() -> None:
    assert nearest_rank([3.0], 95) == 3.0


# --- thresholds ---


def test_hit_rate_exactly_90_percent_meets_target() -> None:
    answers = [GOOD] * 9 + [AskResult("x", True, ["Other"], 1)]
    report = _run(answers, [1.0] * 10)
    assert report.hit_rate == pytest.approx(0.9)
    assert report.hit_rate_met


def test_hit_rate_below_90_fails() -> None:
    answers = [GOOD] * 8 + [AskResult("x", True, ["Other"], 1)] * 2
    report = _run(answers, [1.0] * 10)
    assert not report.hit_rate_met
    assert "hit rate" in format_verdict(report)


def test_citation_presence_exactly_90_meets_and_below_fails() -> None:
    uncited = AskResult("x", True, ["Vacation Policy"], 0)
    assert _run([GOOD] * 9 + [uncited], [1.0] * 10).citation_met
    below = _run([GOOD] * 8 + [uncited] * 2, [1.0] * 10)
    assert not below.citation_met
    assert "citation presence" in format_verdict(below)


def test_p95_exactly_8s_meets_and_above_fails() -> None:
    durations = [1.0] * 19 + [8.0]
    assert _run([GOOD] * 20, durations[:]).p95_met is True  # 19th value is 1.0
    boundary = [1.0] * 18 + [8.0, 9.0]
    report = _run([GOOD] * 20, boundary)
    assert report.p95 == 8.0
    assert report.p95_met
    slow = _run([GOOD] * 20, [1.0] * 18 + [8.1, 9.0])
    assert not slow.p95_met
    assert "p95" in format_verdict(slow)


def test_unanswerable_excluded_from_rates_but_in_timing() -> None:
    answers = [GOOD, AskResult(NOT_FOUND_MESSAGE, False, [], 0)]
    report = _run(answers, [1.0, 7.0], questions=[ANSWERABLE, UNANSWERABLE])
    assert report.hit_rate == 1.0
    assert report.p95 == 7.0


def test_totals_labels() -> None:
    lines = format_totals(_run([GOOD], [1.0]))
    assert len(lines) == 4
    assert all("meets target" in line for line in lines[:3])
    assert "for information" in lines[3]
    failing = format_totals(_run([AskResult("x", True, [], 0)], [9.0]))
    assert all("below target" in line for line in failing[:3])


def test_verdict_passed() -> None:
    assert format_verdict(_run([GOOD], [1.0])) == "Evaluation passed."


# --- CLI ---


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for var in (
        "STORAGE_ACCOUNT_URL",
        "DOCINTEL_ENDPOINT",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        "AZURE_OPENAI_CHAT_DEPLOYMENT",
        "SEARCH_ENDPOINT",
    ):
        monkeypatch.setenv(var, "x")
    path = tmp_path / "q.jsonl"
    monkeypatch.setenv("EVAL_PATH", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


def test_cli_eval_empty_library_exits_1(cli_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(cli_env, [json.dumps({"question": "Q?", "expected_title": "T"})])
    monkeypatch.setattr(
        cli,
        "build_ask_adapters",
        lambda s: (FakeEmbedder(), InMemoryChunkStore(), FakeChatModel(StructuredAnswer(False))),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1
    assert "The library has no documents yet. Run ingest first." in result.output


def test_cli_eval_malformed_line_exits_1(cli_env: Path) -> None:
    _write(cli_env, ["{oops"])
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1
    assert "line 1" in result.output


def test_cli_eval_failing_run_exits_1_and_passing_exits_0(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workplace_agent.ingestion.models import Chunk

    store = InMemoryChunkStore()
    store.chunks["a"] = Chunk(
        id="a",
        doc_id="d",
        title="T",
        source_path="t.pdf",
        page_start=1,
        page_end=1,
        section="",
        chunk_index=0,
        content="hello",
        content_hash="h",
    )
    _write(cli_env, [json.dumps({"question": "hello", "expected_title": "T"})])
    answer = StructuredAnswer(True, [AnswerSentence("Hi.", [1])])
    monkeypatch.setattr(
        cli, "build_ask_adapters", lambda s: (FakeEmbedder(), store, FakeChatModel(answer))
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 0, result.output
    assert "Evaluation passed." in result.output
    assert "warning" in result.output.lower()  # 1 question, not 20

    _write(cli_env, [json.dumps({"question": "hello", "expected_title": "Missing"})])
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1
    assert "below target" in result.output
