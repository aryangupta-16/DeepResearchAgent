"""async research execution: progress/attempts columns + research_job_outbox

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("research_jobs") as batch:
        batch.add_column(
            sa.Column("stage", sa.String(length=50), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "progress_completed_tasks",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "progress_total_tasks",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
        )

    op.create_table(
        "research_job_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "research_job_id",
            sa.Uuid(),
            sa.ForeignKey("research_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("research_job_id", name="uq_outbox_research_job"),
    )
    op.create_index(
        "ix_research_job_outbox_published_at",
        "research_job_outbox",
        ["published_at"],
    )
    op.create_index(
        "ix_research_job_outbox_research_job_id",
        "research_job_outbox",
        ["research_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_job_outbox_research_job_id", table_name="research_job_outbox"
    )
    op.drop_index(
        "ix_research_job_outbox_published_at", table_name="research_job_outbox"
    )
    op.drop_table("research_job_outbox")
    with op.batch_alter_table("research_jobs") as batch:
        batch.drop_column("attempts")
        batch.drop_column("progress_total_tasks")
        batch.drop_column("progress_completed_tasks")
        batch.drop_column("stage")