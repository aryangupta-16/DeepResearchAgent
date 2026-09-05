"""Application service for research jobs.

The service is the boundary between the API layer and persistence: it applies
business rules, owns transactions, and orchestrates repositories. Routes never
touch SQLAlchemy, and the service never leaks raw ORM concepts to callers via the
schemas module.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import (
    ResearchJobInvalidStateError,
    ResearchJobNotFoundError,
    ResearchTaskNotFoundError,
    ValidationError,
)
from app.evidence.service import EvidenceService
from app.infrastructure.database.models import (
    ResearchJob,
    ResearchJobOutbox,
    ResearchTask,
)
from app.infrastructure.database.models.research_outbox import OUTBOX_EVENT_RESEARCH_RUN
from app.infrastructure.database.repositories import (
    ResearchJobOutboxRepository,
    ResearchJobRepository,
    ResearchTaskRepository,
)
from app.infrastructure.queue.client import JobQueue
from app.infrastructure.queue.tasks import ResearchJobTask
from app.research.enums import (
    ResearchJobStage,
    ResearchJobStatus,
    ResearchTaskStatus,
    validate_job_status_transition,
    validate_task_status_transition,
)
from app.research.schemas import DEFAULT_WORKFLOW_TYPE, DeepResearchResponse
from app.workflows.registry import registry

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ResearchService:
    """Application operations for creating and tracking research jobs."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        job_repository: ResearchJobRepository | None = None,
        task_repository: ResearchTaskRepository | None = None,
        outbox_repository: ResearchJobOutboxRepository | None = None,
        queue: JobQueue | None = None,
    ) -> None:
        self._session = session
        self._jobs = job_repository if job_repository is not None else ResearchJobRepository(
            session
        )
        self._tasks = task_repository if task_repository is not None else ResearchTaskRepository(
            session
        )
        self._outbox = (
            outbox_repository
            if outbox_repository is not None
            else ResearchJobOutboxRepository(session)
        )
        self._queue = queue

    @property
    def session(self) -> AsyncSession:
        """The bound session (read-only access for composing other services)."""
        return self._session

    async def create_research_job(
        self,
        *,
        query: str,
        workflow_type: str | None = None,
        document_ids: list[object] | None = None,
        owner_id: str = "default",
        idempotency_key: str | None = None,
    ) -> ResearchJob:
        """Validate, persist, and return a new job in ``pending`` state.

        With an ``idempotency_key`` (Phase A), replaying the same key for the
        same owner returns the original job instead of creating a duplicate —
        safe against concurrent submissions via the partial unique index (a
        race loses the insert and re-reads the winner).
        """
        if not query or not query.strip():
            raise ValidationError("query must not be empty.")

        normalized_workflow = (workflow_type or "").strip() or DEFAULT_WORKFLOW_TYPE
        normalized_document_ids = await self._validate_document_ids(document_ids)
        normalized_owner = (owner_id or "default").strip() or "default"

        if idempotency_key:
            existing = await self._jobs.get_by_idempotency_key(
                normalized_owner, idempotency_key
            )
            if existing is not None:
                return existing

        job = ResearchJob(
            query=query.strip(),
            workflow_type=normalized_workflow,
            status=ResearchJobStatus.PENDING,
            document_ids=normalized_document_ids or None,
            owner_id=normalized_owner,
            idempotency_key=idempotency_key or None,
        )
        try:
            await self._jobs.create(job)
            await self._commit()
        except IntegrityError:
            # Concurrent duplicate submission: the unique index decided; return
            # the winning job so the caller still gets a stable 202 response.
            await self._session.rollback()
            if idempotency_key:
                existing = await self._jobs.get_by_idempotency_key(
                    normalized_owner, idempotency_key
                )
                if existing is not None:
                    return existing
            raise
        await self._session.refresh(job)
        return job

    async def _validate_document_ids(
        self, document_ids: list[object] | None
    ) -> list[str]:
        """Validate an explicit document selection (Phase 8).

        Every id must reference an existing document in ``ready`` state — we never
        silently attach processing/failed documents to a research job.
        """
        if not document_ids:
            return []

        from app.documents.enums import DocumentStatus
        from app.documents.repository import DocumentRepository

        repo = DocumentRepository(self._session)
        normalized: list[str] = []
        for raw in document_ids:
            try:
                document_id = UUID(str(raw))
            except ValueError as exc:
                raise ValidationError(f"Invalid document id: {raw!r}") from exc
            document = await repo.get_by_id(document_id)
            if document is None:
                raise ValidationError(f"Document {document_id} does not exist.")
            if document.status != DocumentStatus.READY.value:
                raise ValidationError(
                    f"Document {document.filename} is not ready "
                    f"(status={document.status})."
                )
            if str(document_id) not in normalized:
                normalized.append(str(document_id))
        return normalized

    async def get_research_job(self, research_job_id: UUID) -> ResearchJob:
        job = await self._jobs.get_by_id(research_job_id)
        if job is None:
            raise ResearchJobNotFoundError(
                f"Research job {research_job_id} not found."
            )
        return job

    async def list_research_jobs(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        status: ResearchJobStatus | None = None,
    ) -> list[ResearchJob]:
        """Recent jobs, newest first (history sidebar)."""
        return await self._jobs.list_by_status(
            status, limit=max(1, min(limit, 100)), offset=max(0, offset)
        )

    async def cancel_research_job(self, research_job_id: UUID) -> ResearchJob:
        """Cancel a job that has not reached a terminal status."""
        job = await self.get_research_job(research_job_id)
        validate_job_status_transition(job.status, ResearchJobStatus.CANCELLED)
        job.status = ResearchJobStatus.CANCELLED
        await self._jobs.update(job)
        await self._commit()
        return job

    async def create_research_task(
        self,
        *,
        research_job_id: UUID,
        description: str,
    ) -> ResearchTask:
        """Persist a pending task under an existing research job."""
        if not description or not description.strip():
            raise ValidationError("description must not be empty.")

        job = await self.get_research_job(research_job_id)
        task = ResearchTask(
            research_job_id=job.id,
            description=description.strip(),
            status=ResearchTaskStatus.PENDING,
        )
        await self._tasks.create(task)
        await self._commit()
        await self._session.refresh(task)
        return task

    async def create_research_tasks(
        self,
        research_job_id: UUID,
        descriptions: list[str],
    ) -> list[ResearchTask]:
        """Persist multiple pending tasks for a job in a single transaction."""
        job = await self.get_research_job(research_job_id)
        tasks: list[ResearchTask] = []
        for description in descriptions:
            if not description or not description.strip():
                raise ValidationError("task description must not be empty.")
            task = ResearchTask(
                research_job_id=job.id,
                description=description.strip(),
                status=ResearchTaskStatus.PENDING,
            )
            await self._tasks.create(task)
            tasks.append(task)
        await self._commit()
        return tasks

    async def get_research_tasks(self, research_job_id: UUID) -> list[ResearchTask]:
        """Return a job's tasks, raising 404 if the job does not exist."""
        await self.get_research_job(research_job_id)
        return await self._tasks.list_by_research_job(research_job_id)

    # ---- Job lifecycle (used by the workflow) ----

    async def start_research(self, research_job_id: UUID) -> ResearchJob:
        """Transition a pending job to ``running`` and stamp ``started_at``."""
        job = await self.get_research_job(research_job_id)
        validate_job_status_transition(job.status, ResearchJobStatus.RUNNING)
        job.status = ResearchJobStatus.RUNNING
        job.started_at = _utc_now()
        await self._jobs.update(job)
        await self._commit()
        return job

    async def complete_research(
        self,
        research_job_id: UUID,
        *,
        report: str | None = None,
    ) -> ResearchJob:
        """Transition a running job to ``completed`` and persist the full report.

        ``report`` is the complete structured report (JSON/text), so no truncation
        is applied — the DB column was widened to ``Text`` in migration 0002.
        """
        job = await self.get_research_job(research_job_id)
        validate_job_status_transition(job.status, ResearchJobStatus.COMPLETED)
        job.status = ResearchJobStatus.COMPLETED
        job.completed_at = _utc_now()
        if report:
            job.report_reference = report
        await self._jobs.update(job)
        await self._commit()
        return job

    async def fail_research(self, research_job_id: UUID, *, error: str) -> ResearchJob:
        """Transition a non-terminal job to ``failed`` and persist the error."""
        job = await self.get_research_job(research_job_id)
        validate_job_status_transition(job.status, ResearchJobStatus.FAILED)
        job.status = ResearchJobStatus.FAILED
        job.error = (error or "unknown error")[:2000]
        job.completed_at = _utc_now()
        await self._jobs.update(job)
        await self._commit()
        return job

    # ---- Task lifecycle (used by the workflow) ----

    async def mark_task_running(self, task_id: UUID) -> ResearchTask:
        """Transition a pending task to ``running``."""
        task = await self._get_task(task_id)
        validate_task_status_transition(task.status, ResearchTaskStatus.RUNNING)
        task.status = ResearchTaskStatus.RUNNING
        task.started_at = _utc_now()
        await self._tasks.update(task)
        await self._commit()
        return task

    async def complete_task(self, task_id: UUID, *, result: str) -> ResearchTask:
        """Transition a running task to ``completed`` and store its result."""
        task = await self._get_task(task_id)
        validate_task_status_transition(task.status, ResearchTaskStatus.COMPLETED)
        task.status = ResearchTaskStatus.COMPLETED
        task.result = (result or "")[:10000]
        task.completed_at = _utc_now()
        await self._tasks.update(task)
        await self._commit()
        return task

    async def fail_task(self, task_id: UUID, *, error: str) -> ResearchTask:
        """Transition a non-terminal task to ``failed`` and store its error."""
        task = await self._get_task(task_id)
        validate_task_status_transition(task.status, ResearchTaskStatus.FAILED)
        task.status = ResearchTaskStatus.FAILED
        task.error = (error or "unknown error")[:2000]
        task.completed_at = _utc_now()
        await self._tasks.update(task)
        await self._commit()
        return task

    async def _get_task(self, task_id: UUID) -> ResearchTask:
        task = await self._tasks.get_by_id(task_id)
        if task is None:
            raise ResearchTaskNotFoundError(f"Research task {task_id} not found.")
        return task

    # ---- Phase 6: asynchronous submission + execution primitives ----

    async def submit_research_job(self, research_job_id: UUID) -> None:
        """Durably enqueue a pending job for the worker.

        Strategy — database-backed outbox:

        1. If the job already has a *published* outbox row, the worker will pick it
           up; re-submission is a safe no-op (idempotency).
        2. Otherwise create the outbox row (durable) and try to push the job id to
           Redis. If Redis is temporarily unavailable, the row stays unpublished and
           the worker's reconciliation sweep publishes it later — the job can never
           be silently lost between PostgreSQL and Redis.
        """
        job = await self.get_research_job(research_job_id)

        existing = await self._outbox.get_by_job(research_job_id)
        if existing is not None and existing.published_at is not None:
            return

        if existing is None:
            row = ResearchJobOutbox(
                research_job_id=research_job_id,
                event_type=OUTBOX_EVENT_RESEARCH_RUN,
            )
            await self._outbox.create(row)
        else:
            row = existing

        # Try to publish now; on failure leave it unpublished for the worker sweep.
        if self._queue is not None:
            try:
                await self._queue.enqueue(
                    ResearchJobTask(job_id=research_job_id, attempt=max(job.attempts or 1, 1))
                )
            except Exception:  # Redis unreachable — outbox guarantees eventual delivery
                logger.warning(
                    "Queue publish failed for job=%s; outbox will retry.", research_job_id
                )
                await self._commit()
                return
            await self._outbox.mark_published(row.id, published_at=_utc_now())
        await self._commit()

    async def claim_for_running(self, research_job_id: UUID, *, attempt: int) -> bool:
        """Atomically claim a pending job for execution (idempotency guard)."""
        claimed = await self._jobs.claim_for_running(research_job_id, attempt=attempt)
        if claimed:
            await self._commit()
        return claimed

    async def reset_job_to_pending(self, research_job_id: UUID) -> bool:
        """Move a ``running`` job back to ``pending`` (retry / crash recovery)."""
        reset = await self._jobs.reset_to_pending(research_job_id)
        if reset:
            await self._commit()
        return reset

    async def mark_job_stage(self, research_job_id: UUID, stage: ResearchJobStage) -> None:
        await self._jobs.set_stage(research_job_id, stage.value)
        await self._commit()

    async def update_job_progress(
        self,
        research_job_id: UUID,
        *,
        completed_tasks: int | None = None,
        total_tasks: int | None = None,
    ) -> None:
        await self._jobs.set_progress(
            research_job_id,
            completed_tasks=completed_tasks,
            total_tasks=total_tasks,
        )
        await self._commit()

    def build_workflow(self, llm_provider: object | None = None) -> object:
        """Build the deep research workflow bound to this job's session."""
        return registry.get(
            "deep_research",
            research_service=self,
            llm_provider=llm_provider,
            evidence_service=EvidenceService(self._session),
        )

    # ---- Workflow execution (synchronous in V1) ----

    async def run_research(
        self,
        research_job_id: UUID,
        *,
        llm_provider: object | None = None,
    ) -> DeepResearchResponse:
        """Execute the deep research workflow for a job and return the outcome."""
        job = await self.get_research_job(research_job_id)
        if job.status != ResearchJobStatus.PENDING:
            raise ResearchJobInvalidStateError(
                f"Cannot run research job in status {job.status.value!r}; "
                "only 'pending' jobs can be started."
            )

        await self.start_research(research_job_id)

        try:
            workflow = registry.get(
                "deep_research",
                research_service=self,
                llm_provider=llm_provider,
                evidence_service=EvidenceService(self._session),
            )
            result = await workflow.run(research_job_id)  # type: ignore[union-attr]
            final = await self.get_research_job(research_job_id)
            return DeepResearchResponse(
                id=str(final.id),
                status=final.status.value,
                query=final.query,
                report=result.final_report or None,
                error=final.error,
            )
        except Exception as exc:
            logger.exception("Deep research workflow failed job=%s", research_job_id)
            await self._safe_fail(research_job_id, error=str(exc))
            final = await self.get_research_job(research_job_id)
            return DeepResearchResponse(
                id=str(final.id),
                status=final.status.value,
                query=final.query,
                error=final.error or str(exc),
            )

    async def _safe_fail(self, research_job_id: UUID, *, error: str) -> None:
        try:
            await self.fail_research(research_job_id, error=error)
        except Exception:
            logger.exception("Failed to mark job %s failed", research_job_id)

    async def _commit(self) -> None:
        """Commit the current transaction, rolling back explicitly on failure."""
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def close(self) -> None:
        """Release the underlying database session (worker uses per-job sessions)."""
        await self._session.close()