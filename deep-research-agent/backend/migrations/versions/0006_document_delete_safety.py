"""document sources FK: ondelete CASCADE -> SET NULL; document delete support

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "research_sources"
_FK = "fk_research_sources_document_id"


def upgrade() -> None:
    """Deleting a document must keep historical report sources intact."""
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.create_foreign_key(
        _FK,
        _TABLE,
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.create_foreign_key(
        _FK,
        _TABLE,
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
