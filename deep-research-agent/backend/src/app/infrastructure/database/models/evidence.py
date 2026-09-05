"""Evidence ORM model.

Evidence is a specific claim + (optional) supporting excerpt taken from a fetched
source. Provenance is mandatory: ``source_id`` is NOT NULL and every evidence row
records the job and task it belongs to, so citations can always trace back through
Source → URL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.postgres import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.infrastructure.database.models.research_source import ResearchSource


class ResearchEvidence(Base):
    __tablename__ = "research_evidence"
    __table_args__ = (
        Index("ix_research_evidence_task_id", "research_task_id"),
        Index("ix_research_evidence_source_id", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
    )
    research_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"),
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped[ResearchSource] = relationship(back_populates="evidence_items")

    def __repr__(self) -> str:
        return f"<ResearchEvidence id={self.id} source_id={self.source_id}>"