"""Pydantic schemas for RAG (chunks + retrieval results)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    id: str
    document_id: str
    text: str
    metadata: dict[str, Any] = {}


class DocumentRetrievalResult(BaseModel):
    """One retrieved chunk, ready to become evidence.

    Carries everything a citation needs: which document, which page, the exact
    content, and the similarity score.
    """

    chunk_id: str
    document_id: str
    document_name: str
    page_number: int | None = None
    chunk_index: int
    content: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Backwards-compatible alias for earlier internal references.
RetrievedChunk = DocumentRetrievalResult