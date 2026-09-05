"""Domain/API schemas for documents."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """Public representation of an uploaded document."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    processed_at: datetime | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    count: int


class RetrievalPreview(BaseModel):
    """Debug/inspection view of retrieval for one query (not used by research)."""

    query: str
    results: list[dict]