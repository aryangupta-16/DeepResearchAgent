"""Parallel research dispatch node (placeholder)."""

from __future__ import annotations

from app.workflows.deep_research.state import ResearchState


def dispatch_research(state: ResearchState) -> ResearchState:
    """Dispatch parallel researcher agents/tasks for each planned sub-question."""
    raise NotImplementedError("dispatch_research node not implemented yet.")