"""chat sessions: conversations + chat_messages

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-02

Notes:
- ``conversations`` holds durable chat sessions; ``owner_id`` is nullable so a
  future auth system does not require migrating existing history.
- ``chat_messages`` stores each turn with provider/model + token usage so chat
  costs remain visible separately from research job costs (``job_usage``).
- Message deletion cascades from the conversation; the FK uses ondelete=CASCADE
  and the index ``(conversation_id, created_at)`` backs the history window query.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
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
    )
    op.create_index(
        "ix_conversations_owner_created", "conversations", ["owner_id", "created_at"]
    )

    op.create_table(
        "chat_messages",
        # Autoincrement int pk: deterministic ordering for same-timestamp turns
        # (func.now() is transaction-fixed on PostgreSQL / second-granular on
        # SQLite, so a UUID pk cannot order messages reliably).
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chat_messages_conversation_created",
        "chat_messages",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_messages_conversation_created", table_name="chat_messages"
    )
    op.drop_table("chat_messages")
    op.drop_index("ix_conversations_owner_created", table_name="conversations")
    op.drop_table("conversations")
