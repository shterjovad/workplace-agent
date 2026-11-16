import re
from dataclasses import dataclass, field

from workplace_agent.ports import ChatModel, ChunkStore, Embedder
from workplace_agent.retrieval.models import AnswerSentence, RetrievedChunk
from workplace_agent.retrieval.prompt import MAX_WORDS
from workplace_agent.retrieval.search import TOP_K, retrieve
from workplace_agent.telemetry import get_tracer

NOT_FOUND_MESSAGE = "I couldn't find this in the company documents."
EN_DASH = "–"
tracer = get_tracer()


@dataclass(frozen=True, slots=True)
class AskResult:
    text: str
    found: bool
    retrieved_titles: list[str] = field(default_factory=list)
    validated_cite_count: int = 0


_SOURCE_REF = r"(?:passages?|documents?|sources?|excerpts?|context|text)"
_ABSENCE_VERB = (
    r"(?:do(?:es)?\s+not|don't|doesn't)\s+"
    r"(?:mention|state|specify|include|contain|provide|say|list)"
)
# Sentences that only report an absence of information are not facts from the documents.
# A bare negative ("Employees do not need approval") must survive, so the first pattern
# requires a source reference next to the absence verb.
_ABSENCE_PATTERNS = [
    re.compile(rf"\b{_SOURCE_REF}\b[^.]{{0,40}}\b{_ABSENCE_VERB}\b", re.IGNORECASE),
    re.compile(rf"\b{_SOURCE_REF}\b[^.]{{0,40}}\b(?:is|are)\s+silent\b", re.IGNORECASE),
    re.compile(
        r"\b(?:is|are)\s+not\s+(?:mentioned|stated|specified|provided|included)\b", re.IGNORECASE
    ),
    re.compile(r"\bno\s+(?:information|mention|details?)\s+(?:about|on|of|regarding)\b", re.I),
    re.compile(r"\b(?:couldn't|could\s+not|cannot|can't)\s+find\b", re.IGNORECASE),
]


def _is_absence_statement(text: str) -> bool:
    return any(pattern.search(text) for pattern in _ABSENCE_PATTERNS)


def _validate(sentences: list[AnswerSentence], passage_count: int) -> list[tuple[str, list[int]]]:
    """Drop cites outside 1..passage_count, absence statements, and cite-less sentences."""
    kept: list[tuple[str, list[int]]] = []
    for sentence in sentences:
        cites = list(dict.fromkeys(c for c in sentence.cites if 1 <= c <= passage_count))
        if cites and sentence.text.strip() and not _is_absence_statement(sentence.text):
            kept.append((sentence.text.strip(), cites))
    return kept


def _apply_word_cap(sentences: list[tuple[str, list[int]]]) -> list[tuple[str, list[int]]]:
    capped: list[tuple[str, list[int]]] = []
    total = 0
    for text, cites in sentences:
        words = text.split()
        if total + len(words) > MAX_WORDS:
            if not capped:
                capped.append((" ".join(words[:MAX_WORDS]), cites))
            break
        capped.append((text, cites))
        total += len(words)
    return capped


def render(
    answer_found: bool,
    sentences: list[AnswerSentence],
    missing_part: str | None,
    passages: list[RetrievedChunk],
) -> tuple[str, int]:
    """Return (rendered text, validated cite count)."""
    valid = _validate(sentences, len(passages))
    if not answer_found or not valid:
        return NOT_FOUND_MESSAGE, 0
    valid = _apply_word_cap(valid)

    numbers: dict[tuple[str, int, int], int] = {}
    lines: list[str] = []
    cite_count = 0
    for text, cites in valid:
        markers: list[int] = []
        for cite in cites:
            passage = passages[cite - 1]
            number = numbers.setdefault(
                (passage.title, passage.page_start, passage.page_end), len(numbers) + 1
            )
            if number not in markers:
                markers.append(number)
        cite_count += len(markers)
        lines.append(f"{text} {''.join(f'[{n}]' for n in markers)}")

    out = [" ".join(lines), "", "Sources:"]
    for (title, start, end), number in numbers.items():
        pages = f"p. {start}" if start == end else f"pp. {start}{EN_DASH}{end}"
        out.append(f"[{number}] {title}, {pages}")
    if missing_part and missing_part.strip():
        out.insert(
            1, f"I couldn't find information about {missing_part.strip()} in the company documents."
        )
    return "\n".join(out), cite_count


def ask(
    question: str,
    *,
    embedder: Embedder,
    store: ChunkStore,
    chat: ChatModel,
    top_k: int = TOP_K,
) -> AskResult:
    with tracer.start_as_current_span("ask") as span:
        span.set_attribute("question.length", len(question))
        passages = retrieve(question, embedder, store, top_k)
        span.set_attribute("retrieved.count", len(passages))
        titles = [p.title for p in passages]
        if not passages:
            span.set_attribute("found", False)
            return AskResult(NOT_FOUND_MESSAGE, False, titles, 0)
        with tracer.start_as_current_span("chat") as chat_span:
            answer = chat.answer(question, passages)
            for name, value in answer.usage.items():
                chat_span.set_attribute(f"usage.{name}", value)
                span.set_attribute(f"usage.{name}", value)
        with tracer.start_as_current_span("render"):
            text, cite_count = render(answer.found, answer.sentences, answer.missing_part, passages)
        found = text != NOT_FOUND_MESSAGE
        span.set_attribute("found", found)
        span.set_attribute("cites.validated", cite_count)
        return AskResult(text, found, titles, cite_count)
