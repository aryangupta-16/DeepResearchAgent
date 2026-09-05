"""Finalize node.

1. Decide success/failure based on collected results.
2. Update the ResearchJob status via the existing domain rules.
3. Persist the report reference and completion timestamps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.research.enums import ResearchJobStage
from app.workflows.deep_research.state import ResearchState

if TYPE_CHECKING:  # pragma: no cover
    from app.research.service import ResearchService


async def finalize(
    state: ResearchState,
    *,
    research_service: ResearchService,
) -> ResearchState:
    """Persist the final job state (completed or failed)."""
    job_id = UUID(state.run_id)
    if state.errors and not state.task_results:
        await research_service.fail_research(job_id, error="; ".join(state.errors))
        await research_service.mark_job_stage(job_id, ResearchJobStage.FAILED)
        return state.model_copy(update={"status": "failed"})

    report = state.final_report or ""
    await research_service.complete_research(job_id, report=report)
    await research_service.mark_job_stage(job_id, ResearchJobStage.COMPLETED)
    return state.model_copy(update={"status": "completed"})