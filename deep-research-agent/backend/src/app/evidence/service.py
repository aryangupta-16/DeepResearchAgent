"""Evidence domain service.

Evidence = sources/findings discovered during a research run (kept separate from
RAG). The service owns the provenance invariant: every evidence item must point at
a source that exists and belongs to the same research job. No DB queries live in
agents or routes — they go through this service / its repositories.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import EvidenceError, EvidenceNotFoundError
from app.documents.enums import SourceType
from app.evidence.repository import (
    EvidenceRepository,
    ResearchSourceRepository,
)
from app.infrastructure.database.models import ResearchEvidence, ResearchSource
from app.infrastructure.database.repositories import (
    ResearchJobRepository,
    ResearchTaskRepository,
)


def _content_hash(content: str | None, url: str) -> str:
    """Stable 64-char hash used for per-job source deduplication."""
    raw = content.strip() if content and content.strip() else url
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceRecord:
    """Internal handle for a persisted source (avoids leaking ORM objects)."""

    id: object
    research_job_id: object
    research_task_id: object | None
    url: str
    title: str
    domain: str | None
    content: str | None
    content_hash: str | None


class EvidenceService:
    """Stores and queries sources + evidence for a research job."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        source_repository: ResearchSourceRepository | None = None,
        evidence_repository: EvidenceRepository | None = None,
        task_repository: ResearchTaskRepository | None = None,
    ) -> None:
        self._session = session
        self._sources = source_repository or ResearchSourceRepository(session)
        self._evidence = evidence_repository or EvidenceRepository(session)
        self._jobs = ResearchJobRepository(session)
        self._tasks = task_repository or ResearchTaskRepository(session)

    # ---- Sources ----

    async def save_source(
        self,
        *,
        research_job_id: object,
        url: str,
        title: str = "",
        content: str = "",
        domain: str = "",
        research_task_id: object | None = None,
    ) -> ResearchSource:
        """Persist a source, deduplicating identical content within the job."""
        hash_value = _content_hash(content, url)
        existing = await self._sources.get_by_job_and_hash(research_job_id, hash_value)
        if existing is not None:
            return existing

        source = ResearchSource(
            research_job_id=research_job_id,
            research_task_id=research_task_id,
            url=url,
            title=title or "",
            domain=domain or None,
            content=content or None,
            content_hash=hash_value,
        )
        await self._sources.create(source)
        await self._commit()
        return source

    async def save_document_source(
        self,
        *,
        research_job_id: object,
        document_id: object,
        title: str,
        research_task_id: object | None = None,
    ) -> ResearchSource:
        """Persist (or fetch) the DOCUMENT-type source for one uploaded file.

        One row per (job, document) pair: the content hash is derived from the
        document id, so repeated tasks / duplicate retrieval reuse the same
        source via the existing ``uq_sources_job_hash`` constraint.
        """
        del research_task_id  # kept for symmetry; job-level dedupe wins
        hash_value = hashlib.sha256(f"document:{document_id}".encode()).hexdigest()
        existing = await self._sources.get_by_job_and_hash(research_job_id, hash_value)
        if existing is not None:
            return existing

        source = ResearchSource(
            research_job_id=research_job_id,
            research_task_id=None,
            source_type=SourceType.DOCUMENT.value,
            url=None,  # never fabricate a URL for a document source
            title=title or "Document",
            domain=None,
            content=None,
            content_hash=hash_value,
            document_id=document_id,
        )
        await self._sources.create(source)
        await self._commit()
        return source

    async def get_source(self, source_id: object) -> ResearchSource:
        source = await self._sources.get_by_id(source_id)
        if source is None:
            raise EvidenceNotFoundError(f"Research source {source_id} not found.")
        return source

    async def list_sources_for_job(self, research_job_id: object) -> list[ResearchSource]:
        return await self._sources.list_for_job(research_job_id)

    # ---- Evidence ----

    async def save_evidence(
        self,
        *,
        research_job_id: object,
        research_task_id: object,
        source_id: object,
        claim: str,
        excerpt: str = "",
        locator: str | None = None,
    ) -> ResearchEvidence:
        """Persist an evidence item, enforcing source provenance.

        Raises:
            EvidenceError: if the source does not exist or belongs to a different job.
        """
        if not claim or not claim.strip():
            raise EvidenceError("Evidence claim must not be empty.")

        source = await self._sources.get_by_id(source_id)
        if source is None:
            raise EvidenceError(
                f"Cannot store evidence for unknown source {source_id}."
            )
        if source.research_job_id != research_job_id:
            raise EvidenceError(
                "Evidence source does not belong to the given research job "
                "(provenance violation)."
            )

        # Defensive: the task must belong to the same job too.
        task = await self._tasks.get_by_id(research_task_id)
        if task is None or task.research_job_id != research_job_id:
            raise EvidenceError("Evidence task does not belong to the research job.")

        evidence = ResearchEvidence(
            research_job_id=research_job_id,
            research_task_id=research_task_id,
            source_id=source_id,
            claim=claim.strip(),
            excerpt=excerpt or None,
            locator=locator,
        )
        await self._evidence.create(evidence)
        await self._commit()
        return evidence

    async def get_evidence(self, evidence_id: object) -> ResearchEvidence:
        item = await self._evidence.get_by_id(evidence_id)
        if item is None:
            raise EvidenceNotFoundError(f"Evidence {evidence_id} not found.")
        return item

    async def list_evidence_for_source(self, source_id: object) -> list[ResearchEvidence]:
        return await self._evidence.list_for_source(source_id)

    async def list_evidence_for_research_task(
        self, research_task_id: object
    ) -> list[ResearchEvidence]:
        return await self._evidence.list_for_task(research_task_id)

    async def evidence_count_for_task(self, research_task_id: object) -> int:
        return await self._evidence.count_for_task(research_task_id)

    async def _commit(self) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise