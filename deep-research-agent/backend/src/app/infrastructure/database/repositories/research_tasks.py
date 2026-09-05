"""Research task persistence (SQLAlchemy)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ResearchTask


class ResearchTaskRepository:
    """Data-access boundary for :class:`ResearchTask`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: ResearchTask) -> ResearchTask:
        self._session.add(task)
        await self._session.flush()
        return task

    async def get_by_id(self, task_id: UUID) -> ResearchTask | None:
        return await self._session.scalar(
            select(ResearchTask).where(ResearchTask.id == task_id)
        )

    async def list_by_research_job(self, research_job_id: UUID) -> list[ResearchTask]:
        return list(
            await self._session.scalars(
                select(ResearchTask)
                .where(ResearchTask.research_job_id == research_job_id)
                .order_by(ResearchTask.created_at.asc())
            )
        )

    async def update(self, task: ResearchTask) -> ResearchTask:
        await self._session.flush()
        return task