from pathlib import Path

import pytest

from workplace_agent.config import Settings, get_settings
from workplace_agent.errors import AppError

ENV_NAMES = [
    "STORAGE_ACCOUNT_URL",
    "DOCINTEL_ENDPOINT",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "SEARCH_ENDPOINT",
    "BLOB_CONTAINER",
    "TOP_K",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # no stray .env


def test_defaults() -> None:
    s = Settings()
    assert s.blob_container == "documents"
    assert s.search_index_name == "workplace-docs"
    assert s.eval_path == "eval/questions.jsonl"
    assert (s.chunk_max_tokens, s.chunk_overlap_tokens, s.top_k) == (512, 64, 5)
    assert s.key_vault_uri is None
    assert s.applicationinsights_connection_string is None


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOP_K", "7")
    monkeypatch.setenv("BLOB_CONTAINER", "other")
    s = Settings()
    assert s.top_k == 7
    assert s.blob_container == "other"


def test_loads_without_azure_config() -> None:
    assert get_settings.__wrapped__().search_endpoint is None


def test_require_azure_lists_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_ENDPOINT", "https://s")
    with pytest.raises(AppError) as exc:
        Settings().require_azure()
    msg = str(exc.value)
    assert "STORAGE_ACCOUNT_URL" in msg
    assert "AZURE_OPENAI_CHAT_DEPLOYMENT" in msg
    assert "SEARCH_ENDPOINT" not in msg


def test_require_azure_passes_when_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES[:6]:
        monkeypatch.setenv(name, "x")
    Settings().require_azure()
