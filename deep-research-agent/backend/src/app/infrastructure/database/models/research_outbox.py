"""Research job outbox ORM model.

A minimal database-backed outbox (Phase 6): created in the *same transaction* as a
``ResearchJob`` so a durable record of "this job should be executed" survives even
if Redis is temporarily unavailable. The worker sweeps unpublished rows and pushes
them into the queue, and marks them published once Redis accepted them.

This is intentionally not a general event-bus: one row per job, one event type.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.postgres import Base

#: Event type emitted for a research job that should be executed.
OUTBOX_EVENT_RESEARCH_RUN = "research.run"


class ResearchJobOutbox(Base):
    __tablename__ = "research_job_outbox"
    __table_args__ = (
        UniqueConstraint("research_job_id", name="uq_outbox_research_job"),
        Index("ix_research_job_outbox_research_job_id", "research_job_id"),
        Index("ix_research_job_outbox_published_at", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(50), default=OUTBOX_EVENT_RESEARCH_RUN)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")

    def __repr__(self) -> str:
        return (
            f"<ResearchJobOutbox job={self.research_job_id} "
            f"published={self.published_at is not None}>"
        )