import json
import logging
from dataclasses import replace
from typing import cast

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema

from workplace_agent.retrieval.models import AnswerSentence, RetrievedChunk, StructuredAnswer
from workplace_agent.retrieval.prompt import RESPONSE_FORMAT, SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

NOT_FOUND = StructuredAnswer(found=False)


def parse_answer(raw: str | None) -> StructuredAnswer:
    """Parse the model's JSON; anything unparseable counts as not found."""
    try:
        data = json.loads(raw or "")
        sentences = [
            AnswerSentence(text=str(s["text"]), cites=[int(c) for c in s["cites"]])
            for s in data["sentences"]
        ]
        missing = data.get("missing_part")
        return StructuredAnswer(
            found=bool(data["found"]),
            sentences=sentences,
            missing_part=str(missing) if missing else None,
        )
    except (ValueError, KeyError, TypeError):
        logger.warning("Unparseable chat response; treating as not found")
        return NOT_FOUND


def _usage(response: object) -> dict[str, int]:
    """Token counts from a chat response (reasoning tokens when reported)."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    counts = {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_tokens": getattr(
            getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None
        ),
    }
    return {k: v for k, v in counts.items() if isinstance(v, int)}


class AzureChatModel:
    def __init__(self, client: OpenAI, deployment: str) -> None:
        self._client = client
        self._deployment = deployment

    def answer(self, question: str, passages: list[RetrievedChunk]) -> StructuredAnswer:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(question, passages)},
        ]
        response = self._client.chat.completions.create(
            model=self._deployment,
            messages=messages,
            response_format=cast(ResponseFormatJSONSchema, RESPONSE_FORMAT),
            reasoning_effort="minimal",
            max_completion_tokens=800,
        )
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            logger.warning("Chat model refused; treating as not found")
            return NOT_FOUND
        return replace(parse_answer(message.content), usage=_usage(response))
