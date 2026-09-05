"""API tests for the conversation endpoints (Phase C1).

Exercises the full HTTP surface against the isolated PostgreSQL test database
(schema via ``Base.metadata.create_all`` in the session fixture) with the LLM
provider faked at the dependency boundary. Exit criteria covered here: a
conversation survives multiple requests (durable across restarts by virtue of
being committed rows), quick answers return without any deep-research job, and
usage metadata is persisted per assistant message.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from app.api.dependencies import DbSession, get_conversation_service
from app.chat.service import ChatSessionService
from app.common.exceptions import LLMProviderError
from app.config.settings import get_settings
from app.llm.base import LLMResponse, LLMStreamEvent, LLMUsage
from app.main import app
from app.workflows.chat.workflow import ChatWorkflow
from tests.conftest import FakeLLMProvider


@pytest.fixture
async def http_client(
    fake_llm_provider: FakeLLMProvider,
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client with the chat session provider faked at the dependency
    boundary. The override mirrors the real dependency signature (``DbSession``
    is a dependency-injected annotation), so FastAPI still supplies a
    request-scoped DB session."""

    def _build(session: DbSession) -> ChatSessionService:
        return ChatSessionService(
            session=session,
            provider=fake_llm_provider,  # type: ignore[arg-type]
            history_window=get_settings().chat_history_window,
        )

    app.dependency_overrides[get_conversation_service] = _build
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_conversation_service, None)


def _failing_override(failing: FakeLLMProvider) -> Callable[..., ChatSessionService]:
    """Override that injects a provider which raises on every generate call."""

    def _build(session: DbSession) -> ChatSessionService:
        return ChatSessionService(session=session, provider=failing)  # type: ignore[arg-type]

    return _build


def _grounded_override(
    provider: object,
    context_sources: list,
) -> Callable[..., ChatSessionService]:
    """Override injecting a fake RAG context provider (Phase C2)."""

    class _FakeContext:
        def __init__(self, sources: list) -> None:
            self.sources = sources

        async def retrieve(self, query: str, *, limit: int) -> list:
            return self.sources

    def _build(session: DbSession) -> ChatSessionService:
        return ChatSessionService(
            session=session,
            provider=provider,  # type: ignore[arg-type]
            context_provider=_FakeContext(context_sources),  # type: ignore[arg-type]
            retrieval_top_k=2,
        )

    return _build


def _missing_id() -> str:
    import uuid

    return str(uuid.uuid4())


async def test_conversation_lifecycle(http_client: httpx.AsyncClient) -> None:
    # Create.
    response = await http_client.post(
        "/api/conversations", json={"title": "Quick questions"}
    )
    assert response.status_code == 201
    conversation = response.json()
    conversation_id = conversation["id"]
    assert conversation["title"] == "Quick questions"

    # List includes it.
    response = await http_client.get("/api/conversations")
    assert response.status_code == 200
    assert any(c["id"] == conversation_id for c in response.json()["conversations"])

    # Send a turn -> assistant reply with usage metadata.
    response = await http_client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "Summarize RAG in one sentence."},
    )
    assert response.status_code == 200
    assistant = response.json()
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "fake reply"
    assert assistant["model"] == "fake-model"
    assert assistant["prompt_tokens"] == 3
    assert assistant["completion_tokens"] == 4

    # Detail carries the full persisted thread (user + assistant).
    response = await http_client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 200
    detail = response.json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]

    # Delete -> 204, then 404 on subsequent access.
    response = await http_client.delete(f"/api/conversations/{conversation_id}")
    assert response.status_code == 204
    response = await http_client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "conversation_not_found"


async def test_conversation_survives_across_requests_and_auto_titles(
    http_client: httpx.AsyncClient,
) -> None:
    """Committed rows are durable: each request uses a fresh DB session, so a
    conversation created in one request is visible (and updated) in the next —
    the same property that makes it survive a server restart."""
    response = await http_client.post("/api/conversations", json={})
    conversation_id = response.json()["id"]
    assert response.json()["title"] is None

    await http_client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "What causes the northern lights?"},
    )
    response = await http_client.get(f"/api/conversations/{conversation_id}")
    assert response.json()["title"] == "What causes the northern lights?"


async def test_message_validation_and_unknown_conversation(
    http_client: httpx.AsyncClient,
) -> None:
    response = await http_client.post(
        "/api/conversations", json={"title": "validation"}
    )
    conversation_id = response.json()["id"]

    # Blank / missing content -> 422.
    assert (
        await http_client.post(
            f"/api/conversations/{conversation_id}/messages", json={"content": "  "}
        )
    ).status_code == 422
    assert (
        await http_client.post(
            f"/api/conversations/{conversation_id}/messages", json={}
        )
    ).status_code == 422

    # Unknown conversation -> 404 with domain code.
    response = await http_client.post(
        f"/api/conversations/{_missing_id()}/messages", json={"content": "hi"}
    )
    assert response.status_code == 404
    assert response.json()["code"] == "conversation_not_found"

    # Malformed id -> 422 (path UUID parsing).
    response = await http_client.post(
        "/api/conversations/not-a-uuid/messages", json={"content": "hi"}
    )
    assert response.status_code == 422


