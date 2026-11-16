from pytest_mock import MockerFixture

from workplace_agent.ingestion.index import SearchChunkStore, build_index_definition
from workplace_agent.ingestion.models import Chunk, IndexedDocState


def _store(mocker: MockerFixture) -> tuple[SearchChunkStore, object, object]:
    index_client, search = mocker.Mock(), mocker.Mock()
    return SearchChunkStore(index_client, search, "workplace-docs"), index_client, search


def _chunk(i: int) -> Chunk:
    return Chunk(
        id=f"d-{i}", doc_id="d", title="T", source_path="T.pdf", page_start=1, page_end=2,
        section="S", chunk_index=i, content="c", content_hash="h", vector=[0.1, 0.2],
    )  # fmt: skip


def test_schema_fields() -> None:
    index = build_index_definition("workplace-docs")
    f = {x.name: x for x in index.fields}
    assert list(f) == [
        "id", "doc_id", "title", "source_path", "page_start", "page_end", "section",
        "chunk_index", "content", "content_vector", "content_hash", "ingested_at",
    ]  # fmt: skip
    assert f["id"].key
    for name in ("doc_id", "title", "source_path", "page_start", "page_end", "chunk_index",
                 "content_hash"):  # fmt: skip
        assert f[name].filterable, name
    assert f["chunk_index"].sortable
    for name in ("title", "section", "content"):
        assert f[name].searchable, name
    assert f["page_start"].type == "Edm.Int32"
    assert f["ingested_at"].type == "Edm.DateTimeOffset"
    vec = f["content_vector"]
    assert vec.type == "Collection(Edm.Single)"
    assert vec.vector_search_dimensions == 1536
    algo = index.vector_search.algorithms[0]
    assert algo.parameters.metric == "cosine"
    assert index.vector_search.profiles[0].algorithm_configuration_name == algo.name


def test_get_states_filters_chunk_zero_and_maps(mocker: MockerFixture) -> None:
    store, _, search = _store(mocker)
    search.search.return_value = [{"doc_id": "d", "source_path": "a.pdf", "content_hash": "h"}]
    assert store.get_states() == [IndexedDocState("d", "a.pdf", "h")]
    kwargs = search.search.call_args.kwargs
    assert kwargs["filter"] == "chunk_index eq 0"
    assert kwargs["select"] == ["doc_id", "source_path", "content_hash"]
    assert kwargs["top"] == 1000


def test_ids_for_doc_filter_and_mapping(mocker: MockerFixture) -> None:
    store, _, search = _store(mocker)
    search.search.return_value = [{"id": "d-0"}, {"id": "d-1"}]
    assert store.ids_for_doc("d'x") == ["d-0", "d-1"]
    assert search.search.call_args.kwargs["filter"] == "doc_id eq 'd''x'"


def test_upsert_merge_or_upload_in_batches(mocker: MockerFixture) -> None:
    store, _, search = _store(mocker)
    store.upsert([_chunk(i) for i in range(1001)])
    sizes = [len(c.kwargs["documents"]) for c in search.merge_or_upload_documents.call_args_list]
    assert sizes == [1000, 1]
    doc = search.merge_or_upload_documents.call_args_list[0].kwargs["documents"][0]
    assert doc["id"] == "d-0" and doc["content_vector"] == [0.1, 0.2] and doc["ingested_at"]


def test_delete_ids_and_count(mocker: MockerFixture) -> None:
    store, _, search = _store(mocker)
    store.delete_ids(["a", "b"])
    search.delete_documents.assert_called_once_with(documents=[{"id": "a"}, {"id": "b"}])
    search.get_document_count.return_value = 7
    assert store.document_count() == 7
