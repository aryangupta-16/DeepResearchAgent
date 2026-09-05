"""Gap evaluation node (placeholder)."""

from __future__ import annotations

from app.workflows.deep_research.state import ResearchState


def evaluate_gaps(state: ResearchState) -> ResearchState:
    """Assess uncovered questions and decide whether to iterate."""
    raise NotImplementedError("evaluate_gaps node not implemented yet.")