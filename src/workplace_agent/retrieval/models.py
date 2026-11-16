from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    title: str
    page_start: int
    page_end: int
    content: str
    score: float = 0.0
    section: str = ""


@dataclass(frozen=True, slots=True)
class AnswerSentence:
    text: str
    cites: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StructuredAnswer:
    found: bool
    sentences: list[AnswerSentence] = field(default_factory=list)
    missing_part: str | None = None
    usage: dict[str, int] = field(default_factory=dict)  # token counts only
