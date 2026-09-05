"""Domain schemas for evidence (sources + evidence items).

Kept deliberately separate from RAG: evidence represents sources/findings
discovered during a research run with mandatory provenance back to a source.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ResearchSourceCreate(BaseModel):
    """Payload to persist a fetched source."""

    research_job_id: UUID
    research_task_id: UUID | None = None
    url: str = Field(..., min_length=1)
    title: str = ""
    domain: str = ""
    content: str = ""


class ResearchSourceSchema(BaseModel):
    """API/domain representation of a research source."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    research_job_id: UUID
    research_task_id: UUID | None = None
    url: str
    title: str
    domain: str | None = None
    content: str | None = None
    content_hash: str | None = None
    retrieved_at: datetime


class ResearchEvidenceCreate(BaseModel):
    """Payload to persist a single evidence item."""

    research_job_id: UUID
    research_task_id: UUID
    source_id: UUID
    claim: str = Field(..., min_length=1)
    excerpt: str = ""
    locator: str | None = None


class ResearchEvidenceSchema(BaseModel):
    """Domain representation of an evidence item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    research_job_id: UUID
    research_task_id: UUID
    source_id: UUID
    claim: str
    excerpt: str | None = None
    locator: str | None = None
    created_at: datetime