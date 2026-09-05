"""Job-scoped repository: per-job token usage ledger."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.job_usage import JobUsage


class JobUsageRepository:
    """Append-only access to the ``job_usage`` ledger."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, usage: JobUsage) -> JobUsage:
        self._session.add(usage)
        await self._session.flush()
        return usage

    async def add_many(self, usages: list[JobUsage]) -> int:
        """Bulk-insert usage rows; returns count persisted."""
        if not usages:
            return 0
        self._session.add_all(usages)
        await self._session.flush()
        return len(usages)

    async def totals_for_job(self, job_id: UUID) -> dict[str, int]:
        """Aggregated token totals for one job."""
        stmt = select(
            func.coalesce(func.sum(JobUsage.prompt_tokens), 0),
            func.coalesce(func.sum(JobUsage.completion_tokens), 0),
            func.count(JobUsage.id),
        ).where(JobUsage.job_id == job_id)
        row = (await self._session.execute(stmt)).one()
        return {
            "prompt_tokens": int(row[0]),
            "completion_tokens": int(row[1]),
            "calls": int(row[2]),
        }

    async def list_for_job(
        self, job_id: UUID, *, limit: int = 200
    ) -> list[JobUsage]:
        stmt = (
            select(JobUsage)
            .where(JobUsage.job_id == job_id)
            .order_by(JobUsage.created_at, JobUsage.id)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
