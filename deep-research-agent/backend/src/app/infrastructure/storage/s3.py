"""S3-compatible object storage.

Implements the :class:`~app.infrastructure.storage.object_storage.ObjectStore`
protocol against any S3-compatible endpoint (Supabase Storage, Vercel Blob,
Cloudflare R2, AWS S3, MinIO…). Logical buckets (``"documents"``) are namespaced
as key prefixes inside the single configured provider bucket, so the caller-facing
contract is identical to the local-filesystem backend.

Design notes:
- A fresh client is created per call. Builder objects are cheap and this guarantees
  a fresh connection pool per request with no shared-state races on the event loop.
- Concurrency-safe and stateless: uploads made by the API are read by the worker
  (and vice-versa) because both resolve the same configured endpoint/bucket.
"""

from __future__ import annotations

import logging

from aiobotocore.session import AioSession
from botocore.config import Config
from botocore.exceptions import ClientError

from app.common.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

#: botocore error codes that unambiguously mean "the object does not exist".
_MISSING_CODES = {"NoSuchKey", "NotFound", "NoSuchBucket"}


def _is_missing(exc: ClientError) -> bool:
    """Return True when ``exc`` is a 'not found' style S3 error."""
    status = ""
    code = ""
    try:
        status = str(exc.response["ResponseMetadata"]["HTTPStatusCode"])
    except (KeyError, TypeError, AttributeError):
        pass
    try:
        code = exc.response["Error"]["Code"]
    except (KeyError, TypeError, AttributeError):  # pragma: no cover - defensive
        pass
    return status == "404" or code in _MISSING_CODES


class S3ObjectStore:
    """S3/S3-compatible backend for the application object-store protocol."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region_name: str = "us-east-1",
        force_path_style: bool = True,
        max_attempts: int = 3,
        connect_timeout: float = 10.0,
        read_timeout: float = 120.0,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region_name
        self._path_style = force_path_style
        self._max_attempts = max_attempts
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._session = AioSession()

    # ---- key handling (parity with the local backend's security rules) ----

    def _validate_key(self, key: str) -> None:
        """Reject keys that could escape the bucket namespace."""
        if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
            raise ValidationError(f"Invalid object key {key!r}.")

    def _object_key(self, bucket: str, key: str) -> str:
        """Prefix a logical bucket into the object key inside the S3 bucket."""
        self._validate_key(key)
        return f"{bucket}/{key}"

    # ---- S3 client ----

    def _make_client(self):
        """Build an S3 low-level client configured for the app's endpoint."""
        return self._session.create_client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            config=Config(
                s3={
                    "addressing_style": "path" if self._path_style else "virtual",
                },
                retries={"max_attempts": self._max_attempts, "mode": "standard"},
                connect_timeout=self._connect_timeout,
                read_timeout=self._read_timeout,
            ),
        )

    # ---- ObjectStore protocol ----

    async def put(self, *, bucket: str, key: str, data: bytes) -> None:
        object_key = self._object_key(bucket, key)
        async with self._make_client() as client:
            await client.put_object(Bucket=self._bucket, Key=object_key, Body=data)

    async def get(self, *, bucket: str, key: str) -> bytes:
        object_key = self._object_key(bucket, key)
        try:
            async with self._make_client() as client:
                response = await client.get_object(Bucket=self._bucket, Key=object_key)
                return await response["Body"].read()
        except ClientError as exc:
            if _is_missing(exc):
                raise NotFoundError(f"Object {bucket}/{key} not found.") from exc
            logger.warning("S3 get failed", extra={"bucket": bucket, "key": key})
            raise

    async def delete(self, *, bucket: str, key: str) -> None:
        object_key = self._object_key(bucket, key)
        async with self._make_client() as client:
            await client.delete_object(Bucket=self._bucket, Key=object_key)

    async def exists(self, *, bucket: str, key: str) -> bool:
        object_key = self._object_key(bucket, key)
        try:
            async with self._make_client() as client:
                await client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise