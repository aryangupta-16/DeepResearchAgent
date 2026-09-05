"""Background worker entrypoints.

The worker is a separate process that waits on Redis for research-job ids, loads
the job from PostgreSQL, and delegates execution to the research-specific handler.
It contains **no research business logic** (the handler owns that).

``python -m app.infrastructure.queue.workers`` (or ``app.infrastructure.queue``)
starts the worker with:

- signal handling (SIGTERM/SIGINT → graceful shutdown),
- periodic reconciliation (outbox publish + stale-job reclaim),
- clean teardown of Redis + DB resources.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.config.settings import get_settings
from app.guardrails.budget import budget_tracker
from app.infrastructure.database.postgres import get_engine, get_session_factory
from app.infrastructure.queue.client import (
    get_document_queue_client,
    get_queue_client,
)
from app.infrastructure.queue.handlers import ACTION_ACK, ACTION_RETRY
from app.observability.context import (
    bind_job_context,
    clear_job_context,
)
from app.observability.metrics import (
    JOB_FAILURES,
    JOB_TOTAL_DURATION,
    JOBS_IN_FLIGHT,
    QUEUE_DEPTH,
    TASK_RETRIES,
)
from app.research.recovery import (
    DOCUMENT_PENDING_RECLAIM_SECONDS,
    requeue_stale_pending_documents,
)

logger = logging.getLogger(__name__)


async def process_next(
    queue: Any,
    handler: Any,
    *,
    timeout: float = 0.0,
) -> bool:
    """Dequeue one message and run the handler; return True if work was done."""
    task = await queue.dequeue(timeout=timeout)
    if task is None:
        return False
    action = await handler.handle(task)
    if action == ACTION_RETRY:
        logger.info("Requeueing job=%s attempt+1", task.job_id)
        await queue.requeue(task)
    else:
        await queue.acknowledge(task)
    return True


async def run_worker(
    queue: Any,
    handler: Any,
    *,
    stop_event: asyncio.Event,
    poll_timeout: float = 1.0,
    reconciler: Callable[[], Awaitable[None]] | None = None,
    reconcile_interval: float | None = None,
) -> None:
    """Consume jobs from one queue until ``stop_event`` is set (graceful shutdown)."""
    await run_worker_multi(
        queue,
        {getattr(queue, "queue_name", "research:queue"): handler},
        stop_event=stop_event,
        poll_timeout=poll_timeout,
        reconciler=reconciler,
        reconcile_interval=reconcile_interval,
    )


async def _flush_usage(usage_flusher: Callable[[], Awaitable[int]] | None) -> None:
    """Persist buffered per-job usage; failures are logged, never propagated."""
    if usage_flusher is None:
        return
    try:
        persisted = await usage_flusher()
        if persisted:
            logger.info("Persisted %d LLM usage events.", persisted)
    except Exception:  # pragma: no cover - defensive; flusher already guards
        logger.exception("Usage flush failed; continuing.")


async def _record_queue_depths(queue: Any, handlers_by_queue: dict[str, Any]) -> None:
    """Export queue + DLQ depth gauges (best-effort; never raises)."""
    try:
        for queue_name in handlers_by_queue:
            depth_fn = getattr(queue, "depth", None)
            if depth_fn is None:  # single-queue fakes in tests
                continue
            QUEUE_DEPTH.labels(queue=queue_name).set(await depth_fn(queue_name))
            dlq_name = f"{queue_name}:dlq"
            QUEUE_DEPTH.labels(queue=dlq_name).set(await depth_fn(dlq_name))
    except Exception:  # pragma: no cover - Redis hiccup mid-sweep
        logger.exception("Queue depth sampling failed; continuing.")


async def run_worker_multi(
    queue: Any,
    handlers_by_queue: dict[str, Any],
    *,
    stop_event: asyncio.Event,
    poll_timeout: float = 1.0,
    reconciler: Callable[[], Awaitable[None]] | None = None,
    reconcile_interval: float | None = None,
    usage_flusher: Callable[[], Awaitable[int]] | None = None,
) -> None:
    """Consume from every registered queue, dispatching to the matching handler.

    Supports two queue interfaces so legacy single-queue fakes/queues keep working:
    a multi-queue transport that implements ``dequeue_any`` (the current Redis
    client) routing by origin queue, or a single-queue transport that implements
    ``dequeue`` (used by unit-test fakes and any single-queue caller).

    ``usage_flusher`` (optional) persists buffered per-job LLM token usage at
    safe commit points — after each handled task and after each reconcile sweep.
    """
    import time

    use_multi = hasattr(queue, "dequeue_any")

    async def _pop():
        if use_multi:
            return await queue.dequeue_any(
                list(handlers_by_queue), timeout=poll_timeout
            )
        task = await queue.dequeue(timeout=poll_timeout)
        if task is None:
            return None
        # Single-queue callers carry a single handler; route to it.
        return next(iter(handlers_by_queue)), task

    last_reconcile = 0.0
    while not stop_event.is_set():
        if reconciler is not None and reconcile_interval:
            now = time.monotonic()
            if now - last_reconcile >= reconcile_interval:
                last_reconcile = now
                logger.info("Running reconciliation sweep.")
                await reconciler()
                # Queue health + buffered usage at each sweep (cheap, bounded).
                await _record_queue_depths(queue, handlers_by_queue)
                await _flush_usage(usage_flusher)
        try:
            popped = await _pop()
            if popped is None:
                continue
            queue_name, task = popped
            handler = handlers_by_queue.get(queue_name)
            if handler is None:  # pragma: no cover - defensive
                logger.warning("No handler for queue %s; dropping task.", queue_name)
                continue
            # Correlation ids: every log line + metric emitted while this task runs
            # carries job/task identity.
            job_id = getattr(task, "job_id", None)
            document_id = getattr(task, "document_id", None)
            bind_job_context(
                str(job_id or document_id or ""),
                task_id=str(job_id or document_id or "") if (job_id or document_id) else "",
            )
            if job_id is not None:
                JOBS_IN_FLIGHT.inc()
            task_start = time.monotonic()
            action = ACTION_RETRY  # safe default if handler raises mid-flight
            try:
                action = await handler.handle(task)
            except Exception:
                if job_id is not None:
                    JOB_FAILURES.labels(reason="handler_error").inc()
                raise
            finally:
                clear_job_context()
                if job_id is not None:
                    JOBS_IN_FLIGHT.dec()
                    outcome_label = "ack" if action == ACTION_ACK else "retry"
                    JOB_TOTAL_DURATION.labels(outcome=outcome_label).observe(
                        time.monotonic() - task_start
                    )
                    # Phase B2: drop this job's in-process budget tally once
                    # its task is fully handled (success or failure).
                    try:
                        from uuid import UUID as _UUID

                        budget_tracker.forget(_UUID(str(job_id)))
                    except (ValueError, AttributeError):
                        pass
            # Persist token usage recorded during this task (safe commit point;
            # never raises, so it cannot fail the task outcome).
            await _flush_usage(usage_flusher)
            if action == ACTION_RETRY:
                TASK_RETRIES.inc()
                task_id = getattr(task, "job_id", None) or getattr(
                    task, "document_id", None
                )
                logger.info("Requeueing task=%s on %s.", task_id, queue_name)
                next_task = task.with_next_attempt()
                if getattr(queue, "enqueue_raw", None) is not None:
                    await queue.enqueue_raw(queue_name, next_task)
                else:
                    await queue.enqueue(next_task)
            else:
                await queue.acknowledge(task)
        except Exception:
            logger.exception("Worker iteration failed; continuing.")


def _build_document_processing_service(session_factory):
    """Assemble the document pipeline from settings (worker-side wiring)."""
    from app.documents.processing_service import DocumentProcessingService
    from app.infrastructure.storage.object_storage import build_object_store
    from app.rag.embeddings import build_embedding_provider

    settings = get_settings()
    return DocumentProcessingService(
        session_factory=session_factory,
        object_store=build_object_store(),
        embedding_provider=build_embedding_provider(),
        chunk_size=settings.document_chunk_size,
        chunk_overlap=settings.document_chunk_overlap,
    )


async def _wait_for_infrastructure() -> None:
    """Apply migrations and confirm Redis is reachable before consuming.

    Bounded, idempotent checks so a worker starting before Postgres/Redis finish
    coming up (or sharing a fresh deployment) begins cleanly instead of dying or
    silently dropping work. Fails loudly if infrastructure never becomes ready.
    """
    settings = get_settings()

    # 1. Schema (idempotent): the worker needs the research tables to exist.
    from app.infrastructure.database.migrations import run_migrations_async

    if settings.run_migrations_on_startup:
        await run_migrations_async()

    # 2. Redis connectivity (bounded).
    from redis.exceptions import RedisError

    from app.infrastructure.cache.redis import build_redis_client

    deadline = time.monotonic() + 30.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        client = build_redis_client()
        try:
            await client.ping()
            await client.aclose()
            logger.info("Redis is reachable.")
            return
        except (RedisError, OSError) as exc:  # pragma: no cover - env dependent
            last_error = exc
            await client.aclose()
            await asyncio.sleep(0.5)
    raise RuntimeError(
        f"Redis did not become reachable within 30s; check REDIS_URL connectivity: "
        f"{getattr(last_error, 'message', None) or last_error}"
    ) from last_error


async def _build_and_run(poll_timeout: float, reconcile_interval: float) -> None:
    settings = get_settings()
    await _wait_for_infrastructure()

    from app.infrastructure.queue.handlers import (
        DocumentProcessingHandler,
        ResearchJobHandler,
    )
    from app.research.execution_service import ResearchExecutionService
    from app.research.recovery import run_reconciliation_once
    from app.research.service import ResearchService

    queue = get_queue_client()
    document_queue = get_document_queue_client()

    session_factory = get_session_factory()

    def _runner_factory() -> ResearchService:
        return ResearchService(session=session_factory())

    execution = ResearchExecutionService(
        runner_factory=_runner_factory,
        max_retries=settings.research_worker_max_retries,
    )
    research_handler = ResearchJobHandler(
        execution_service=execution,
        queue=queue,
        lease_timeout_seconds=settings.research_job_lease_timeout,
    )

    processing_service = _build_document_processing_service(session_factory)
    document_handler = DocumentProcessingHandler(processing_service=processing_service)

    handlers_by_queue = {
        queue.queue_name: research_handler,
        document_queue.queue_name: document_handler,
    }

    async def _reconcile() -> None:
        await run_reconciliation_once(
            session_factory,
            queue,
            lease_timeout_seconds=settings.research_job_lease_timeout,
        )
        # Documents: status-based reclaim (idempotent reprocessing makes this safe).
        await requeue_stale_pending_documents(
            session_factory,
            document_queue,
            older_than_seconds=DOCUMENT_PENDING_RECLAIM_SECONDS,
        )

    async def _usage_flusher() -> int:
        """Persist buffered per-job LLM token usage to the job_usage ledger."""
        from app.research.usage_service import UsageService

        async with session_factory() as session:
            persisted = await UsageService(session).flush_buffered_usage()
            await session.commit()
        return persisted

    stop_event = asyncio.Event()

    def _request_stop(*_: object) -> None:
        logger.info("Shutdown signal received; finishing current job.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - e.g. Windows
            signal.signal(sig, _request_stop)

    try:
        await run_worker_multi(
            queue,
            handlers_by_queue,
            stop_event=stop_event,
            poll_timeout=poll_timeout,
            reconciler=_reconcile,
            reconcile_interval=reconcile_interval,
            usage_flusher=_usage_flusher,
        )
    finally:
        with contextlib.suppress(Exception):
            await queue.close()
        await get_engine().dispose()


def worker_main() -> None:
    """CLI entrypoint for the worker process."""
    from prometheus_client import start_http_server

    from app.observability.logging import setup_logging

    settings = get_settings()
    setup_logging(debug=settings.debug)

    # Process-local Prometheus endpoint so the monitoring stack can scrape
    # worker-side counters (jobs, LLM tokens, circuit state, queue depth).
    start_http_server(settings.worker_metrics_port)
    logger.info(
        "Starting deep research worker (metrics on :%d).",
        settings.worker_metrics_port,
    )
    asyncio.run(
        _build_and_run(
            poll_timeout=settings.research_worker_poll_timeout,
            reconcile_interval=settings.research_outbox_sweep_interval,
        )
    )


if __name__ == "__main__":
    worker_main()
