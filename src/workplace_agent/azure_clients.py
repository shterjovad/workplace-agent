"""Factories for Azure SDK clients; all authenticate with DefaultAzureCredential."""

from typing import Any

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.keyvault.secrets import SecretClient
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from openai import AzureOpenAI, OpenAI

from workplace_agent.config import Settings
from workplace_agent.errors import AppError

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
OPENAI_MAX_RETRIES = 2  # 3 attempts in total
# azure-core retry policy for DI / Search / Blob: 3 attempts in total, exponential backoff
# (0.8s, 1.6s, ...) on 408/429/5xx and connection errors.
AZURE_RETRY_OPTIONS: dict[str, Any] = {
    "retry_total": 2,
    "retry_backoff_factor": 0.8,
    "retry_mode": "exponential",
}


def build_docintel_client(settings: Settings) -> DocumentIntelligenceClient:
    if not settings.docintel_endpoint:
        raise AppError("Missing required configuration: DOCINTEL_ENDPOINT")
    return DocumentIntelligenceClient(
        settings.docintel_endpoint, DefaultAzureCredential(), **AZURE_RETRY_OPTIONS
    )


def build_openai_client(settings: Settings) -> OpenAI:
    """Shared OpenAI client for Azure: GA v1 API when the version is "v1", else AzureOpenAI."""
    if not settings.azure_openai_endpoint:
        raise AppError("Missing required configuration: AZURE_OPENAI_ENDPOINT")
    token_provider = get_bearer_token_provider(DefaultAzureCredential(), COGNITIVE_SERVICES_SCOPE)
    if settings.azure_openai_api_version == "v1":
        return OpenAI(
            base_url=f"{settings.azure_openai_endpoint.rstrip('/')}/openai/v1/",
            api_key=token_provider,
            max_retries=OPENAI_MAX_RETRIES,
        )
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        azure_ad_token_provider=token_provider,
        max_retries=OPENAI_MAX_RETRIES,
    )


def _search_credential(settings: Settings) -> AzureKeyCredential | TokenCredential:
    """Entra by default; the admin key from Key Vault when a secret name is configured."""
    credential = DefaultAzureCredential()
    if settings.search_key_secret_name and settings.key_vault_uri:
        secret = SecretClient(settings.key_vault_uri, credential).get_secret(
            settings.search_key_secret_name
        )
        if not secret.value:
            raise AppError("Search key secret in Key Vault is empty")
        return AzureKeyCredential(secret.value)
    return credential


def _require_search(settings: Settings) -> str:
    if not settings.search_endpoint:
        raise AppError("Missing required configuration: SEARCH_ENDPOINT")
    return settings.search_endpoint


def build_search_index_client(settings: Settings) -> SearchIndexClient:
    return SearchIndexClient(
        _require_search(settings), _search_credential(settings), **AZURE_RETRY_OPTIONS
    )


def build_search_client(settings: Settings) -> SearchClient:
    return SearchClient(
        _require_search(settings),
        settings.search_index_name,
        _search_credential(settings),
        **AZURE_RETRY_OPTIONS,
    )
