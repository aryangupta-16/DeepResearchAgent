"""Research job persistence (SQLAlchemy).

SQLAlchemy specifics live here; the service layer talks to this class instead of
constructing raw queries.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ResearchJob
from app.research.enums import ResearchJobStatus


class ResearchJobRepository:
    """Data-access boundary for :class:`ResearchJob`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job: ResearchJob) -> ResearchJob:
        self._session.add(job)
        await self._session.flush()
        return job

    async def get_by_id(self, research_job_id: UUID) -> ResearchJob | None:
        # populate_existing: raw UPDATEs elsewhere bypass the identity map, so
        # every read must reflect the database, not cached attribute values.
        return await self._session.scalar(
            select(ResearchJob)
            .where(ResearchJob.id == research_job_id)
            .execution_options(populate_existing=True)
        )

    async def get_by_idempotency_key(
        self, owner_id: str, idempotency_key: str
    ) -> ResearchJob | None:
        """Existing job created with the same owner + Idempotency-Key, if any."""
        return await self._session.scalar(
            select(ResearchJob)
            .where(
                ResearchJob.owner_id == owner_id,
                ResearchJob.idempotency_key == idempotency_key,
            )
            .execution_options(populate_existing=True)
        )

    async def update(self, job: ResearchJob) -> ResearchJob:
        await self._session.flush()
        return job

    async def list_by_status(
        self,
        status: ResearchJobStatus | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ResearchJob]:
        stmt = (
            select(ResearchJob)
            .order_by(ResearchJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(ResearchJob.status == status)
        return list(await self._session.scalars(stmt))

    # ---- Phase 6: async execution primitives ----

    async def claim_for_running(self, research_job_id: UUID, *, attempt: int) -> bool:
        """Atomically transition ``pending → running`` for exactly one worker.

        Only one competing ``UPDATE`` can match the ``status == pending`` guard, so a
        duplicate queue message (or a second worker) can never double-execute a job.
        """
        result = await self._session.execute(
            update(ResearchJob)
            .where(
                ResearchJob.id == research_job_id,
                ResearchJob.status == ResearchJobStatus.PENDING,
            )
            .values(
                status=ResearchJobStatus.RUNNING,
                started_at=func.now(),
                attempts=attempt,
            )
            .execution_options(synchronize_session=False)
        )
        return (result.rowcount or 0) == 1

    async def reset_to_pending(self, research_job_id: UUID) -> bool:
        """Move a ``running`` job back to ``pending`` (retry / crash recovery)."""
        result = await self._session.execute(
            update(ResearchJob)
            .where(
                ResearchJob.id == research_job_id,
                ResearchJob.status == ResearchJobStatus.RUNNING,
            )
            .values(status=ResearchJobStatus.PENDING, started_at=None)
            .execution_options(synchronize_session=False)
        )
        return (result.rowcount or 0) == 1

    async def list_stale_running(self, *, cutoff: datetime) -> list[ResearchJob]:
        """Jobs that have been ``running`` longer than the lease timeout (crashed)."""
        return list(
            await self._session.scalars(
                select(ResearchJob).where(
                    ResearchJob.status == ResearchJobStatus.RUNNING,
                    ResearchJob.started_at.is_not(None),
                    ResearchJob.started_at < cutoff,
                )
            )
        )

    async def reset_stale_to_pending(self, research_job_id: UUID, *, cutoff: datetime) -> bool:
        """Atomically return a stale ``running`` job to ``pending`` for recovery.

        Guarded by ``status == running`` *and* ``started_at < cutoff`` so exactly one
        reconciler wins the race; a job that was legitimately re-claimed in the
        meantime is left untouched. Resetting to ``pending`` is what allows the
        re-enqueued task to pass the ``pending → running`` idempotency guard.
        """
        result = await self._session.execute(
            update(ResearchJob)
            .where(
                ResearchJob.id == research_job_id,
                ResearchJob.status == ResearchJobStatus.RUNNING,
                ResearchJob.started_at.is_not(None),
                ResearchJob.started_at < cutoff,
            )
            .values(status=ResearchJobStatus.PENDING, started_at=None)
            .execution_options(synchronize_session=False)
        )
        return (result.rowcount or 0) == 1

    async def set_stage(self, research_job_id: UUID, stage: str) -> None:
        await self._session.execute(
            update(ResearchJob)
            .where(ResearchJob.id == research_job_id)
            .values(stage=stage)
            .execution_options(synchronize_session=False)
        )

    async def set_progress(
        self,
        research_job_id: UUID,
        *,
        completed_tasks: int | None = None,
        total_tasks: int | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if completed_tasks is not None:
            values["progress_completed_tasks"] = completed_tasks
        if total_tasks is not None:
            values["progress_total_tasks"] = total_tasks
        if not values:
            return
        await self._session.execute(
            update(ResearchJob)
            .where(ResearchJob.id == research_job_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )