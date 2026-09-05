"""Document domain service.

Owns upload validation, persistence of document metadata, and status
transitions. The binary never lives here: it goes straight to the configured
object store and only its ``storage_reference`` is persisted.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import (
    DocumentInvalidStateError,
    NotFoundError,
    ValidationError,
)
from app.documents.enums import (
    DOCUMENT_STATUS_TRANSITIONS,
    DocumentStatus,
    validate_document_status_transition,
)
from app.documents.repository import DocumentChunkRepository, DocumentRepository
from app.infrastructure.database.models.document import Document
from app.infrastructure.storage.object_storage import ObjectStore

#: Upload bucket name inside the object store.
DOCUMENT_BUCKET = "documents"

logger = logging.getLogger(__name__)
_MAX_FILENAME_LENGTH = 255

_FILENAME_DISALLOWED = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(filename: str) -> str:
    """Normalize an uploaded filename to a safe basename."""
    name = (filename or "upload").replace("\\", "/").split("/")[-1].strip()
    name = _FILENAME_DISALLOWED.sub("_", name).strip(". ")
    name = name[:_MAX_FILENAME_LENGTH] or "upload"
    return name


def storage_key_for(document_id: UUID, filename: str) -> str:
    """Controlled storage key: ``<document_id>/<filename>`` (no user paths)."""
    return f"{document_id}/{sanitize_filename(filename)}"


class DocumentService:
    """Uploads, queries, and transitions documents."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        object_store: ObjectStore | None = None,
        max_size_mb: int = 25,
    ) -> None:
        self._session = session
        self._documents = DocumentRepository(session)
        self._chunks = DocumentChunkRepository(session)
        self._store = object_store
        self._max_bytes = max(1, max_size_mb) * 1024 * 1024

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    # ---- Upload ----

    async def create_document(
        self,
        *,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> Document:
        """Validate + persist an upload; returns the ``pending`` document row."""
        if not data:
            raise ValidationError("Uploaded file is empty.")
        if len(data) > self._max_bytes:
            limit_mb = self._max_bytes // (1024 * 1024)
            raise ValidationError(
                f"Document exceeds the maximum upload size of {limit_mb} MB."
            )

        safe_name = sanitize_filename(filename)
        document = Document(
            filename=safe_name,
            content_type=(content_type or "").split(";")[0].strip(),
            size_bytes=len(data),
            storage_reference="",  # filled once the id exists
            status=DocumentStatus.PENDING.value,
        )
        await self._documents.create(document)

        key = storage_key_for(document.id, safe_name)
        document.storage_reference = key
        await self._session.flush()

        if self._store is not None:
            await self._store.put(bucket=DOCUMENT_BUCKET, key=key, data=data)
        await self._commit()
        # Load server defaults (created_at/updated_at) while still in async
        # context — response schema extraction cannot do implicit lazy IO.
        await self._session.refresh(document)
        return document

    async def read_stored_file(self, document: Document) -> bytes:
        """Load the stored binary for a document (download / parsing)."""
        if self._store is None:
            raise ValidationError("Object storage is not configured.")
        return await self._store.get(bucket=DOCUMENT_BUCKET, key=document.storage_reference)

    # ---- Queries ----

    async def get_document(self, document_id: UUID) -> Document:
        document = await self._documents.get_by_id(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found.")
        return document

    async def list_documents(self, *, limit: int = 100) -> list[Document]:
        return await self._documents.list_all(limit=limit)

    async def list_ready_documents(self) -> list[Document]:
        return await self._documents.list_ready()

    async def delete_document(self, document_id: UUID) -> None:
        """Hard-delete a document: DB row, chunks/vectors, and stored file.

        - ``409`` while the document is mid-processing (worker in flight).
        - Historical research sources are preserved (FK is ``SET NULL``).
        - File deletion is best-effort: an orphaned blob must never block the
          metadata delete.
        """
        document = await self.get_document(document_id)
        if document.status == DocumentStatus.PROCESSING.value:
            raise DocumentInvalidStateError(
                f"Document {document.filename!r} is currently processing; "
                "wait for it to finish before deleting."
            )

        storage_reference = document.storage_reference
        await self._documents.delete(document_id)
        await self._commit()

        if self._store is not None and storage_reference:
            try:
                await self._store.delete(bucket=DOCUMENT_BUCKET, key=storage_reference)
            except Exception:  # pragma: no cover - defensive (infra flake)
                logger.warning(
                    "Stored file delete failed for %s (blob may be orphaned)",
                    storage_reference,
                    exc_info=True,
                )

    async def require_ready_documents(self, document_ids: list[UUID]) -> list[Document]:
        """Resolve + validate a research job's document selection (§37)."""
        documents: list[Document] = []
        for document_id in document_ids:
            document = await self.get_document(document_id)
            if document.status != DocumentStatus.READY.value:
                raise ValidationError(
                    f"Document {document.filename!r} is {document.status!r}; "
                    "only 'ready' documents can be used for research."
                )
            documents.append(document)
        return documents

    # ---- Status transitions ----

    async def set_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        *,
        error: str | None = None,
    ) -> Document:
        """Transition status with validation; raises on illegal transitions."""
        document = await self.get_document(document_id)
        current = DocumentStatus(document.status)
        validate_document_status_transition(current, status)

        document.status = status.value
        document.error = error
        if status == DocumentStatus.READY:
            document.processed_at = datetime.now(UTC)
        await self._session.flush()
        await self._commit()
        await self._session.refresh(document)
        return document

    @staticmethod
    def can_transition(current: str, new: str) -> bool:
        try:
            return new in DOCUMENT_STATUS_TRANSITIONS[DocumentStatus(current)]
        except ValueError:
            return False

    async def enqueue_processing(self, document_id: UUID) -> None:
        """Enqueue a document-processing task for the worker.

        Durability: the row is already persisted ``pending`` in this transaction.
        If Redis is briefly down, the worker's reconciliation sweep re-enqueues
        any pending document after ``DOCUMENT_PENDING_RECLAIM_SECONDS`` — so the
        batch is never lost, and idempotent processing makes redelivery harmless.
        """
        from app.infrastructure.queue.client import get_document_queue_client
        from app.infrastructure.queue.tasks import DocumentProcessingTask

        queue = get_document_queue_client()
        await queue.enqueue(DocumentProcessingTask(document_id=document_id, attempt=1))
        await self._commit()