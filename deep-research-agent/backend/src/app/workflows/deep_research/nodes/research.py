"""Research node.

Reads pending ResearchTasks, invokes the ResearcherAgent for each task
(sequentially in V1), stores results in workflow state, and updates task status:

pending → running → completed (or failed).

Policy: a failed task is recorded and the workflow continues; if no task
succeeds, finalize will fail the job.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from app.common.exceptions import AppError
from app.guardrails.budget import BudgetExceededError, budget_tracker
from app.observability.metrics import GUARDRAIL_VIOLATIONS
from app.research.enums import ResearchJobStage
from app.workflows.deep_research.state import ResearchState

if TYPE_CHECKING:  # pragma: no cover
    from app.agents.researcher.agent import ResearcherAgent
    from app.research.service import ResearchService

logger = logging.getLogger(__name__)


async def research(
    state: ResearchState,
    *,
    researcher: ResearcherAgent,
    research_service: ResearchService,
    document_retriever: object | None = None,
) -> ResearchState:
    """Execute every pending task through the researcher agent.

    Hybrid mode (Phase 8): when the job selected uploaded documents *and* a
    retriever is configured, each task gets its most relevant chunks injected
    as ``document_context``. Retrieval failures degrade to web-only for that
    task — they never fail the job.
    """
    results: list[object] = []
    errors = list(state.errors)
    job_id = UUID(state.run_id)

    await research_service.mark_job_stage(job_id, ResearchJobStage.RESEARCHING)

    document_ids: list[UUID] = []
    if state.document_ids and document_retriever is not None:
        try:
            document_ids = [UUID(value) for value in state.document_ids]
        except ValueError:
            logger.warning("Ignoring invalid document_ids on job=%s", state.run_id)

    processed = 0
    budget_hit: str | None = None
    for task in state.tasks:
        # Phase B2 cost ceiling: check the hard per-job token budget before
        # each task. On breach, stop the loop and route the job through the
        # graceful-failure path (finalize fails it with a clear reason).
        try:
            budget_tracker.ensure_within_budget(job_id)
        except BudgetExceededError as exc:
            logger.warning("Job=%s budget exhausted: %s", job_id, exc)
            budget_hit = str(exc)
            GUARDRAIL_VIOLATIONS.labels(guard="budget").inc()
            break

        try:
            await research_service.mark_task_running(task.id)

            document_context = []
            if document_ids:
                document_context = await _retrieve_document_context(
                    document_retriever,
                    query=task.description,
                    document_ids=document_ids,
                )

            result = await researcher.run(
                query=state.topic,
                task=task.description,
                research_job_id=UUID(state.run_id),
                research_task_id=task.id,
                document_context=document_context,
            )
            await research_service.complete_task(task.id, result=result.model_dump_json())
            results.append(result)
        except AppError as exc:
            logger.warning("Research task %s failed: %s", task.id, exc)
            await research_service.fail_task(task.id, error=str(exc))
            errors.append(f"Task {task.description!r}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected research task failure for %s", task.id)
            await research_service.fail_task(task.id, error=f"Unexpected error: {exc}")
            errors.append(f"Task {task.description!r}: unexpected error")

        # Progress: every attempted task (success or failure) counts as done.
        processed += 1
        await research_service.update_job_progress(job_id, completed_tasks=processed)

    # Budget halt: fail every task that never ran, and drop any collected
    # results so finalize takes the graceful-failure path with a clear reason.
    if budget_hit is not None:
        for task in state.tasks[processed:]:
            try:
                await research_service.fail_task(
                    task.id, error="Skipped: job token budget exhausted."
                )
            except AppError as exc:  # pragma: no cover - defensive
                logger.warning("Could not fail task %s: %s", task.id, exc)
        errors.append(f"Job halted: {budget_hit}")
        return state.model_copy(update={"task_results": [], "errors": errors})

    return state.model_copy(update={"task_results": results, "errors": errors})


async def _retrieve_document_context(
    retriever: object,
    *,
    query: str,
    document_ids: list[UUID],
) -> list[object]:
    """Best-effort retrieval for one task; never raises into the workflow."""
    try:
        return await retriever.retrieve(query, document_ids=document_ids)  # type: ignore[attr-defined]
    except Exception:
        logger.exception("Document retrieval failed (task continues web-only)")
        return []