"""create research_jobs and research_tasks

Revision ID: 0001
Revises:
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_STATUS = sa.Enum(
    "pending", "running", "completed", "failed", "cancelled",
    name="research_job_status",
)
_TASK_STATUS = sa.Enum(
    "pending", "running", "completed", "failed", "cancelled",
    name="research_task_status",
)


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.String(length=1000), nullable=False),
        sa.Column(
            "workflow_type",
            sa.String(length=50),
            server_default="deep_research",
            nullable=False,
        ),
        sa.Column("status", _JOB_STATUS, server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("report_reference", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_jobs_status", "research_jobs", ["status"])

    op.create_table(
        "research_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_job_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("status", _TASK_STATUS, server_default="pending", nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["research_job_id"],
            ["research_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_tasks_research_job_id", "research_tasks", ["research_job_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_research_tasks_research_job_id", table_name="research_tasks")
    op.drop_table("research_tasks")
    op.drop_index("ix_research_jobs_status", table_name="research_jobs")
    op.drop_table("research_jobs")
    op.execute("DROP TYPE research_job_status")
    op.execute("DROP TYPE research_task_status")