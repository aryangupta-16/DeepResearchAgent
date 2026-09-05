"""Unit tests for the S3-compatible object store and the storage factory."""

import pytest
from botocore.exceptions import ClientError

from app.common.exceptions import NotConfiguredError, NotFoundError, ValidationError
from app.config.settings import get_settings
from app.infrastructure.storage.local import LocalFileStorage
from app.infrastructure.storage.object_storage import build_object_store
from app.infrastructure.storage.s3 import S3ObjectStore


class _AsyncBytes:
    """Minimal async file-object stand-in for a get_object response body."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _ClientContext:
    """Async context manager that yields a fake S3 client."""

    def __init__(self, client) -> None:
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeS3Client:
    """In-memory S3 client stand-in: bucket -> key -> bytes."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, bytes]] = {}
        self.calls: list[tuple[str, str, str]] = []

    def _raise_missing(self, operation: str) -> None:
        raise ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
            operation,
        )

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.calls.append(("put", Bucket, Key))
        self.objects.setdefault(Bucket, {})[Key] = Body

    async def get_object(self, *, Bucket: str, Key: str):
        self.calls.append(("get", Bucket, Key))
        try:
            body = self.objects[Bucket][Key]
        except KeyError:
            self._raise_missing("GetObject")
        return {"Body": _AsyncBytes(body)}

    async def head_object(self, *, Bucket: str, Key: str) -> None:
        self.calls.append(("head", Bucket, Key))
        if Key not in self.objects.get(Bucket, {}):
            self._raise_missing("HeadObject")

    async def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.calls.append(("delete", Bucket, Key))
        self.objects.get(Bucket, {}).pop(Key, None)


class FakeS3Store(S3ObjectStore):
    """S3 store bound to a fake in-memory client instead of a real endpoint."""

    def __init__(self, client: FakeS3Client, *, bucket: str = "app-documents") -> None:
        super().__init__(
            endpoint_url="https://s3.example.invalid",
            bucket=bucket,
            access_key="access-key",
            secret_key="secret-key",
            region_name="us-east-1",
            force_path_style=True,
        )
        self._client = client

    def _make_client(self):
        return _ClientContext(self._client)


# ---- protocol behaviour ---------------------------------------------------


async def test_roundtrip_put_get_exists_delete():
    client = FakeS3Client()
    store = FakeS3Store(client)

    await store.put(bucket="documents", key="abc/note.txt", data=b"hello world")
    assert await store.get(bucket="documents", key="abc/note.txt") == b"hello world"
    assert await store.exists(bucket="documents", key="abc/note.txt") is True
    assert await store.exists(bucket="documents", key="abc/nope.txt") is False

    await store.delete(bucket="documents", key="abc/note.txt")
    assert await store.exists(bucket="documents", key="abc/note.txt") is False


async def test_logical_bucket_is_namespaced_into_s3_key():
    client = FakeS3Client()
    store = FakeS3Store(client, bucket="production-documents")

    await store.put(bucket="documents", key="abc/file.pdf", data=b"%PDF")
    assert client.objects["production-documents"]["documents/abc/file.pdf"] == b"%PDF"


async def test_get_missing_raises_not_found():
    store = FakeS3Store(FakeS3Client())
    with pytest.raises(NotFoundError):
        await store.get(bucket="documents", key="abc/missing.txt")


async def test_invalid_keys_are_rejected():
    store = FakeS3Store(FakeS3Client())
    for bad in ("", "/absolute", "../escape", "a/../../b", "back\\slash"):
        with pytest.raises(ValidationError):
            await store.put(bucket="documents", key=bad, data=b"x")
        with pytest.raises(ValidationError):
            await store.get(bucket="documents", key=bad)
        with pytest.raises(ValidationError):
            await store.exists(bucket="documents", key=bad)
        with pytest.raises(ValidationError):
            await store.delete(bucket="documents", key=bad)


async def test_non_missing_client_errors_propagate_unchanged():
    class ForbiddingClient(FakeS3Client):
        async def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "no"}}, "PutObject"
            )

    store = FakeS3Store(ForbiddingClient())
    with pytest.raises(ClientError):
        await store.put(bucket="documents", key="abc/x.txt", data=b"x")


# ---- factory --------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Ensure env-driven settings from one test never leak into the next."""
    yield
    get_settings.cache_clear()


def test_factory_uses_local_storage_without_object_storage_config(monkeypatch):
    for var in (
        "OBJECT_STORAGE_ENDPOINT",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()

    assert isinstance(build_object_store(), LocalFileStorage)


def test_factory_requires_credentials_when_s3_is_configured(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "https://s3.example.invalid")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "documents")
    monkeypatch.delenv("OBJECT_STORAGE_ACCESS_KEY", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_SECRET_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(NotConfiguredError):
        build_object_store()


def test_factory_builds_s3_store_when_configured(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "https://s3.example.invalid")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "documents")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "access-key")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "secret-key")
    monkeypatch.setenv("OBJECT_STORAGE_REGION", "auto")
    get_settings.cache_clear()

    store = build_object_store()
    assert isinstance(store, S3ObjectStore)
    assert store._bucket == "documents"
    assert store._region == "auto"