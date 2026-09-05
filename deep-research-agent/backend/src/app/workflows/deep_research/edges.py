"""Graph edges / conditional routing for the deep research workflow (placeholder)."""

from __future__ import annotations

from app.workflows.deep_research.state import ResearchState


def route_after_collection(state: ResearchState) -> str:  # pragma: no cover - placeholder
    """Decide whether more research is needed or whether to synthesize.

    Returns a node name to route to ("evaluate_gaps" / "synthesize").
    """
    raise NotImplementedError("Routing between collection and synthesis is not built yet.")