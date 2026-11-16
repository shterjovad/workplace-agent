from pathlib import Path

import pytest
from typer.testing import CliRunner

from workplace_agent.cli import app
from workplace_agent.config import get_settings

runner = CliRunner()

AZURE_VARS = (
    "STORAGE_ACCOUNT_URL",
    "DOCINTEL_ENDPOINT",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "SEARCH_ENDPOINT",
    "EVAL_PATH",
)


@pytest.fixture(autouse=True)
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run in an empty dir (no .env) with no Azure variables set."""
    monkeypatch.chdir(tmp_path)
    for var in AZURE_VARS:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("args", [["ask", ""], ["ask", "   "], ["ask"]])
def test_ask_without_question_exits_2(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "Please type a question." in result.output


def test_eval_missing_file_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_PATH", str(tmp_path / "missing.jsonl"))
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1
    assert "No evaluation questions found." in result.output


def test_eval_empty_file_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "questions.jsonl"
    path.write_text("\n  \n", encoding="utf-8")
    monkeypatch.setenv("EVAL_PATH", str(path))
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1
    assert "No evaluation questions found." in result.output


def test_ingest_without_azure_config_exits_3() -> None:
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 3
    assert "STORAGE_ACCOUNT_URL" in result.output


def test_ingest_empty_folder_prints_message_and_exits_0(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.fakes import FakeBlobSource, FakeEmbedder, FakeParser, InMemoryChunkStore
    from workplace_agent import cli

    for var in AZURE_VARS[:-1]:
        monkeypatch.setenv(var, "x")
    get_settings.cache_clear()
    monkeypatch.setattr(
        cli,
        "build_ingest_adapters",
        lambda s: (FakeBlobSource(), FakeParser(), FakeEmbedder(), InMemoryChunkStore()),
    )
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 0
    assert "No documents found in the document folder." in result.output
    assert "Ingest finished successfully." in result.output


def test_ask_empty_library_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.fakes import FakeChatModel, FakeEmbedder, InMemoryChunkStore
    from workplace_agent import cli
    from workplace_agent.retrieval.models import StructuredAnswer

    for var in AZURE_VARS[:-1]:
        monkeypatch.setenv(var, "x")
    get_settings.cache_clear()
    monkeypatch.setattr(
        cli,
        "build_ask_adapters",
        lambda s: (FakeEmbedder(), InMemoryChunkStore(), FakeChatModel(StructuredAnswer(False))),
    )
    result = runner.invoke(app, ["ask", "anything"])
    assert result.exit_code == 1
    assert "The library has no documents yet. Run ingest first." in result.output
