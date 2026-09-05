"""Job handlers: map queue messages to execution + queue actions.

The generic ``QueueWorker`` only understands ``ack`` / ``retry``. Research-specific
decisions (how to execute, whether to retry) live in :class:`ResearchJobHandler`,
so the queue infrastructure itself knows nothing about research.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Protocol

from app.infrastructure.queue.client import JobQueue
from app.infrastructure.queue.tasks import ResearchJobTask

logger = logging.getLogger(__name__)

#: Queue actions the worker understands.
ACTION_ACK = "ack"
ACTION_RETRY = "retry"


class JobHandler(Protocol):
    """Contract every queue handler satisfies."""

    async def handle(self, task: ResearchJobTask) -> str: ...


class DocumentProcessingHandler:
    """Processes document tasks and decides ack/retry for the worker."""

    def __init__(self, *, processing_service: Any) -> None:
        self._processing = processing_service

    async def handle(self, task: Any) -> str:
        """Run the document pipeline; transient failures map to ``retry``."""
        logger.info(
            "Processing document=%s attempt=%d", task.document_id, task.attempt
        )
        outcome = await self._processing.process(
            task.document_id, attempt=task.attempt
        )
        logger.info("Document=%s attempt=%d outcome=%s",
                    task.document_id, task.attempt, outcome)
        if outcome == "retry":
            return ACTION_RETRY
        return ACTION_ACK


class ResearchJobHandler:
    """Executes research jobs and decides ack/retry for the worker."""

    def __init__(
        self,
        *,
        execution_service: Any,
        queue: JobQueue,
        lease_timeout_seconds: float = 90.0,
    ) -> None:
        self._execution = execution_service
        self._queue = queue
        self._lease_interval = max(lease_timeout_seconds / 2, 1.0)

    async def handle(self, task: ResearchJobTask) -> str:
        job_id = task.job_id
        with contextlib.suppress(Exception):
            await self._queue.start_lease(job_id)

        renewer = asyncio.create_task(self._renew_lease(job_id))
        try:
            outcome = await self._execution.execute(task)
        finally:
            renewer.cancel()
            with contextlib.suppress(Exception):
                await self._queue.clear_lease(job_id)

        logger.info("Job=%s attempt=%d outcome=%s", job_id, task.attempt, outcome)
        if outcome == "retry":
            return ACTION_RETRY
        return ACTION_ACK

    async def _renew_lease(self, job_id: Any) -> None:
        try:
            while True:
                await asyncio.sleep(self._lease_interval)
                with contextlib.suppress(Exception):
                    await self._queue.renew_lease(job_id)
        except asyncio.CancelledError:
            raise