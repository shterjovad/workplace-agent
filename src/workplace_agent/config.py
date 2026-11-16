from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from workplace_agent.errors import AppError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    storage_account_url: str | None = None
    blob_container: str = "documents"
    docintel_endpoint: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "v1"
    azure_openai_embedding_deployment: str | None = None
    azure_openai_chat_deployment: str | None = None
    search_endpoint: str | None = None
    search_index_name: str = "workplace-docs"
    key_vault_uri: str | None = None
    search_key_secret_name: str | None = None
    eval_path: str = "eval/questions.jsonl"
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 64
    top_k: int = 5
    applicationinsights_connection_string: str | None = None

    def require_azure(self) -> None:
        """Raise AppError listing every required Azure variable that is not set."""
        required = (
            "storage_account_url",
            "docintel_endpoint",
            "azure_openai_endpoint",
            "azure_openai_embedding_deployment",
            "azure_openai_chat_deployment",
            "search_endpoint",
        )
        missing = [name.upper() for name in required if not getattr(self, name)]
        if missing:
            raise AppError(f"Missing required configuration: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
