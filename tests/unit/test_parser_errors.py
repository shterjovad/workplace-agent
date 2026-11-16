import logging
from types import SimpleNamespace as NS
from typing import Any

import httpx2
import openai
import pytest
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError

from workplace_agent.errors import FailureReason, ParseError
from workplace_agent.ingestion.parser import DocumentIntelligenceParser, classify_error


def http_error(status: int, code: str, message: str, inner: tuple[str, str] | None = None) -> Any:
    """Mimic the HttpResponseError Document Intelligence raises (live-API shape)."""
    text = f"({code}) {message}" + (f"\nInner error: {inner[1]}" if inner else "")
    exc = HttpResponseError(message=text)
    exc.status_code = status
    inner_error = NS(code=inner[0], innererror=None) if inner else None
    exc.error = NS(code=code, innererror=inner_error)
    return exc


def openai_status_error(status: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://x.openai.azure.com/embeddings")
    response = httpx2.Response(status, request=request)
    return openai.APIStatusError("boom", response=response, body=None)


PASSWORD = http_error(
    400,
    "InvalidRequest",
    "Invalid request.",
    ("UnsupportedContent", "Content is not supported: File may be password protected."),
)
CORRUPT = http_error(
    400,
    "InvalidRequest",
    "Invalid request.",
    ("InvalidContent", "The file is corrupted or format is unsupported."),
)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (PASSWORD, FailureReason.PASSWORD_PROTECTED),
        (
            http_error(415, "UnsupportedMediaType", "This PDF is encrypted."),
            FailureReason.PASSWORD_PROTECTED,
        ),
        (CORRUPT, FailureReason.NOT_READABLE_PDF),
        (http_error(415, "UnsupportedMediaType", "nope"), FailureReason.NOT_READABLE_PDF),
        (http_error(200, "InvalidContent", "bad"), FailureReason.NOT_READABLE_PDF),
        (http_error(408, "Timeout", "slow"), FailureReason.TEMPORARY),
        (http_error(429, "TooManyRequests", "slow down"), FailureReason.TEMPORARY),
        (http_error(503, "ServiceUnavailable", "down"), FailureReason.TEMPORARY),
        (ServiceRequestError("no network"), FailureReason.TEMPORARY),
        (ServiceResponseError("connection reset"), FailureReason.TEMPORARY),
        (TimeoutError("poller timed out"), FailureReason.TEMPORARY),
        (
            openai.APIConnectionError(request=httpx2.Request("POST", "https://x")),
            FailureReason.TEMPORARY,
        ),
        (openai_status_error(429), FailureReason.TEMPORARY),
        (openai_status_error(502), FailureReason.TEMPORARY),
        (ParseError(FailureReason.NOT_READABLE_PDF, "empty"), FailureReason.NOT_READABLE_PDF),
    ],
)
def test_classify_error_mapping(exc: Exception, expected: FailureReason) -> None:
    assert classify_error(exc) is expected


def test_unknown_exception_is_not_readable_and_logged_with_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="workplace_agent.ingest"):
        try:
            raise KeyError("surprise")
        except KeyError as exc:
            assert classify_error(exc) is FailureReason.NOT_READABLE_PDF
    assert caplog.records[0].exc_info is not None


def test_openai_client_error_status_is_not_temporary() -> None:
    assert classify_error(openai_status_error(400)) is FailureReason.NOT_READABLE_PDF


class RaisingClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def begin_analyze_document(self, *args: Any, **kwargs: Any) -> Any:
        raise self.exc


def test_parser_wraps_sdk_errors_as_parse_error() -> None:
    parser = DocumentIntelligenceParser(RaisingClient(PASSWORD))  # type: ignore[arg-type]
    with pytest.raises(ParseError) as info:
        parser.parse("x.pdf", b"data")
    assert info.value.reason is FailureReason.PASSWORD_PROTECTED
