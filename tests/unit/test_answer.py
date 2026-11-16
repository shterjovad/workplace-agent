import pytest

from tests.fakes import FakeChatModel, FakeEmbedder, InMemoryChunkStore
from workplace_agent.ingestion.models import Chunk
from workplace_agent.retrieval.answer import NOT_FOUND_MESSAGE, AskResult, ask
from workplace_agent.retrieval.chat import parse_answer
from workplace_agent.retrieval.models import AnswerSentence, StructuredAnswer


def _chunk(i: int, title: str, start: int, end: int, content: str) -> Chunk:
    return Chunk(
        id=f"c{i}",
        doc_id=title,
        chunk_index=i,
        title=title,
        source_path=f"{title}.pdf",
        page_start=start,
        page_end=end,
        content=content,
        content_hash="h",
        section="",
    )


def _store() -> InMemoryChunkStore:
    store = InMemoryChunkStore()
    # Fake search ranks by word overlap with the query "alpha beta gamma delta".
    store.upsert(
        [
            _chunk(0, "Leave", 3, 3, "alpha beta gamma delta"),
            _chunk(1, "Travel", 5, 6, "alpha beta gamma"),
            _chunk(2, "Travel", 5, 5, "alpha beta"),
            _chunk(3, "Travel", 7, 7, "alpha"),
        ]
    )
    return store


def _run(answer: StructuredAnswer) -> AskResult:
    return ask(
        "alpha beta gamma delta",
        embedder=FakeEmbedder(),
        store=_store(),
        chat=FakeChatModel(answer),
        top_k=5,
    )


def S(text: str, *cites: int) -> AnswerSentence:  # noqa: N802
    return AnswerSentence(text, list(cites))


# Passage order from the fake store: 1 Leave p.3, 2 Travel pp.5-6, 3 Travel p.5, 4 Travel p.7


def test_basic_answer_with_sources() -> None:
    result = _run(StructuredAnswer(True, [S("Ten days carry over.", 1)]))
    assert result.text == "Ten days carry over. [1]\n\nSources:\n[1] Leave, p. 3"
    assert result.found
    assert result.validated_cite_count == 1
    assert result.retrieved_titles == ["Leave", "Travel", "Travel", "Travel"]


def test_invalid_cite_dropped_but_sentence_kept_when_valid_cite_remains() -> None:
    result = _run(StructuredAnswer(True, [S("Fact.", 1, 9, 0)]))
    assert result.text == "Fact. [1]\n\nSources:\n[1] Leave, p. 3"


def test_sentence_with_no_valid_cite_dropped() -> None:
    result = _run(StructuredAnswer(True, [S("Made up.", 9), S("Real.", 1)]))
    assert "Made up." not in result.text
    assert "Real. [1]" in result.text


def test_all_sentences_invalid_gives_not_found() -> None:
    result = _run(StructuredAnswer(True, [S("Made up.", 9)]))
    assert result.text == NOT_FOUND_MESSAGE
    assert not result.found


def test_not_found_exact_text_no_sources() -> None:
    result = _run(StructuredAnswer(False, [S("ignored", 1)]))
    assert result.text == "I couldn't find this in the company documents."
    assert "Sources" not in result.text


def test_word_cap_drops_trailing_sentences() -> None:
    first = " ".join(["w"] * 100) + "."
    second = " ".join(["x"] * 60) + "."
    result = _run(StructuredAnswer(True, [S(first, 1), S(second, 2)]))
    assert second not in result.text
    assert "[2]" not in result.text
    assert "Travel" not in result.text  # dropped sentence's source is not listed


def test_word_cap_truncates_single_long_sentence() -> None:
    long = " ".join(f"w{i}" for i in range(200))
    result = _run(StructuredAnswer(True, [S(long, 1)]))
    body = result.text.split(" [1]")[0]
    assert len(body.split()) == 150
    assert body.endswith("w149")


def test_word_cap_ignores_markers_and_sources() -> None:
    sentence = " ".join(["w"] * 150)
    result = _run(StructuredAnswer(True, [S(sentence, 1, 2)]))
    assert sentence in result.text


