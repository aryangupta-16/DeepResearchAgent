"""Long-term user memory ORM model.

Durable, user-scoped memory (preferences, interests, goals, context,
instructions, facts). This is **context for personalization only** — memory is
never evidence, never a research source, and never something the report may cite.

Ownership: ``owner_id`` is a lightweight string identity (default ``"default"``)
so authentication can be added later without restructuring the schema.

Idempotency: ``uq_memories_owner_active_hash`` guarantees a given owner can only
ever hold one *active* memory with the same normalized content hash.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.postgres import Base

#: Default owner when no identity system is present (lightweight V1 ownership).
DEFAULT_MEMORY_OWNER = "default"


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_owner_active", "owner_id", "is_active"),
        # One *active* memory per (owner, normalized content) — dedupe guarantee.
        Index(
            "uq_memories_owner_active_hash",
            "owner_id",
            "content_hash",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_MEMORY_OWNER, server_default=DEFAULT_MEMORY_OWNER
    )
    content: Mapped[str] = mapped_column(Text)
    # sha256 hex of the normalized content (see memory.service.normalize_content).
    content_hash: Mapped[str] = mapped_column(String(64))
    memory_type: Mapped[str] = mapped_column(String(24), index=True)
    source: Mapped[str] = mapped_column(String(16), default="explicit")
    importance: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )

    def __repr__(self) -> str:
        return (
            f"<Memory id={self.id} owner={self.owner_id!r} "
            f"type={self.memory_type!r} active={self.is_active}>"
        )