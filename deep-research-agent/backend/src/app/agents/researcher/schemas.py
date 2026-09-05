"""Pydantic schemas for the researcher agent.

The researcher performs bounded real web search via tools and produces structured
findings. A finding is *grounded*: it references the evidence items and sources it
was derived from, so downstream synthesis and citation validation never rely on
the LLM remembering URLs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchFinding(BaseModel):
    """A single finding anchored to persisted evidence + sources."""

    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class ResearchResult(BaseModel):
    """Structured output of the researcher agent for one task."""

    task: str
    summary: str
    findings: list[ResearchFinding] = Field(default_factory=list)


class ResearcherQuerySet(BaseModel):
    """LLM output: candidate search queries for a task."""

    queries: list[str] = Field(default_factory=list)


class ResearcherSourceSelection(BaseModel):
    """LLM output: indices of the search results worth fetching."""

    indices: list[int] = Field(default_factory=list)


class ResearcherEvidenceItem(BaseModel):
    """A single evidence candidate extracted by the LLM from fetched content."""

    claim: str = Field(..., min_length=1)
    excerpt: str = ""
    locator: str | None = None


class ResearcherEvidenceList(BaseModel):
    """LLM output: evidence items extracted from one source page."""

    evidence: list[ResearcherEvidenceItem] = Field(default_factory=list)


class ResearcherSummary(BaseModel):
    """LLM output: short summary of the task's findings."""

    summary: str = ""