async def test_provider_error_maps_to_502() -> None:
    failing = FakeLLMProvider(raise_error=LLMProviderError("boom"))
    app.dependency_overrides[get_conversation_service] = _failing_override(failing)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            created = await client.post("/api/conversations", json={})
            conversation_id = created.json()["id"]
            response = await client.post(
                f"/api/conversations/{conversation_id}/messages",
                json={"content": "hello"},
            )
            assert response.status_code == 502
            assert response.json()["code"] == "llm_provider_error"
        finally:
            app.dependency_overrides.pop(get_conversation_service, None)


class StreamingFakeLLMProvider:
    """Deterministic in-process provider that streams token deltas."""

    name = "fake-stream"

    def __init__(self, deltas: list[str]) -> None:
        self.deltas = deltas

    def supports_streaming(self) -> bool:
        return True

    async def generate_stream(  # noqa: RUF029
        self, messages: list, **kwargs: object
    ):
        for delta in self.deltas:
            yield LLMStreamEvent(delta=delta)
        yield LLMStreamEvent(
            response=LLMResponse(
                content="".join(self.deltas),
                model="stream-model",
                provider=self.name,
                usage=LLMUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
            )
        )


def _streaming_override(streaming: StreamingFakeLLMProvider) -> Callable[..., ChatSessionService]:
    """Typed override so FastAPI injects the DB session (not a query param)."""

    def _build(session: DbSession) -> ChatSessionService:
        return ChatSessionService(
            session=session, workflow=ChatWorkflow(provider=streaming)  # type: ignore[arg-type]
        )

    return _build


async def test_stream_endpoint_emits_sse_frames() -> None:
    """POST /messages/stream returns progress frames then the full reply."""
    streaming = StreamingFakeLLMProvider(["Hello", " there", "!"])
    app.dependency_overrides[get_conversation_service] = _streaming_override(streaming)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            created = await client.post("/api/conversations", json={})
            conversation_id = created.json()["id"]

            body = ""
            async with client.stream(
                "POST",
                f"/api/conversations/{conversation_id}/messages/stream",
                json={"content": "hi"},
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith(
                    "text/event-stream"
                )
                async for chunk in response.aiter_text():
                    body += chunk

            assert "event: start" in body
            assert 'event: delta\ndata: {"text": "Hello"}' in body
            assert 'event: delta\ndata: {"text": " there"}' in body
            assert 'event: delta\ndata: {"text": "!"}' in body
            assert "event: done" in body
            assert '"content": "Hello there!"' in body
            assert '"model": "stream-model"' in body
        finally:
            app.dependency_overrides.pop(get_conversation_service, None)


async def test_create_and_patch_context_mode(http_client: httpx.AsyncClient) -> None:
    # Default is plain chat.
    created = await http_client.post("/api/conversations", json={})
    assert created.status_code == 201
    assert created.json()["context_mode"] == "none"

    # Documents-grounded from creation.
    created = await http_client.post(
        "/api/conversations", json={"context_mode": "documents"}
    )
    assert created.json()["context_mode"] == "documents"

    # Toggle an existing conversation off/on via PATCH.
    response = await http_client.patch(
        f"/api/conversations/{created.json()['id']}",
        json={"context_mode": "none"},
    )
    assert response.status_code == 200
    assert response.json()["context_mode"] == "none"

    response = await http_client.patch(
        f"/api/conversations/{created.json()['id']}",
        json={"context_mode": "documents"},
    )
    assert response.status_code == 200
    assert response.json()["context_mode"] == "documents"

    # Invalid mode -> 422.
    response = await http_client.patch(
        f"/api/conversations/{created.json()['id']}",
        json={"context_mode": "articles"},
    )
    assert response.status_code == 422


async def test_documents_mode_returns_citations(
    fake_llm_provider: FakeLLMProvider,
) -> None:
    """A documents-grounded turn returns structured citations that map to the
    offered sources — the same evidence system the report UI renders."""
    fake_llm_provider.content = (
        "Nevada holds about 1% of reserves [C2] with caveats [C1]. "
        "Unsupported [C9] is dropped."
    )
    from app.chat.context import ChatDocumentSource

    sources = [
        ChatDocumentSource(
            citation_key="C1",
            document_id="doc-a",
            document_name="caveats.pdf",
            page_number=2,
            excerpt="Estimates vary by agency.",
            score=0.4,
        ),
        ChatDocumentSource(
            citation_key="C2",
            document_id="doc-b",
            document_name="lithium.pdf",
            page_number=None,
            excerpt="Nevada holds ~1% of reserves.",
            score=0.9,
        ),
    ]
    app.dependency_overrides[get_conversation_service] = _grounded_override(
        fake_llm_provider, sources
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            created = await client.post(
                "/api/conversations", json={"context_mode": "documents"}
            )
            conversation_id = created.json()["id"]
            response = await client.post(
                f"/api/conversations/{conversation_id}/messages",
                json={"content": "What do the documents say?"},
            )
            assert response.status_code == 200
            body = response.json()
            assert [c["citation_key"] for c in body["citations"]] == ["C2", "C1"]
            assert body["citations"][0]["document_name"] == "lithium.pdf"
            assert body["citations"][0]["page_number"] is None
            assert body["citations"][1]["page_number"] == 2
        finally:
            app.dependency_overrides.pop(get_conversation_service, None)