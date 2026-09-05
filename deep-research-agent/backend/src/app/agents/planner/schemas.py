"""Pydantic schemas for the planner agent.

The planner produces a structured research plan; agents own their output schema
so the graph can validate it without fragile string parsing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchPlanTask(BaseModel):
    """A single research task produced by the planner."""

    description: str
    notes: str = ""


class ResearchPlan(BaseModel):
    """Structured output of the planner agent."""

    objective: str
    tasks: list[ResearchPlanTask] = Field(default_factory=list)