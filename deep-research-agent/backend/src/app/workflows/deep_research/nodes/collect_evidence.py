"""Evidence collection node (placeholder)."""

from __future__ import annotations

from app.workflows.deep_research.state import ResearchState


def collect_evidence(state: ResearchState) -> ResearchState:
    """Aggregate evidence yielded by dispatched researchers."""
    raise NotImplementedError("collect_evidence node not implemented yet.")