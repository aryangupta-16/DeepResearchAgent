"""Object/blob storage abstraction and the configured-backend factory."""

from __future__ import annotations

from typing import Protocol

from app.common.exceptions import NotConfiguredError


class ObjectStore(Protocol):
    """Minimal object storage interface (S3-compatible, GCS, etc.)."""

    async def put(self, *, bucket: str, key: str, data: bytes) -> None: ...
    async def get(self, *, bucket: str, key: str) -> bytes: ...
    async def delete(self, *, bucket: str, key: str) -> None: ...
    async def exists(self, *, bucket: str, key: str) -> bool: ...


def build_object_store() -> ObjectStore:
    """Factory: build the configured object store from application settings.

    S3-compatible storage (``OBJECT_STORAGE_ENDPOINT`` + ``OBJECT_STORAGE_BUCKET``
    set): durable uploads that survive redeploys — required on PaaS hosts with
    ephemeral filesystems (Railway, Render, Fly, Vercel…). The credentials must
    also be configured; a missing key fails fast at startup instead of surfacing
    mid-flight as an opaque S3 error.

    Without those settings, V1 local-filesystem storage rooted at
    ``DOCUMENT_STORAGE_PATH`` is used so local development stays reproducible
    with zero extra infrastructure.
    """
    from app.config.settings import get_settings
    from app.infrastructure.storage.local import LocalFileStorage
    from app.infrastructure.storage.s3 import S3ObjectStore

    settings = get_settings()
    endpoint = settings.object_storage_endpoint
    bucket = settings.object_storage_bucket
    if endpoint and bucket:
        if not settings.object_storage_access_key or not settings.object_storage_secret_key:
            raise NotConfiguredError(
                "OBJECT_STORAGE_ENDPOINT/OBJECT_STORAGE_BUCKET are set but "
                "OBJECT_STORAGE_ACCESS_KEY/OBJECT_STORAGE_SECRET_KEY are missing."
            )
        return S3ObjectStore(
            endpoint_url=endpoint,
            bucket=bucket,
            access_key=settings.object_storage_access_key,
            secret_key=settings.object_storage_secret_key,
            region_name=settings.object_storage_region,
            force_path_style=settings.object_storage_force_path_style,
        )
    return LocalFileStorage(root_path=settings.document_storage_path)