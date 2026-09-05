"""Search tools.

Public API:

- :class:`SearchTool` — deterministic tool wrapping a :class:`SearchProvider`.
- :class:`SearchProvider` — abstract backend contract.
- :class:`SerperSearchProvider` / :class:`SerpApiSearchProvider` — concrete providers.
- :func:`build_search_provider` — factory from settings.
"""

from __future__ import annotations

from app.tools.search.providers import (
    SearchProvider,
    SearchProviderConfig,
    SerpApiSearchProvider,
    SerperSearchProvider,
    build_search_provider,
)
from app.tools.search.schemas import SearchQuery, SearchResponse, SearchResult
from app.tools.search.tool import SearchTool

__all__ = [
    "SearchProvider",
    "SearchProviderConfig",
    "SerperSearchProvider",
    "SerpApiSearchProvider",
    "SearchTool",
    "SearchQuery",
    "SearchResponse",
    "SearchResult",
    "build_search_provider",
]