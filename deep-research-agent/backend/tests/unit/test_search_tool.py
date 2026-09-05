"""Unit tests for the search tool + Serper provider (mocked transport, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.common.exceptions import SearchError
from app.tools.search.providers import (
    SearchProviderConfig,
    SerperSearchProvider,
)
from app.tools.search.schemas import SearchQuery
from app.tools.search.tool import SearchTool


def _serper(payload: dict, *, status: int = 200):
    def _handler(request: httpx.Request) -> httpx.Response:
        body = payload if status < 300 else {"error": "nope"}
        return httpx.Response(status, json=body, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


async def test_search_maps_serper_results() -> None:
    payload = {
        "organic": [
            {"title": "Alpha", "link": "https://www.example.com/a", "snippet": "s1"},
            {"title": "Beta", "link": "https://other.org/b", "snippet": "s2"},
        ]
    }
    provider = SerperSearchProvider(
        SearchProviderConfig(api_key="k"), client=_serper(payload)
    )
    tool = SearchTool(provider)

    response = await tool.execute(SearchQuery(query="robots", limit=5))

    assert response.query == "robots"
    assert len(response.results) == 2
    assert response.results[0].domain == "example.com"
    assert response.results[1].domain == "other.org"


async def test_search_empty_results() -> None:
    provider = SerperSearchProvider(
        SearchProviderConfig(api_key="k"), client=_serper({"organic": []})
    )
    tool = SearchTool(provider)

    response = await tool.execute({"query": "nothing"})

    assert response.results == []


async def test_search_error_on_4xx() -> None:
    provider = SerperSearchProvider(
        SearchProviderConfig(api_key="k"), client=_serper({}, status=401)
    )
    tool = SearchTool(provider)

    with pytest.raises(SearchError):
        await tool.execute(SearchQuery(query="robots"))


async def test_search_requires_api_key() -> None:
    provider = SerperSearchProvider(
        SearchProviderConfig(api_key=""), client=httpx.AsyncClient()
    )
    tool = SearchTool(provider)

    with pytest.raises(SearchError):
        await tool.execute({"query": "robots"})


async def test_search_tool_maps_dict_input() -> None:
    provider = SerperSearchProvider(
        SearchProviderConfig(api_key="k"), client=_serper({"organic": []})
    )
    response = await SearchTool(provider).execute({"query": "q", "limit": 3})
    assert response.query == "q"