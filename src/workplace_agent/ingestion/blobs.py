from azure.storage.blob import ContainerClient


class AzureBlobSource:
    def __init__(self, container: ContainerClient) -> None:
        self._container = container

    def list_names(self) -> list[str]:
        return sorted(self._container.list_blob_names())

    def download(self, name: str) -> bytes:
        return bytes(self._container.download_blob(name).readall())
