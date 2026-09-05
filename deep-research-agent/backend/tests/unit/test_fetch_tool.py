"""Unit tests for the fetch tool (mocked transport, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.common.exceptions import FetchError
from app.tools.browser.schemas import FetchInput
from app.tools.browser.tool import FetchTool

HTML_PAGE = """<!doctype html>
<html><head><title>Test Page</title></head><body>
<h1>Hello</h1>
<p>Readable content here.</p>
<script>document.write("noise");</script>
<style>.x { color: red; }</style>
</body></html>
"""

STANDARD_HEADERS = {"content-type": "text/html; charset=utf-8"}


def _client_for(
    *,
    status: int = 200,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    content_type: str | None = None,
    raise_exc: Exception | None = None,
) -> httpx.AsyncClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        if raise_exc is not None:
            raise raise_exc
        hdrs = dict(STANDARD_HEADERS)
        if content_type is not None:
            hdrs["content-type"] = content_type
        if headers:
            hdrs.update(headers)
        return httpx.Response(
            status,
            content=body or HTML_PAGE.encode(),
            headers=hdrs,
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


async def test_fetch_success_extracts_readable_text() -> None:
    tool = FetchTool(client=_client_for())
    doc = await tool.execute(FetchInput(url="https://example.com/page"))

    assert doc.status_code == 200
    assert doc.title == "Test Page"
    assert "Readable content here" in doc.content
    assert "noise" not in doc.content


async def test_fetch_http_error() -> None:
    tool = FetchTool(client=_client_for(status=404))
    with pytest.raises(FetchError):
        await tool.execute(FetchInput(url="https://example.com/404"))


async def test_fetch_timeout() -> None:
    tool = FetchTool(client=_client_for(raise_exc=httpx.ReadTimeout("slow")))
    with pytest.raises(FetchError):
        await tool.execute(FetchInput(url="https://example.com/"))


async def test_fetch_unsupported_content_type() -> None:
    tool = FetchTool(client=_client_for(content_type="image/png"))
    with pytest.raises(FetchError):
        await tool.execute(FetchInput(url="https://example.com/pic"))


async def test_fetch_oversized_response() -> None:
    tool = FetchTool(client=_client_for(body=b"x" * 60_000))
    with pytest.raises(FetchError):
        await tool.execute(FetchInput(url="https://example.com/big", max_bytes=1_024))


async def test_fetch_rejects_unsupported_scheme() -> None:
    tool = FetchTool(client=_client_for())
    with pytest.raises(FetchError):
        await tool.execute(FetchInput(url="ftp://example.com/file"))