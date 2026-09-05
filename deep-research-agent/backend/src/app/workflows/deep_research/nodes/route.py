"""Graph nodes for the deep research workflow (placeholders).

Nodes are thin orchestration steps; they delegate reasoning to agents and
deterministic work to tools/domain services.
"""

from __future__ import annotations

from app.workflows.deep_research.state import ResearchState


def route(state: ResearchState) -> ResearchState:
    """Initial routing/entry node."""
    state.status = "route"
    return state