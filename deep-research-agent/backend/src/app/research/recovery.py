"""Recovery + reconciliation for the async research pipeline.

Runs periodically inside the worker (and can be triggered manually). Two duties:

1. **Outbox → Redis**: publish ``research_job_outbox`` rows that were written to
   PostgreSQL but never made it to Redis (e.g. Redis was down at submission time).

2. **Stale ``running`` jobs**: a job whose lease has expired (worker crashed/killed)
   is reset to ``pending`` and re-enqueued so it is executed again.

Redis remains a transient transport; PostgreSQL is the source of truth.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.infrastructure.database.repositories.outbox import ResearchJobOutboxRepository
from app.infrastructure.database.repositories.research_jobs import ResearchJobRepository
from app.infrastructure.queue.client import JobQueue
from app.infrastructure.queue.tasks import ResearchJobTask

logger = logging.getLogger(__name__)

_STALE_RECLAIM_LIMIT = 50


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def publish_pending_outbox(
    session_factory: Any, queue: JobQueue, *, limit: int = 50
) -> int:
    """Push unpublished outbox rows into Redis; mark them published on success."""
    published = 0
    async with session_factory() as session:
        outbox = ResearchJobOutboxRepository(session)
        for row in await outbox.list_unpublished(limit=limit):
            try:
                await queue.enqueue(
                    ResearchJobTask(job_id=row.research_job_id, attempt=1)
                )
            except Exception as exc:  # Redis down — keep trying next sweep
                logger.warning("Outbox publish failed job=%s: %s", row.research_job_id, exc)
                continue
            await outbox.mark_published(row.id, published_at=_utc_now())
            published += 1
        await session.commit()
    if published:
        logger.info("Outbox published %d pending job(s) to Redis.", published)
    return published


async def reclaim_stale_running(
    session_factory: Any,
    queue: JobQueue,
    *,
    lease_timeout_seconds: float,
) -> int:
    """Re-enqueue jobs stuck in ``running`` past the lease deadline."""
    cutoff = _utc_now() - timedelta(seconds=lease_timeout_seconds)
    reclaimed = 0
    async with session_factory() as session:
        jobs = ResearchJobRepository(session)
        stale = await jobs.list_stale_running(cutoff=cutoff)
        for job in stale[:_STALE_RECLAIM_LIMIT]:
            attempt = (job.attempts or 0) + 1
            try:
                # Enqueue first: if Redis is down, the job simply stays stale-running
                # and this sweep retries later — it is never stranded as a messageless
                # ``pending`` row.
                await queue.enqueue(ResearchJobTask(job_id=job.id, attempt=attempt))
            except Exception as exc:  # pragma: no cover - Redis down
                logger.warning("Reclaim enqueue failed job=%s: %s", job.id, exc)
                continue
            # Atomically reset ONLY while still stale-running; the winner resets the
            # job to ``pending`` so the re-enqueued task can pass the normal
            # ``pending → running`` idempotency claim. A losing racer's extra message
            # is harmlessly skipped by whoever dequeues it.
            if await jobs.reset_stale_to_pending(job.id, cutoff=cutoff):
                reclaimed += 1
        await session.commit()
    if reclaimed:
        logger.info("Reclaimed %d stale running job(s).", reclaimed)
    return reclaimed


#: A ``pending`` document older than this is assumed to have lost its queue
#: message (e.g. Redis was down at submission) and is re-enqueued. Safe because
#: document processing is idempotent.
DOCUMENT_PENDING_RECLAIM_SECONDS = 120


async def requeue_stale_pending_documents(
    session_factory: Any,
    queue: JobQueue,
    *,
    older_than_seconds: float = DOCUMENT_PENDING_RECLAIM_SECONDS,
) -> int:
    """Re-enqueue documents stuck in ``pending`` (lost queue message recovery).

    This is the document analogue of the research outbox sweep: PostgreSQL holds a
    durable ``pending`` row, and any delivery gap is repaired by re-enqueueing.
    Processing is idempotent, so duplicate deliveries are harmless.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from app.documents.enums import DocumentStatus
    from app.infrastructure.database.models.document import Document
    from app.infrastructure.queue.tasks import DocumentProcessingTask

    cutoff = _utc_now() - timedelta(seconds=older_than_seconds)
    requeued = 0
    async with session_factory() as session:
        rows = await session.scalars(
            select(Document).where(
                Document.status == DocumentStatus.PENDING.value,
                Document.created_at < cutoff,
            )
        )
        documents = list(rows)
        for document in documents:
            try:
                await queue.enqueue(
                    DocumentProcessingTask(document_id=document.id, attempt=1)
                )
                requeued += 1
            except Exception as exc:  # pragma: no cover - Redis down
                logger.warning(
                    "Document reclaim enqueue failed %s: %s", document.id, exc
                )
        await session.commit()

    if requeued:
        logger.info("Requeued %d stale pending document(s).", requeued)
    return requeued


async def run_reconciliation_once(
    session_factory: Any,
    queue: JobQueue,
    *,
    lease_timeout_seconds: float,
) -> tuple[int, int]:
    """Run outbox publishing + stale-job reclaim; return (published, reclaimed)."""
    published = 0
    reclaimed = 0
    try:
        published = await publish_pending_outbox(session_factory, queue)
    except Exception:
        logger.exception("Reconciliation (outbox) failed")
    try:
        reclaimed = await reclaim_stale_running(
            session_factory, queue, lease_timeout_seconds=lease_timeout_seconds
        )
    except Exception:
        logger.exception("Reconciliation (reclaim) failed")
    return published, reclaimed