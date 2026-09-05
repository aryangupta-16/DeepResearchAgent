"""chat context: per-conversation document grounding + citations

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-02

Notes:
- ``conversations.context_mode`` toggles evidence-grounding per session:
  ``'none'`` (plain chat, Phase C1 default) or ``'documents'`` (answer grounded
  in uploaded documents via the existing RAG stack).
- ``chat_messages.citations`` is a JSON snapshot column: the immutable list of
  document citations backing an assistant reply (document id, name, page,
  excerpt, score). Snapshots are returned as-is, never queried into, so a
  portable ``JSON`` type (not JSONB) keeps the ORM usable on SQLite in tests.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "context_mode",
            sa.String(length=16),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column("citations", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "citations")
    op.drop_column("conversations", "context_mode")