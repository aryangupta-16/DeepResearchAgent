"""Pydantic schemas for the citation validator."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CitationIssue(BaseModel):
    """A single citation-integrity problem found by the validator."""

    source_id: str
    message: str


class CitationValidationResult(BaseModel):
    """Result of validating a report's citation integrity."""

    valid: bool
    issues: list[CitationIssue] = Field(default_factory=list)
    checked_source_ids: list[str] = Field(default_factory=list)