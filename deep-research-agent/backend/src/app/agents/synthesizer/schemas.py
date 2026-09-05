"""Pydantic schemas for the synthesizer agent.

The synthesizer combines grounded research results into a structured final report
where every section can name the sources that support it (machine-readable
citations). Sections must never cite source ids that were not provided.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchReportSection(BaseModel):
    """A section of the final report with machine-readable citations."""

    heading: str
    content: str
    citation_source_ids: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """Structured output of the synthesizer agent."""

    title: str
    summary: str
    sections: list[ResearchReportSection] = Field(default_factory=list)
    conclusion: str = ""