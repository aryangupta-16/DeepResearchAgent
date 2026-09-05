"""add research_sources, research_evidence, widen report_reference

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "research_job_id",
            sa.Uuid(),
            sa.ForeignKey("research_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "research_task_id",
            sa.Uuid(),
            sa.ForeignKey("research_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "research_job_id", "content_hash", name="uq_sources_job_hash"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_sources_job_id", "research_sources", ["research_job_id"]
    )
    op.create_index(
        "ix_research_sources_content_hash", "research_sources", ["content_hash"]
    )

    op.create_table(
        "research_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "research_job_id",
            sa.Uuid(),
            sa.ForeignKey("research_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "research_task_id",
            sa.Uuid(),
            sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("research_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("locator", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_evidence_task_id", "research_evidence", ["research_task_id"]
    )
    op.create_index(
        "ix_research_evidence_source_id", "research_evidence", ["source_id"]
    )

    # §23: store the full structured report (JSON) instead of a 500-char pointer.
    with op.batch_alter_table("research_jobs") as batch:
        batch.alter_column(
            "report_reference",
            existing_type=sa.String(length=500),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("research_jobs") as batch:
        batch.alter_column(
            "report_reference",
            existing_type=sa.Text(),
            type_=sa.String(length=500),
            existing_nullable=True,
        )
    op.drop_index(
        "ix_research_evidence_source_id", table_name="research_evidence"
    )
    op.drop_index(
        "ix_research_evidence_task_id", table_name="research_evidence"
    )
    op.drop_table("research_evidence")
    op.drop_index(
        "ix_research_sources_content_hash", table_name="research_sources"
    )
    op.drop_index(
        "ix_research_sources_job_id", table_name="research_sources"
    )
    op.drop_table("research_sources")