from pytest_mock import MockerFixture

from tests.fakes import FakeEmbedder, InMemoryChunkStore
from workplace_agent.ingestion.index import SearchChunkStore
from workplace_agent.retrieval.models import RetrievedChunk
from workplace_agent.retrieval.prompt import ANSWER_JSON_SCHEMA, build_user_message
from workplace_agent.retrieval.search import is_library_empty, retrieve


def _store(mocker: MockerFixture, rows: list[dict] | None = None):  # type: ignore[no-untyped-def]
    search = mocker.Mock()
    search.search.return_value = rows or []
    return SearchChunkStore(mocker.Mock(), search, "workplace-docs"), search


def test_hybrid_search_query_shape(mocker: MockerFixture) -> None:
    store, search = _store(mocker)
    store.hybrid_search("vacation?", [0.1, 0.2], 5)
    kwargs = search.search.call_args.kwargs
    assert kwargs["top"] == 5
    assert kwargs["search_text"] == "vacation?"
    (vq,) = kwargs["vector_queries"]
    assert vq.k_nearest_neighbors == 50
    assert vq.fields == "content_vector"
    assert list(vq.vector) == [0.1, 0.2]
    assert kwargs["select"] == ["title", "page_start", "page_end", "section", "content"]


def test_hybrid_search_maps_results(mocker: MockerFixture) -> None:
    row = {"title": "HR", "page_start": 2, "page_end": 3, "section": "Leave", "content": "c",
           "@search.score": 0.5}  # fmt: skip
    store, _ = _store(mocker, [row])
    assert store.hybrid_search("q", [0.1], 5) == [
        RetrievedChunk("HR", 2, 3, "c", score=0.5, section="Leave")
    ]


def test_retrieve_embeds_question_and_searches(mocker: MockerFixture) -> None:
    store = mocker.Mock()
    store.hybrid_search.return_value = []
    embedder = FakeEmbedder()
    retrieve("q?", embedder, store, 5)
    assert embedder.calls == [["q?"]]
    store.hybrid_search.assert_called_once_with("q?", embedder.embed(["q?"])[0], 5)


def test_is_library_empty_true_and_false() -> None:
    store = InMemoryChunkStore()
    assert is_library_empty(store) is True
    store.chunks["x"] = object()  # type: ignore[assignment]
    assert is_library_empty(store) is False


def test_build_user_message_numbers_passages() -> None:
    msg = build_user_message(
        "Q?", [RetrievedChunk("A", 1, 1, "alpha"), RetrievedChunk("B", 2, 4, "beta")]
    )
    assert "[1] A (p. 1)\nalpha" in msg
    assert "[2] B (pp. 2-4)\nbeta" in msg
    assert "[0]" not in msg and "[3]" not in msg
    assert msg.endswith("Question: Q?")


def _check_strict(schema: dict) -> None:  # type: ignore[type-arg]
    if schema.get("type") == "object":
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        for sub in schema["properties"].values():
            _check_strict(sub)
    if schema.get("type") == "array":
        _check_strict(schema["items"])


def test_answer_schema_is_strict_valid() -> None:
    _check_strict(ANSWER_JSON_SCHEMA)
    assert set(ANSWER_JSON_SCHEMA["properties"]) == {"found", "sentences", "missing_part"}
    assert ANSWER_JSON_SCHEMA["properties"]["missing_part"]["type"] == ["string", "null"]
    item = ANSWER_JSON_SCHEMA["properties"]["sentences"]["items"]
    assert set(item["properties"]) == {"text", "cites"}
