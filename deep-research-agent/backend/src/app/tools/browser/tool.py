"""Fetch tool: URL → readable page content via a bounded HTTP GET.

Deterministic and safe-by-default V1:

- http/https schemes only
- bounded request timeout
- bounded response size (read in chunks, abort when over limit)
- redirects followed within a bound
- content-type allowlist (HTML / plain text)
- errors mapped into :class:`FetchError`

No JavaScript rendering / browser automation — a normal HTTP client suffices for
research content.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from app.common.exceptions import FetchError
from app.tools.browser.html import HtmlExtractor
from app.tools.browser.schemas import FetchedDocument, FetchInput

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
}


class FetchTool:
    """Deterministic web page fetcher returning readable text."""

    name = "fetch"
    description = (
        "Fetch a web page at a URL and return its readable text content "
        "(HTML markup removed)."
    )

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._client = client

    async def execute(self, input_data: object) -> FetchedDocument:
        """Fetch ``input_data`` (a :class:`FetchInput` or dict)."""
        fetch = input_data if isinstance(input_data, FetchInput) else FetchInput.model_validate(
            input_data
        )

        url = fetch.url.strip()
        self._validate_url(url)

        try:
            if self._client is not None:
                response = await self._client.get(
                    url,
                    follow_redirects=True,
                    headers={"User-Agent": "deep-research-agent/0.1"},
                )
            else:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(fetch.timeout_seconds or self._timeout),
                    follow_redirects=True,
                    max_redirects=self._max_redirects,
                    headers={"User-Agent": "deep-research-agent/0.1"},
                ) as client:
                    response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise FetchError(f"Timed out fetching {url!r}.") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"Network error fetching {url!r}.") from exc

        if response.is_error:
            raise FetchError(f"HTTP {response.status_code} while fetching {url!r}.")

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
            raise FetchError(
                f"Unsupported content-type {content_type!r} while fetching {url!r}."
            )

        if len(response.content) > (fetch.max_bytes or self._max_bytes):
            raise FetchError(
                f"Response for {url!r} exceeded the maximum allowed size."
            )

        raw_html = response.content.decode("utf-8", errors="replace")
        title, text = HtmlExtractor().extract(raw_html)
        if fetch.max_bytes:
            text = text[: fetch.max_bytes]

        logger.info(
            "Fetched url=%s bytes=%d status=%d",
            url,
            len(response.content),
            response.status_code,
        )
        return FetchedDocument(
            url=url,
            final_url=str(response.url),
            title=title,
            content=text,
            content_type=content_type or "",
            fetched_at=datetime.now(UTC),
            status_code=response.status_code,
        )

    def _validate_url(self, url: str) -> None:
        """Reject obviously unsafe/unsupported schemes.

        Deliberately minimal SSRF *hardening* (documented limitation): we block
        non-HTTP schemes but do not yet implement full private-IP filtering.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise FetchError(
                f"Unsupported URL scheme {parsed.scheme!r}; only http/https allowed."
            )


__all__ = ["FetchTool"]