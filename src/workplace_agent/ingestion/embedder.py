from openai import OpenAI

BATCH_SIZE = 16


class AzureOpenAIEmbedder:
    def __init__(self, client: OpenAI, deployment: str, batch_size: int = BATCH_SIZE) -> None:
        self._client = client
        self._deployment = deployment
        self._batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            response = self._client.embeddings.create(model=self._deployment, input=batch)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(list(item.embedding) for item in ordered)
        return vectors
