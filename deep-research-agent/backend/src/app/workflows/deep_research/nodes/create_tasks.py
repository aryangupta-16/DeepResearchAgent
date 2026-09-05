"""Create research tasks node.

The planner's task list becomes persisted ResearchTask records (status=pending)
via the existing repository/service layer. No Redis or background queueing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.workflows.deep_research.state import ResearchState

if TYPE_CHECKING:  # pragma: no cover
    from app.research.service import ResearchService


async def create_tasks(
    state: ResearchState,
    *,
    research_service: ResearchService,
) -> ResearchState:
    """Persist one ResearchTask per planned task and store them in state."""
    plan = state.plan
    if plan is None or not plan.tasks:
        return state.model_copy(update={"errors": [*state.errors, "No tasks in research plan."]})

    descriptions = [task.description for task in plan.tasks if task.description.strip()]
    tasks = await research_service.create_research_tasks(UUID(state.run_id), descriptions)
    await research_service.update_job_progress(
        UUID(state.run_id), total_tasks=len(tasks), completed_tasks=0
    )
    return state.model_copy(update={"tasks": tasks})