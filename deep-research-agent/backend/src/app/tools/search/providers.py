"""Search provider backends.

A :class:`SearchProvider` performs the raw request against a search backend and
returns normalized results. The :class:`SearchTool` wraps a provider and owns
error mapping (V1: no retries). Agents depend on the :class:`SearchTool`, never on
a provider directly, so backends can be swapped via factory wiring.

The provider selected for V1 is **Serper** (simple Google-search JSON API). The
rest of the application only knows about :class:`SearchProvider` + the normalized
schemas — no vendor shapes escape this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.common.exceptions import SearchError
from app.tools.search.schemas import SearchQuery, SearchResponse, SearchResult


class _TransientSearchError(SearchError):
    """Internal marker for retryable search failures (upstream 5xx, timeouts, network errors).

    A subclass of :class:`SearchError`, so existing callers that catch the public
    error stay unaffected; only the retry decorator observes this subtype.
"""


#: Transient search failures retry up to 3 times with exponential backoff + jitter.
_SEARCH_RETRY_ATTEMPTS = 3
_SEARCH_RETRY_MIN_WAIT =   0.5
_SEARCH_RETRY_MAX_WAIT =   10.0


def _with_search_retry(func):
    """Retry transient (retryable) search failures."""

    @wraps(func)
    @retry(
        retry=retry_if_exception_type(_TransientSearchError),
        wait=wait_exponential_jitter(initial=_SEARCH_RETRY_MIN_WAIT, max=_SEARCH_RETRY_MAX_WAIT),
        stop=stop_after_attempt(_SEARCH_RETRY_ATTEMPTS),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def wrapper(*args: object, **kwargs: object):
        return await func(*args, **kwargs)

    return wrapper


if TYPE_CHECKING:  # pragma: no cover
    from app.config.settings import Settings

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_ENDPOINT = "https://google.serper.dev/search"
_MAX_SEARCH_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MB


class SearchProvider(Protocol):
    """Contract for a search backend implementation."""

    name: str

    async def search(self, query: str, *, limit: int = 5) -> SearchResponse:
        """Return normalized search results for ``query``."""
        ...


@dataclass(frozen=True)
class SearchProviderConfig:
    """Configuration for a search provider (all optional; defaults safe)."""

    api_key: str = ""
    endpoint: str = DEFAULT_SEARCH_ENDPOINT
    timeout_seconds: float = 15.0


def _domain(url: str) -> str:
    """Best-effort domain extraction from a URL."""
    netloc = urlparse(url).netloc or ""
    return netloc[4:] if netloc.lower().startswith("www.") else netloc.lower()


class SerperSearchProvider:
    """Search provider backed by the Serper Search API.

    Serper returns Google results in a simple JSON shape; we translate the
    ``organic`` array into our normalized :class:`SearchResult` type. A plain
    ``X-API-KEY`` header authenticates the request.
    """

    name = "serper"

    def __init__(
        self, config: SearchProviderConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._client = client

    @_with_search_retry
    async def search(self, query: str, *, limit: int = 5) -> SearchResponse:
        if not self._config.api_key:
            raise SearchError("search_api_key is required for the Serper provider.")

        url = self._config.endpoint
        headers = {
            "X-API-KEY": self._config.api_key,
            "Content-Type": "application/json",
        }
        payload = {"q": query, "num": min(limit, 10)}

        if self._client is not None:
            response = await self._client.post(url, json=payload, headers=headers)
        else:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._config.timeout_seconds),
                    follow_redirects=True,
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise _TransientSearchError("Search request timed out.") from exc
            except httpx.HTTPError as exc:
                raise _TransientSearchError(
                    "Search request failed at the network layer."
                ) from exc

        if response.is_error:
            if 400 <= response.status_code < 500:
                raise SearchError(
                    f"Search provider rejected the request (HTTP {response.status_code})."
                )
            raise _TransientSearchError(
                f"Search provider upstream error (HTTP {response.status_code})."
            )

        if len(response.content) > _MAX_SEARCH_RESPONSE_BYTES:
            raise SearchError("Search response exceeded the maximum allowed size.")

        data = response.json()
        organic = data.get("organic", [])
        results: list[SearchResult] = []
        for item in organic[:limit]:
            raw_url = str(item.get("link", ""))
            if not raw_url:
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title", "")),
                    url=raw_url,
                    snippet=str(item.get("snippet", item.get("description", ""))),
                    domain=_domain(raw_url),
                )
            )
        return SearchResponse(query=query, results=results, total=len(results))


class SerpApiSearchProvider:
    """Search provider backed by the SerpApi Google Search API.

    SerpApi authenticates with an ``api_key`` query parameter and returns results
    in the ``organic_results`` array (each with ``title``/``link``/``snippet``).
    """

    name = "serpapi"

    DEFAULT_ENDPOINT = "https://serpapi.com/search.json"

    def __init__(
        self, config: SearchProviderConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._client = client

    @_with_search_retry
    async def search(self, query: str, *, limit: int = 5) -> SearchResponse:
        if not self._config.api_key:
            raise SearchError("search_api_key is required for the SerpApi provider.")

        url = self._config.endpoint or self.DEFAULT_ENDPOINT
        params = {
            "engine": "google",
            "q": query,
            "num": min(limit, 10),
            "api_key": self._config.api_key,
        }

        if self._client is not None:
            response = await self._client.get(url, params=params)
        else:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._config.timeout_seconds),
                    follow_redirects=True,
                ) as client:
                    response = await client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise _TransientSearchError("Search request timed out.") from exc
            except httpx.HTTPError as exc:
                raise _TransientSearchError(
                    "Search request failed at the network layer."
                ) from exc

        if response.is_error:
            if 400 <= response.status_code < 500:
                raise SearchError(
                    f"Search provider rejected the request (HTTP {response.status_code})."
                )
            raise _TransientSearchError(
                f"Search provider upstream error (HTTP {response.status_code})."
            )

        if len(response.content) > _MAX_SEARCH_RESPONSE_BYTES:
            raise SearchError("Search response exceeded the maximum allowed size.")

        data = response.json()
        # SerpApi returns an explicit error indicator for invalid keys.
        if data.get("error"):
            raise SearchError(f"Search provider error: {data['error']}")

        organic = data.get("organic_results", [])
        results: list[SearchResult] = []
        for item in organic[:limit]:
            raw_url = str(item.get("link", ""))
            if not raw_url:
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title", "")),
                    url=raw_url,
                    snippet=str(item.get("snippet", item.get("description", ""))),
                    domain=_domain(raw_url),
                )
            )
        return SearchResponse(query=query, results=results, total=len(results))


def build_search_provider(settings: Settings) -> SearchProvider:
    """Build the configured search provider from application settings.

    Raises:
        SearchError: if the configured provider is unsupported or missing an API key.
    """
    provider_name = (settings.search_provider or "").strip().lower()
    if not provider_name:
        raise SearchError(
            "Search is not configured (SEARCH_PROVIDER is empty)."
        )
    if not settings.search_api_key:
        raise SearchError("Search is misconfigured (SEARCH_API_KEY is empty).")

    config = SearchProviderConfig(
        api_key=settings.search_api_key,
        endpoint=settings.search_endpoint or "",
        timeout_seconds=settings.fetch_timeout_seconds,
    )
    if provider_name == "serper":
        if not config.endpoint:
            config = SearchProviderConfig(
                api_key=config.api_key,
                endpoint=DEFAULT_SEARCH_ENDPOINT,
                timeout_seconds=config.timeout_seconds,
            )
        return SerperSearchProvider(config)
    if provider_name == "serpapi":
        return SerpApiSearchProvider(config)
    raise SearchError(f"Unsupported search provider: {provider_name!r}.")


__all__ = [
    "DEFAULT_SEARCH_ENDPOINT",
    "SearchProvider",
    "SearchProviderConfig",
    "SerperSearchProvider",
    "SerpApiSearchProvider",
    "SearchQuery",
    "SearchResponse",
    "SearchResult",
    "build_search_provider",
]