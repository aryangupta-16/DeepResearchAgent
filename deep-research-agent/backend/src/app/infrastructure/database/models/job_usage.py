"""Per-job LLM token usage ORM model (Phase A cost accounting).

One row per recorded LLM call, keyed to the research job that incurred it.
Deliberately no FK constraint: usage rows survive even if jobs are purged,
keeping the cost history append-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.postgres import Base


class JobUsage(Base):
    __tablename__ = "job_usage"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<JobUsage job_id={self.job_id} provider={self.provider!r} "
            f"prompt={self.prompt_tokens} completion={self.completion_tokens}>"
        )
