from types import SimpleNamespace

from pytest_mock import MockerFixture

from workplace_agent.ingestion.embedder import AzureOpenAIEmbedder


def _fake_client(mocker: MockerFixture) -> tuple[object, list[list[str]]]:
    calls: list[list[str]] = []

    def create(model: str, input: list[str]) -> SimpleNamespace:  # noqa: A002
        calls.append(list(input))
        # return out of order to prove the embedder restores order by index
        data = [SimpleNamespace(index=i, embedding=[float(len(t))]) for i, t in enumerate(input)]
        return SimpleNamespace(data=list(reversed(data)))

    client = mocker.Mock()
    client.embeddings.create.side_effect = create
    return client, calls


def test_batches_of_16_and_order_preserved(mocker: MockerFixture) -> None:
    client, calls = _fake_client(mocker)
    texts = ["x" * n for n in range(1, 36)]
    vectors = AzureOpenAIEmbedder(client, "emb").embed(texts)  # type: ignore[arg-type]
    assert [len(c) for c in calls] == [16, 16, 3]
    assert vectors == [[float(len(t))] for t in texts]


def test_empty_input_makes_no_call(mocker: MockerFixture) -> None:
    client, calls = _fake_client(mocker)
    assert AzureOpenAIEmbedder(client, "emb").embed([]) == []  # type: ignore[arg-type]
    assert calls == []
