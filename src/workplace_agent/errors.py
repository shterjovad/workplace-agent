from enum import StrEnum


class AppError(Exception):
    """Base for all application errors."""


class FailureReason(StrEnum):
    PASSWORD_PROTECTED = "password-protected"
    NOT_READABLE_PDF = "not a readable PDF"
    TEMPORARY = "temporary problem — try again later"


class ParseError(AppError):
    """A document could not be parsed; carries the user-facing reason."""

    def __init__(self, reason: FailureReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail
