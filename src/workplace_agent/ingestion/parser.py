"""Document Intelligence ``prebuilt-layout`` adapter producing Markdown plus page metadata."""

import logging
import re
from bisect import bisect_right
from typing import Any

import openai
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AnalyzeResult,
    DocumentContentFormat,
)
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError

from workplace_agent.errors import FailureReason, ParseError
from workplace_agent.ingestion.models import PageSpan, ParsedDocument, TableInfo

MODEL_ID = "prebuilt-layout"
_WHITESPACE = re.compile(r"\s+")
_PASSWORD_HINT = re.compile(r"password|encrypt", re.IGNORECASE)
_BAD_INPUT_STATUSES = {400, 415}
_BAD_INPUT_CODES = {
    "invalidcontent",
    "invalidrequest",
    "unsupportedmediatype",
    "unsupportedcontent",
}
_TEMPORARY_STATUSES = {408, 429}
logger = logging.getLogger("workplace_agent.ingest")


def _error_codes(exc: HttpResponseError) -> set[str]:
    """Lower-cased top-level and (nested) inner error codes of an Azure error."""
    codes: set[str] = set()
    node: Any = getattr(exc, "error", None)
    while node is not None:
        code = getattr(node, "code", None) if not isinstance(node, dict) else node.get("code")
        if code:
            codes.add(str(code).lower())
        node = (
            getattr(node, "innererror", None)
            if not isinstance(node, dict)
            else node.get("innererror")
        )
    return codes


def classify_error(exc: BaseException) -> FailureReason:
    """Map any exception raised while ingesting one document to a user-facing reason.

    Document Intelligence answers a protected PDF with 400 InvalidRequest / inner
    UnsupportedContent ("File may be password protected.") and a damaged file with
    400 InvalidRequest / inner InvalidContent ("The file is corrupted ..."), so the
    password case is told apart by message text.
    """
    if isinstance(exc, ParseError):
        return exc.reason
    if isinstance(exc, (ServiceRequestError, ServiceResponseError, TimeoutError, ConnectionError)):
        return FailureReason.TEMPORARY
    if isinstance(exc, (openai.APIConnectionError, openai.RateLimitError)):
        return FailureReason.TEMPORARY  # APIConnectionError includes APITimeoutError
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code in _TEMPORARY_STATUSES or exc.status_code >= 500:
            return FailureReason.TEMPORARY
    elif isinstance(exc, HttpResponseError):
        status = exc.status_code
        if status is not None and (status in _TEMPORARY_STATUSES or status >= 500):
            return FailureReason.TEMPORARY
        if status in _BAD_INPUT_STATUSES or _error_codes(exc) & _BAD_INPUT_CODES:
            if _PASSWORD_HINT.search(str(exc)):
                return FailureReason.PASSWORD_PROTECTED
            return FailureReason.NOT_READABLE_PDF
    logger.error("Unclassified ingest error: %r", exc, exc_info=exc)
    return FailureReason.NOT_READABLE_PDF


def page_for_offset(page_spans: list[PageSpan], offset: int) -> int | None:
    """Return the page containing markdown character ``offset`` (spans sorted by start)."""
    index = bisect_right([s.start for s in page_spans], offset) - 1
    if index >= 0 and offset < page_spans[index].end:
        return page_spans[index].page
    return None


def build_parsed_document(result: AnalyzeResult) -> ParsedDocument:
    """Convert an SDK ``AnalyzeResult`` (offsets in unicode code points) to a ``ParsedDocument``."""
    markdown: str = result.content or ""

    page_spans = sorted(
        (
            PageSpan(page=page.page_number, start=span.offset, end=span.offset + span.length)
            for page in result.pages or []
            for span in page.spans or []
        ),
        key=lambda s: s.start,
    )

    tables = [
        TableInfo(
            start=min(span.offset for span in table.spans),
            end=max(span.offset + span.length for span in table.spans),
            pages=tuple(sorted({r.page_number for r in table.bounding_regions or []})),
        )
        for table in result.tables or []
        if table.spans
    ]

    return ParsedDocument(
        markdown=markdown,
        page_spans=page_spans,
        tables=tables,
        uncovered_lines=_uncovered_lines(result, markdown),
    )


def _uncovered_lines(result: AnalyzeResult, markdown: str) -> list[tuple[int, str]]:
    """OCR lines whose text does not appear in the markdown (e.g. text inside figures)."""
    haystack = _WHITESPACE.sub(" ", markdown)
    uncovered: list[tuple[int, str]] = []
    for page in result.pages or []:
        for line in page.lines or []:
            text = _WHITESPACE.sub(" ", line.content).strip()
            if text and text not in haystack:
                uncovered.append((page.page_number, text))
    return uncovered


class DocumentIntelligenceParser:
    def __init__(self, client: DocumentIntelligenceClient) -> None:
        self._client = client

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        try:
            result = self._analyze(data)
        except Exception as exc:
            raise ParseError(classify_error(exc), type(exc).__name__) from exc
        return build_parsed_document(result)

    def _analyze(self, data: bytes) -> AnalyzeResult:
        poller: Any = self._client.begin_analyze_document(
            MODEL_ID,
            AnalyzeDocumentRequest(bytes_source=data),
            output_content_format=DocumentContentFormat.MARKDOWN,
            string_index_type="unicodeCodePoint",
        )
        analyzed: AnalyzeResult = poller.result()
        return analyzed
