"""Pydantic schemas for the browser/fetch tool."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FetchInput(BaseModel):
    """Input for a single page fetch operation."""

    url: str = Field(..., min_length=1)
    max_bytes: int = Field(default=2_000_000, ge=1_024)  # override of the tool limit
    timeout_seconds: float | None = None  # None → tool default


class FetchedDocument(BaseModel):
    """Readable content of a fetched web page.

    ``content`` is the *extracted readable text* (HTML stripped), not the raw
    markup; ``raw_content_type`` records what the server declared.
    """

    url: str
    final_url: str
    title: str = ""
    content: str = ""
    content_type: str = ""
    fetched_at: datetime
    status_code: int = 0