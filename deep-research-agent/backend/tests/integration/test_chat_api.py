"""API tests for the chat endpoint.

The LLM provider is mocked at the service boundary via :func:`get_chat_service`
dependency override, so no API key or real provider is required.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from app.api.dependencies import get_chat_service
from app.main import app
from app.workflows.chat.service import ChatService


def _override_chat(provider: object) -> None:
    app.dependency_overrides[get_chat_service] = lambda: ChatService(provider=provider)  # type: ignore[arg-type]


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_chat_service, None)


async def test_chat_returns_200_with_mapped_response(
    http_client: httpx.AsyncClient,
    fake_llm_provider: object,
) -> None:
    _override_chat(fake_llm_provider)
    response = await http_client.post("/api/chat", json={"message": "Explain RAG"})

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "fake reply"
    assert body["model"] == "fake-model"
    assert body["provider"] == "fake"
    assert body["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }


async def test_chat_rejects_blank_and_missing_message(
    http_client: httpx.AsyncClient,
    fake_llm_provider: object,
) -> None:
    _override_chat(fake_llm_provider)
    response = await http_client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 422

    response = await http_client.post("/api/chat", json={})
    assert response.status_code == 422


async def test_chat_provider_error_maps_to_502(
    http_client: httpx.AsyncClient,
    failing_llm_provider: object,
) -> None:
    _override_chat(failing_llm_provider)
    response = await http_client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 502
    assert response.json()["code"] == "llm_provider_error"


async def test_chat_requires_provider_configuration(
    http_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No override: the real dependency reaches the factory. Force an unconfigured
    # provider so the test is hermetic regardless of the local `.env`.
    from app.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "llm_provider", "")
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    app.dependency_overrides.pop(get_chat_service, None)
    response = await http_client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 503
    assert response.json()["code"] == "llm_not_configured"