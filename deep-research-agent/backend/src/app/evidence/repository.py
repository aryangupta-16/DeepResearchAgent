"""Evidence persistence (SQLAlchemy repositories).

SQLAlchemy specifics live here. The evidence service talks to these classes
instead of constructing raw queries, so callers never touch ORM plumbing.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ResearchEvidence, ResearchSource


class ResearchSourceRepository:
    """Data-access boundary for :class:`ResearchSource`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, source: ResearchSource) -> ResearchSource:
        self._session.add(source)
        await self._session.flush()
        return source

    async def get_by_id(self, source_id: UUID) -> ResearchSource | None:
        return await self._session.scalar(
            select(ResearchSource).where(ResearchSource.id == source_id)
        )

    async def get_by_job_and_hash(
        self, research_job_id: UUID, content_hash: str
    ) -> ResearchSource | None:
        return await self._session.scalar(
            select(ResearchSource).where(
                ResearchSource.research_job_id == research_job_id,
                ResearchSource.content_hash == content_hash,
            )
        )

    async def list_for_job(self, research_job_id: UUID) -> list[ResearchSource]:
        return list(
            await self._session.scalars(
                select(ResearchSource)
                .where(ResearchSource.research_job_id == research_job_id)
                .order_by(ResearchSource.retrieved_at.asc())
            )
        )


class EvidenceRepository:
    """Data-access boundary for :class:`ResearchEvidence`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, evidence: ResearchEvidence) -> ResearchEvidence:
        self._session.add(evidence)
        await self._session.flush()
        return evidence

    async def get_by_id(self, evidence_id: UUID) -> ResearchEvidence | None:
        return await self._session.scalar(
            select(ResearchEvidence).where(ResearchEvidence.id == evidence_id)
        )

    async def list_for_source(self, source_id: UUID) -> list[ResearchEvidence]:
        return list(
            await self._session.scalars(
                select(ResearchEvidence)
                .where(ResearchEvidence.source_id == source_id)
                .order_by(ResearchEvidence.created_at.asc())
            )
        )

    async def list_for_task(self, research_task_id: UUID) -> list[ResearchEvidence]:
        return list(
            await self._session.scalars(
                select(ResearchEvidence)
                .where(ResearchEvidence.research_task_id == research_task_id)
                .order_by(ResearchEvidence.created_at.asc())
            )
        )

    async def count_for_task(self, research_task_id: UUID) -> int:
        return len(
            await self._session.scalars(
                select(ResearchEvidence.id).where(
                    ResearchEvidence.research_task_id == research_task_id
                )
            )
        )