"""Repositories for documents + document chunks.

All document persistence goes through here — routes, services, and the worker
never touch SQLAlchemy sessions directly. Bulk chunk insertion backs idempotent
re-processing: chunks for a document are replaced atomically.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.enums import DocumentStatus
from app.infrastructure.database.models.document import Document, DocumentChunk


class DocumentRepository:
    """CRUD + status transitions for :class:`Document` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, document: Document) -> Document:
        self._session.add(document)
        await self._session.flush()
        return document

    async def get_by_id(self, document_id: UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def list_all(self, *, limit: int = 100) -> list[Document]:
        result = await self._session.scalars(
            select(Document)
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def list_ready(self) -> list[Document]:
        result = await self._session.scalars(
            select(Document)
            .where(Document.status == DocumentStatus.READY.value)
            .order_by(Document.created_at.desc())
        )
        return list(result)

    async def count(self) -> int:
        result = await self._session.scalar(select(func.count()).select_from(Document))
        return int(result or 0)

    async def set_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        *,
        error: str | None = None,
    ) -> Document | None:
        """Transition a document's status; caller owns transition validation."""
        document = await self.get_by_id(document_id)
        if document is None:
            return None
        document.status = status.value
        document.error = error
        await self._session.flush()
        return document

    async def delete(self, document_id: UUID) -> bool:
        """Delete a document row; chunks (and vectors) cascade via FK.

        Historical ``research_sources`` rows keep existing — their FK is
        ``SET NULL``. Returns ``False`` when the document does not exist.
        """
        document = await self.get_by_id(document_id)
        if document is None:
            return False
        await self._session.delete(document)
        await self._session.flush()
        return True


class DocumentChunkRepository:
    """Bulk chunk persistence + lookup."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_document(
        self, document_id: UUID, chunks: list[DocumentChunk]
    ) -> list[DocumentChunk]:
        """Atomically replace all chunks of a document with ``chunks``.

        This is the idempotency backbone: re-delivered processing tasks rebuild a
        deterministic chunk set instead of appending duplicates.
        """
        await self._session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        for chunk in chunks:
            self._session.add(chunk)
        await self._session.flush()
        return chunks

    async def count_for_document(self, document_id: UUID) -> int:
        result = await self._session.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.document_id == document_id
            )
        )
        return int(result or 0)