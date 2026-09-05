"""Search tool.

A deterministic tool that wraps a :class:`SearchProvider`. Agents depend on the
tool — not on the vendor SDK — so the backend can be swapped without touching
agent code (see ``build_search_provider``).
"""

from __future__ import annotations

import logging

from app.common.exceptions import SearchError
from app.observability.metrics import SEARCH_CALLS
from app.tools.search.providers import SearchProvider
from app.tools.search.schemas import SearchQuery, SearchResponse

logger = logging.getLogger(__name__)


class SearchTool:
    """Deterministic web search operation over a configured provider."""

    name = "search"
    description = (
        "Query a web search engine and return ranked search results "
        "(title, url, snippet, domain)."
    )

    def __init__(self, provider: SearchProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def execute(self, input_data: object) -> SearchResponse:
        """Run ``input_data`` (a :class:`SearchQuery` or dict) through the provider."""
        query = input_data if isinstance(input_data, SearchQuery) else SearchQuery.model_validate(
            input_data
        )
        try:
            response = await self._provider.search(query.query, limit=query.limit)
        except SearchError:
            SEARCH_CALLS.labels(outcome="error").inc()
            raise
        except Exception as exc:  # pragma: no cover - defensive translation
            raise SearchError(f"Search failed unexpectedly: {exc}") from exc
        SEARCH_CALLS.labels(outcome="ok").inc()

        logger.info(
            "Search completed provider=%s query=%r results=%d",
            self._provider.name,
            query.query,
            len(response.results),
        )
        return response


__all__ = ["SearchTool"]