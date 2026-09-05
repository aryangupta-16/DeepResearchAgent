"""documents + document_chunks (pgvector) and document-aware research sources.

Revision ID: 0004
Revises: 0003
Create Date: Phase 8

Notes:
- Requires the PostgreSQL ``vector`` extension (pgvector). The Compose file uses
  the ``pgvector/pgvector:pg16`` image, which ships it pre-installed.
- ``research_sources`` gains an explicit ``source_type`` (web | document): document
  citations reference ``documents.id`` and are never forced into fake URLs, so
  ``url`` becomes nullable.
- ``research_jobs.document_ids`` persists the user's document selection per job.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.infrastructure.database.models.document import EMBEDDING_DIMENSIONS

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector must exist before the embedding column below can be created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_reference", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "embedding",
            Vector(EMBEDDING_DIMENSIONS),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_index"
        ),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    # Cosine-similarity index for semantic retrieval.
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # Research sources become type-aware (web | document).
    op.add_column(
        "research_sources",
        sa.Column(
            "source_type", sa.String(length=20), nullable=False, server_default="web"
        ),
    )
    op.add_column(
        "research_sources",
        sa.Column("document_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_research_sources_document_id",
        "research_sources",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("research_sources", "url", existing_type=sa.Text(), nullable=True)

    # Persist the user's document selection per research job (NULL/[] = web-only).
    op.add_column(
        "research_jobs",
        sa.Column("document_ids", sa.dialects.postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_jobs", "document_ids")
    op.drop_constraint(
        "fk_research_sources_document_id", "research_sources", type_="foreignkey"
    )
    op.drop_column("research_sources", "document_id")
    op.drop_column("research_sources", "source_type")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    # NOTE: the ``vector`` extension itself is intentionally left installed.