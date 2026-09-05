"""Local filesystem object storage.

V1 implementation of the :class:`~app.infrastructure.storage.object_storage.ObjectStore`
protocol. Keys are relative paths under the storage root: traversal is rejected so
an uploaded filename can never escape the controlled directory.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.common.exceptions import NotFoundError, ValidationError


class LocalFileStorage:
    """Filesystem-backed object store rooted at ``root_path``."""

    def __init__(self, root_path: str | Path) -> None:
        self._root = Path(root_path).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Resolve ``key`` inside the root, rejecting traversal attempts."""
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise ValidationError(f"Invalid object key {key!r}.")
        candidate = (self._root / key).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:  # path escaped the storage root
            raise ValidationError(f"Invalid object key {key!r}.") from exc
        return candidate

    async def put(self, *, bucket: str, key: str, data: bytes) -> None:
        target = self._resolve(f"{bucket}/{key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.get_running_loop().run_in_executor(
            None, target.write_bytes, data
        )

    async def get(self, *, bucket: str, key: str) -> bytes:
        target = self._resolve(f"{bucket}/{key}")
        if not target.is_file():
            raise NotFoundError(f"Object {bucket}/{key} not found.")
        return await asyncio.get_running_loop().run_in_executor(
            None, target.read_bytes
        )

    async def delete(self, *, bucket: str, key: str) -> None:
        target = self._resolve(f"{bucket}/{key}")
        if target.is_file():
            target.unlink()
            # Prune the (now empty) key directory and its bucket if unused,
            # so deletes leave no residue on local filesystems. Best-effort:
            # non-empty dirs are left alone, races are ignored.
            try:
                target.parent.rmdir()
                self._root.joinpath(bucket).rmdir()
            except OSError:
                pass

    async def exists(self, *, bucket: str, key: str) -> bool:
        return self._resolve(f"{bucket}/{key}").is_file()