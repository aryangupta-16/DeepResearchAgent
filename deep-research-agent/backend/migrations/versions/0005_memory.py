"""long-term user memory (memories) + research_jobs.owner_id.

Revision ID: 0005
Revises: 0004
Create Date: Phase 9

Notes:
- ``memories`` is durable, user-scoped, long-term context (preferences, interests,
  goals, instructions, context, facts). It is deliberately decoupled from evidence
  and sources: nothing in the research pipeline can cite a memory row.
- ``owner_id`` is a lightweight string identity (default "default") so a real auth
  system can be added later without redesigning the memory schema.
- A partial unique index (``owner_id, content_hash) WHERE is_active`` backs
  deterministic de-duplication at the database level.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.String(length=64), nullable=False, server_default="default"
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("memory_type", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="explicit"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
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
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_memories_owner_active", "memories", ["owner_id", "is_active"])
    op.create_index("ix_memories_memory_type", "memories", ["memory_type"])
    # One *active* memory per (owner, normalized content) — DB-level dedupe.
    op.execute("CREATE UNIQUE INDEX uq_memories_owner_active_hash "
               "ON memories (owner_id, content_hash) WHERE is_active")

    # Thread a lightweight owner identity through research jobs so the workflow
    # can retrieve the right user's memories once auth exists.
    op.add_column(
        "research_jobs",
        sa.Column(
            "owner_id",
            sa.String(length=64),
            nullable=False,
            server_default="default",
        ),
    )


def downgrade() -> None:
    op.drop_column("research_jobs", "owner_id")
    op.execute("DROP INDEX IF EXISTS uq_memories_owner_active_hash")
    op.drop_index("ix_memories_memory_type", table_name="memories")
    op.drop_index("ix_memories_owner_active", table_name="memories")
    op.drop_table("memories")