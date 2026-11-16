from typing import Any

from workplace_agent.retrieval.models import RetrievedChunk

MAX_WORDS = 150

SYSTEM_PROMPT = f"""You answer questions about company documents using only the numbered passages \
provided in the user message.

Rules:
- Use only the numbered passages. Never use outside knowledge.
- The whole answer is at most {MAX_WORDS} words.
- Split the answer into sentences. Every sentence that states a fact must list at least one \
citation number in `cites`, using the passage numbers (for example [1, 3]).
- Do not put citation markers such as [1] inside `text`.
- Set `found` to true whenever ANY part of the question is answered by the passages. Set it to \
false only when nothing in the question is answered; then return no sentences.
- If the question has several parts and the passages answer only some of them, answer the \
answered parts with citations, and put the unanswered part in `missing_part` as a short noun \
phrase (for example "the parking allowance"). Never write sentences saying something is missing \
or not mentioned; `sentences` holds only facts from the passages. If every part is answered, \
set `missing_part` to null.

Example: the question asks about the meal and parking allowances and the passages only state \
the meal allowance. Return found=true, one cited sentence about the meal allowance, and \
missing_part="the parking allowance".
"""

ANSWER_SCHEMA_NAME = "workplace_answer"

ANSWER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "cites": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["text", "cites"],
                "additionalProperties": False,
            },
        },
        "missing_part": {"type": ["string", "null"]},
    },
    "required": ["found", "sentences", "missing_part"],
    "additionalProperties": False,
}

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"name": ANSWER_SCHEMA_NAME, "strict": True, "schema": ANSWER_JSON_SCHEMA},
}


def _pages(chunk: RetrievedChunk) -> str:
    if chunk.page_start == chunk.page_end:
        return f"p. {chunk.page_start}"
    return f"pp. {chunk.page_start}-{chunk.page_end}"


def build_user_message(question: str, passages: list[RetrievedChunk]) -> str:
    blocks = [
        f"[{i}] {p.title} ({_pages(p)})\n{p.content}" for i, p in enumerate(passages, start=1)
    ]
    return "Passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
