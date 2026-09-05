"""Research source ORM model.

A source is one fetched external page used by one or more research tasks within a
single job. URL/content-hash deduplication happens at the service layer — the
unique constraint below backs it at the DB level.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.documents.enums import SourceType
from app.infrastructure.database.postgres import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.infrastructure.database.models.evidence import ResearchEvidence


class ResearchSource(Base):
    __tablename__ = "research_sources"
    __table_args__ = (
        UniqueConstraint(
            "research_job_id", "content_hash", name="uq_sources_job_hash"
        ),
        Index("ix_research_sources_job_id", "research_job_id"),
        Index("ix_research_sources_content_hash", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
    )
    # Optional creator task; a source may be reused across tasks within a job.
    research_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    # ``web`` sources carry a URL; ``document`` sources point at an uploaded file.
    source_type: Mapped[str] = mapped_column(
        String(20), default=SourceType.WEB.value, server_default=SourceType.WEB.value
    )
    # URL for web sources; NULL for document sources (never a fake URL).
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # For document sources: which uploaded document this source represents.
    # SET NULL (not CASCADE): deleting an uploaded document must never destroy
    # historical report evidence — the source row keeps title/locators/excerpts.
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    evidence_items: Mapped[list[ResearchEvidence]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<ResearchSource id={self.id} url={self.url!r}>"