"""Plan node.

1. Take the query from state.
2. Invoke PlannerAgent.
3. Validate the returned plan.
4. Store the plan in state.

The node does not contain the planner's reasoning logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.research.enums import ResearchJobStage
from app.workflows.deep_research.state import ResearchState

if TYPE_CHECKING:  # pragma: no cover
    from app.agents.planner.agent import PlannerAgent
    from app.research.service import ResearchService


async def plan(
    state: ResearchState,
    *,
    planner: PlannerAgent,
    research_service: ResearchService,
) -> ResearchState:
    """Run the planner and store the structured plan in state."""
    await research_service.mark_job_stage(UUID(state.run_id), ResearchJobStage.PLANNING)
    research_plan = await planner.run(
        state.topic,
        available_documents=state.available_documents or None,
        user_context=[m.content for m in state.memories] or None,
    )
    return state.model_copy(update={"plan": research_plan})