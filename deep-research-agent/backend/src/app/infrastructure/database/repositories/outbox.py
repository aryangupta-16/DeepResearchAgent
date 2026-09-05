"""Research job outbox persistence (SQLAlchemy)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ResearchJobOutbox


class ResearchJobOutboxRepository:
    """Data-access boundary for :class:`ResearchJobOutbox`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_job(self, research_job_id: UUID) -> ResearchJobOutbox | None:
        return await self._session.scalar(
            select(ResearchJobOutbox).where(
                ResearchJobOutbox.research_job_id == research_job_id
            )
        )

    async def create(self, row: ResearchJobOutbox) -> ResearchJobOutbox:
        self._session.add(row)
        await self._session.flush()
        return row

    async def mark_published(self, row_id: UUID, *, published_at: datetime) -> ResearchJobOutbox:
        await self._session.execute(
            update(ResearchJobOutbox)
            .where(ResearchJobOutbox.id == row_id)
            .values(published_at=published_at)
        )
        return await self._row(row_id)

    async def record_attempt(self, row_id: UUID) -> None:
        await self._session.execute(
            update(ResearchJobOutbox)
            .where(ResearchJobOutbox.id == row_id)
            .values(attempts=ResearchJobOutbox.attempts + 1)
        )

    async def list_unpublished(self, *, limit: int = 50) -> list[ResearchJobOutbox]:
        return list(
            await self._session.scalars(
                select(ResearchJobOutbox)
                .where(ResearchJobOutbox.published_at.is_(None))
                .order_by(ResearchJobOutbox.created_at.asc())
                .limit(limit)
            )
        )

    async def _row(self, row_id: UUID) -> ResearchJobOutbox:
        return await self._session.scalar(
            select(ResearchJobOutbox).where(ResearchJobOutbox.id == row_id)
        )