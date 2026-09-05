"""Execution boundary that runs one research job inside the worker.

The worker stays generic: it only dequeues messages and delegates to a handler.
This service encapsulates the *research-specific* execution rules:

- load the job from PostgreSQL,
- atomically claim it (``pending → running``) so a job can never run twice,
- run the existing :class:`DeepResearchWorkflow`,
- translate the outcome into ``completed`` / ``retry`` / ``failed`` / ``skipped``.

Retry policy (V1): only whole-job retries for thrown exceptions, bounded by
``max_retries``. After the last attempt the job is marked ``failed``. A workflow
that finishes but fails the job gracefully is treated as permanent (no retry).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.infrastructure.queue.tasks import ResearchJobTask
from app.research.enums import ResearchJobStatus

logger = logging.getLogger(__name__)

#: Outcome strings returned by :meth:`ResearchExecutionService.execute`.
OUTCOME_COMPLETED = "completed"
OUTCOME_RETRY = "retry"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"


class ResearchRunner(Protocol):
    """Slice of :class:`ResearchService` the execution service depends on."""

    async def get_research_job(self, research_job_id: Any) -> Any: ...
    async def claim_for_running(self, research_job_id: Any, *, attempt: int) -> bool: ...
    async def reset_job_to_pending(self, research_job_id: Any) -> bool: ...
    async def fail_research(self, research_job_id: Any, *, error: str) -> Any: ...
    def build_workflow(self, llm_provider: Any | None = None) -> Any: ...
    async def close(self) -> None: ...


class ResearchExecutionService:
    """Executes one research task inside a worker (bounded, idempotent)."""

    def __init__(
        self,
        *,
        runner_factory: Any,
        workflow_factory: Any | None = None,
        max_retries: int = 2,
    ) -> None:
        self._runner_factory = runner_factory
        self._workflow_factory = workflow_factory
        self._max_retries = max(1, max_retries)

    async def execute(self, task: ResearchJobTask) -> str:
        runner = self._runner_factory()
        try:
            if not await runner.claim_for_running(task.job_id, attempt=task.attempt):
                logger.info(
                    "Worker skipped job=%s attempt=%d (already claimed/terminal).",
                    task.job_id, task.attempt,
                )
                return OUTCOME_SKIPPED

            final, result = await self._run_workflow(runner, task)
            if result == OUTCOME_COMPLETED:
                return OUTCOME_COMPLETED
            if result == OUTCOME_RETRY:
                return OUTCOME_RETRY
            if result == OUTCOME_FAILED:
                return OUTCOME_FAILED
            return OUTCOME_SKIPPED
        finally:
            await runner.close()

    async def _run_workflow(self, runner: ResearchRunner, task: ResearchJobTask) -> tuple[Any, str]:
        workflow = (
            self._workflow_factory(runner)
            if self._workflow_factory is not None
            else runner.build_workflow()
        )
        try:
            state = await workflow.run(task.job_id)  # type: ignore[union-attr]
            del state
        except Exception as exc:
            logger.warning(
                "Job=%s attempt=%d workflow failed: %s", task.job_id, task.attempt, exc
            )
            return await self._on_workflow_failure(runner, task, exc)

        final = await runner.get_research_job(task.job_id)
        if final.status == ResearchJobStatus.COMPLETED:
            logger.info(
                "Job=%s completed attempt=%d", task.job_id, task.attempt
            )
            return final, OUTCOME_COMPLETED
        if final.status == ResearchJobStatus.FAILED:
            logger.warning("Job=%s failed gracefully attempt=%d", task.job_id, task.attempt)
            return final, OUTCOME_FAILED
        logger.warning("Job=%s finished in unexpected status %r", task.job_id, final.status)
        return final, OUTCOME_SKIPPED

    async def _on_workflow_failure(
        self, runner: ResearchRunner, task: ResearchJobTask, exc: Exception
    ) -> tuple[Any, str]:
        if task.attempt >= self._max_retries:
            await runner.fail_research(task.job_id, error=str(exc) or "research failed")
            logger.warning("Job=%s retries exhausted attempt=%d", task.job_id, task.attempt)
            return (await runner.get_research_job(task.job_id)), OUTCOME_FAILED
        await runner.reset_job_to_pending(task.job_id)
        logger.info("Job=%s queued for retry attempt=%d", task.job_id, task.attempt)
        return (await runner.get_research_job(task.job_id)), OUTCOME_RETRY