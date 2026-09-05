"""Research job ORM model.

Kept deliberately free of domain logic: it is a persistence mapping. Status
semantics live in ``app.research.enums``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, String, Text, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.postgres import Base
from app.research.enums import ResearchJobStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.infrastructure.database.models.research_task import ResearchTask


def _enum_values(enum_cls: type) -> list[str]:
    """Store lowercase enum member values (e.g. "pending") in PostgreSQL."""
    return [member.value for member in enum_cls]


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Lightweight owner identity (default when no auth). Threads through to
    # long-term memory retrieval so future auth does not require a redesign.
    owner_id: Mapped[str] = mapped_column(
        String(64), default="default", server_default="default"
    )
    query: Mapped[str] = mapped_column(String(1000))
    workflow_type: Mapped[str] = mapped_column(
        String(50), default="deep_research", server_default="deep_research"
    )
    status: Mapped[ResearchJobStatus] = mapped_column(
        SAEnum(
            ResearchJobStatus,
            name="research_job_status",
            values_callable=_enum_values,
        ),
        default=ResearchJobStatus.PENDING,
        server_default=ResearchJobStatus.PENDING.value,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Aligned with migration 0002, which widened this to TEXT: it stores the full
    # structured report JSON (despite the historical "reference" name).
    report_reference: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 6: async execution / progress tracking
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    progress_completed_tasks: Mapped[int] = mapped_column(
        default=0, server_default="0"
    )
    progress_total_tasks: Mapped[int] = mapped_column(default=0, server_default="0")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")

    # Phase 8: uploaded documents this job may consult (empty/NULL = web-only).
    document_ids: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # Phase A: client-supplied idempotency key (POST /api/research replays).
    # NULL when absent; a partial unique index makes replays per-owner unique.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, default=None, index=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tasks: Mapped[list[ResearchTask]] = relationship(
        back_populates="research_job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ResearchJob id={self.id} status={self.status.value!r}>"