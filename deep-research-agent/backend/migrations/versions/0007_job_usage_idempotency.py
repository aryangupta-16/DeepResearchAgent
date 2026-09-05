"""job_usage table + research_jobs.idempotency_key (Phase A)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "job_usage"
_IDEMPOTENCY_COL = "idempotency_key"
_IDEMPOTENCY_INDEX = "uq_research_jobs_owner_idempotency"


def upgrade() -> None:
    # 1) Per-job token usage ledger (append-only; no FK so cost history
    #    survives job purges).
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "completion_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_job_usage_job_id", _TABLE, ["job_id"])

    # 2) Idempotency key for POST /api/research replays. Nullable: only jobs
    #    submitted with an Idempotency-Key header carry one. The partial unique
    #    index makes duplicate replay protection owner-scoped and race-free.
    op.add_column(
        "research_jobs",
        sa.Column(_IDEMPOTENCY_COL, sa.String(128), nullable=True),
    )
    op.create_index(
        _IDEMPOTENCY_INDEX,
        "research_jobs",
        ["owner_id", _IDEMPOTENCY_COL],
        unique=True,
        postgresql_where=sa.text(f"{_IDEMPOTENCY_COL} IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_IDEMPOTENCY_INDEX, table_name="research_jobs")
    op.drop_column("research_jobs", _IDEMPOTENCY_COL)
    op.drop_index("ix_job_usage_job_id", table_name=_TABLE)
    op.drop_table(_TABLE)
