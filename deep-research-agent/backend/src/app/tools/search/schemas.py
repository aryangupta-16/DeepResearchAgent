"""Pydantic schemas for the search tool.

A search result contains only application-level fields (no raw vendor
objects). ``source``/``domain`` capture the originating site so consumers can
attribute findings without vendor SDK types leaking into application code.
"""

from __future__ import annotations

from typing import Any

from pydantic import AnyUrl, BaseModel, Field

DEFAULT_SEARCH_LIMIT = 5


class SearchQuery(BaseModel):
    """Input for a search operation."""

    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=50)


class SearchResult(BaseModel):
    """A single search result."""

    title: str
    url: AnyUrl
    snippet: str = ""
    domain: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Aggregated search response."""

    query: str
    results: list[SearchResult] = Field(default_factory=list)
    total: int | None = None
