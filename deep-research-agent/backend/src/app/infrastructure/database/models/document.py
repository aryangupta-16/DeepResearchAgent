"""Document + document chunk ORM models.

``Document`` holds metadata for one uploaded file; the binary itself lives in
object/file storage (``storage_reference``), never in PostgreSQL.

``DocumentChunk`` is a deterministic slice of the parsed document with its page
number (for citations) and its embedding. Embeddings live on the chunk row so
pgvector can index them without duplicating chunk content into a second store.

Idempotency: ``uq_document_chunks_document_index`` guarantees re-processing a
document can never create duplicate chunks at the database level.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.documents.enums import DocumentStatus
from app.infrastructure.database.postgres import Base

if TYPE_CHECKING:  # pragma: no cover
    pass

#: Dimensionality of the configured embedding model (OpenAI text-embedding-3-small).
EMBEDDING_DIMENSIONS = 1536


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(255), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # Key inside the object/file store; never the binary itself.
    storage_reference: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(
        String(20),
        default=DocumentStatus.PENDING.value,
        server_default=DocumentStatus.PENDING.value,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentChunk.chunk_index",
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} filename={self.filename!r} status={self.status!r}>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        # Idempotency: re-processing a document replaces/never duplicates indices.
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_index"
        ),
        Index("ix_document_chunks_document_id", "document_id"),
        # HNSW index backing cosine similarity search (vector_cosine_ops).
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # pgvector column; nullable until embeddings exist for this chunk.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk id={self.id} document_id={self.document_id} "
            f"index={self.chunk_index} page={self.page_number}>"
        )