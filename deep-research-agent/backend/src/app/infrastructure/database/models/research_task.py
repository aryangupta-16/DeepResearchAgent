"""Research task ORM model.

A task belongs to exactly one research job; all task semantics (statuses,
transitions) live in ``app.research.enums``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.models.research_job import _enum_values
from app.infrastructure.database.postgres import Base
from app.research.enums import ResearchTaskStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.infrastructure.database.models.research_job import ResearchJob


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    research_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
        index=True,
    )
    description: Mapped[str] = mapped_column(String(1000))
    status: Mapped[ResearchTaskStatus] = mapped_column(
        SAEnum(
            ResearchTaskStatus,
            name="research_task_status",
            values_callable=_enum_values,
        ),
        default=ResearchTaskStatus.PENDING,
        server_default=ResearchTaskStatus.PENDING.value,
    )
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    research_job: Mapped[ResearchJob] = relationship(back_populates="tasks")

    def __repr__(self) -> str:
        return f"<ResearchTask id={self.id} status={self.status.value!r}>"