def test_same_document_and_page_listed_once() -> None:
    result = _run(StructuredAnswer(True, [S("One.", 1), S("Two.", 1)]))
    assert result.text.count("[1] Leave, p. 3") == 1
    assert "[2]" not in result.text


def test_renumbered_by_first_use() -> None:
    result = _run(StructuredAnswer(True, [S("A.", 4), S("B.", 1)]))
    assert result.text == "A. [1] B. [2]\n\nSources:\n[1] Travel, p. 7\n[2] Leave, p. 3"


def test_multiple_cites_on_one_sentence() -> None:
    result = _run(StructuredAnswer(True, [S("A.", 1, 4)]))
    assert "A. [1][2]" in result.text
    assert result.validated_cite_count == 2


def test_page_range_uses_en_dash() -> None:
    result = _run(StructuredAnswer(True, [S("A.", 2)]))
    assert "[1] Travel, pp. 5–6" in result.text
    assert "-" not in result.text.split("Sources:")[1]


def test_partial_answer_sentence_appended() -> None:
    result = _run(StructuredAnswer(True, [S("Meals are 50.", 1)], "the parking allowance"))
    body = result.text.split("\n\nSources:")[0]
    assert body.endswith(
        "I couldn't find information about the parking allowance in the company documents."
    )
    assert "Meals are 50. [1]" in body


def test_missing_part_without_sentences_is_plain_not_found() -> None:
    result = _run(StructuredAnswer(True, [], "parking"))
    assert result.text == NOT_FOUND_MESSAGE


def test_sources_match_used_numbers_exactly() -> None:
    result = _run(StructuredAnswer(True, [S("A.", 3), S("B.", 2), S("C.", 3)]))
    body, sources = result.text.split("\n\nSources:\n")
    used = {int(n) for n in __import__("re").findall(r"\[(\d+)\]", body)}
    listed = {int(line[1 : line.index("]")]) for line in sources.splitlines()}
    assert used == listed == {1, 2}


def test_empty_retrieval_is_not_found_without_chat_call() -> None:
    chat = FakeChatModel(StructuredAnswer(True, [S("x", 1)]))
    result = ask("q", embedder=FakeEmbedder(), store=InMemoryChunkStore(), chat=chat, top_k=5)
    assert result.text == NOT_FOUND_MESSAGE
    assert chat.calls == []


@pytest.mark.parametrize("raw", [None, "", "not json", '{"found": true}', "[]"])
def test_unparseable_response_is_not_found(raw: str | None) -> None:
    assert parse_answer(raw) == StructuredAnswer(found=False)


def test_parse_answer_valid() -> None:
    raw = '{"found": true, "sentences": [{"text": "A.", "cites": [1]}], "missing_part": null}'
    assert parse_answer(raw) == StructuredAnswer(True, [S("A.", 1)], None)


def test_system_prompt_states_partial_answer_rule() -> None:
    from workplace_agent.retrieval.prompt import SYSTEM_PROMPT

    assert "ANY part of the question" in SYSTEM_PROMPT
    assert "missing_part" in SYSTEM_PROMPT
    assert "the parking allowance" in SYSTEM_PROMPT
    assert "Never write sentences saying something is missing" in SYSTEM_PROMPT


def test_absence_sentence_dropped_and_its_cites_not_in_sources() -> None:
    result = _run(
        StructuredAnswer(
            True,
            [
                S("Meals are 50 per day.", 1),
                S("The passages do not state any parking allowance amounts.", 3, 4),
            ],
            "the parking allowance",
        )
    )
    body, sources = result.text.split("\n\nSources:\n")
    assert "do not state" not in body
    assert sources == "[1] Leave, p. 3"
    assert result.validated_cite_count == 1


def test_only_absence_sentence_with_missing_part_is_not_found() -> None:
    result = _run(StructuredAnswer(True, [S("It is not mentioned in the documents.", 1)], "x"))
    assert result.text == NOT_FOUND_MESSAGE


def test_legitimate_negative_policy_sentence_kept() -> None:
    result = _run(
        StructuredAnswer(True, [S("Employees do not need manager approval for remote work.", 1)])
    )
    assert "Employees do not need manager approval for remote work. [1]" in result.text
