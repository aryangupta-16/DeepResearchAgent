"""Pydantic schemas for the research domain.

These are the API contract. Internal SQLAlchemy objects are never returned
directly from routes; responses are built from these schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.research.enums import ResearchJobStatus, ResearchTaskStatus

DEFAULT_WORKFLOW_TYPE = "deep_research"

QueryField = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
WorkflowTypeField = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]
#: Lightweight owner identity for future auth; defaults to a shared owner.
ResearchOwnerField = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class ResearchCreateRequest(BaseModel):
    """Payload for creating a new research job."""

    query: QueryField
    workflow_type: WorkflowTypeField = DEFAULT_WORKFLOW_TYPE
    owner_id: ResearchOwnerField = "default"
    # Phase 8: uploaded documents to consult (NULL/empty = web-only).
    document_ids: list[UUID] = Field(default_factory=list)


class JobProgress(BaseModel):
    """Coarse task progress for a research job."""

    completed_tasks: int = 0
    total_tasks: int = 0


class ResearchJobResponse(BaseModel):
    """API representation of a research job."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    query: str
    workflow_type: str
    status: ResearchJobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    # Phase 6: async execution + progress tracking
    stage: str | None = None
    attempts: int = 0
    progress: JobProgress = Field(default_factory=JobProgress)
    # Full structured report; only populated once the job is completed.
    report: str | None = None


class ResearchJobSummaryResponse(BaseModel):
    """Lightweight job row for the history list (no report payload)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    query: str
    workflow_type: str
    status: ResearchJobStatus
    created_at: datetime
    completed_at: datetime | None = None


class ResearchListResponse(BaseModel):
    """Paginated research history, newest first."""

    items: list[ResearchJobSummaryResponse] = Field(default_factory=list)
    count: int
    limit: int
    offset: int


class ResearchTaskResponse(BaseModel):
    """API representation of a research task."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    research_job_id: UUID
    description: str
    status: ResearchTaskStatus
    result: str | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ResearchTasksResponse(BaseModel):
    """Tasks belonging to a research job."""

    research_id: UUID
    tasks: list[ResearchTaskResponse] = Field(default_factory=list)


# ---- Sources & evidence (Phase 7: citation inspection UX) ----


class EvidenceItemResponse(BaseModel):
    """A single piece of supporting evidence for a source."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim: str
    excerpt: str | None = None
    locator: str | None = None


class SourceWithEvidenceResponse(BaseModel):
    """A captured provenance unit plus the evidence extracted from it.

    ``web`` sources carry a URL; ``document`` sources instead point at an
    uploaded document (``document_id``) and evidence locators carry page info.
    """

    id: UUID
    url: str | None = None
    title: str
    domain: str | None = None
    source_type: str = "web"
    document_id: UUID | None = None
    retrieved_at: datetime
    evidence: list[EvidenceItemResponse] = Field(default_factory=list)


class ResearchSourcesResponse(BaseModel):
    """All sources (+evidence) captured during one research job."""

    research_id: UUID
    sources: list[SourceWithEvidenceResponse] = Field(default_factory=list)


# Deep research API schemas
class DeepResearchResponse(BaseModel):
    """Response from executing a research job."""

    id: str
    status: str
    query: str
    report: str | None = None
    error: str | None = None
