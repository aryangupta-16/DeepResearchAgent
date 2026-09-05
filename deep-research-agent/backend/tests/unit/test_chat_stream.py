"""Unit tests for Phase C streaming — SSE chat turns.

Covers the service event sequence (start → deltas → done), the non-streaming
provider fallback, mid-stream error handling, and grounded streaming with
citations — all against in-memory SQLite.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.chat.context import ChatDocumentSource
from app.chat.repository import ConversationRepository
from app.chat.schemas import ConversationCreate, MessageCreate
from app.chat.service import ChatSessionService
from app.common.exceptions import LLMProviderError
from app.infrastructure.database.models.conversation import ChatMessage, Conversation
from app.infrastructure.database.postgres import Base
from app.llm.base import LLMMessage, LLMResponse, LLMStreamEvent, LLMUsage
from app.workflows.chat.workflow import ChatWorkflow

GroundedSource = ChatDocumentSource(
    citation_key="C1",
    document_id="doc-1",
    document_name="lithium.pdf",
    page_number=3,
    excerpt="Nevada hosts ~1% of reserves.",
    score=0.8,
)


class StreamingFakeProvider:
    """Emits token deltas, then a terminal event with usage."""

    name = "fake-stream"

    def __init__(self, deltas: list[str], *, raise_after: int | None = None) -> None:
        self.deltas = deltas
        self.raise_after = raise_after
        self.received_messages: list[list[LLMMessage]] = []

    def supports_streaming(self) -> bool:
        return True

    async def generate_stream(  # noqa: RUF029
        self, messages: list[LLMMessage], **kwargs: object
    ):
        self.received_messages.append(messages)
        emitted = 0
        for delta in self.deltas:
            if self.raise_after is not None and emitted >= self.raise_after:
                raise LLMProviderError("stream exploded mid-flight")
            emitted += 1
            yield LLMStreamEvent(delta=delta)
        yield LLMStreamEvent(
            response=LLMResponse(
                content="".join(self.deltas),
                model="fake-stream-model",
                provider=self.name,
                usage=LLMUsage(prompt_tokens=7, completion_tokens=9, total_tokens=16),
            )
        )


class PlainFakeProvider:
    """No streaming capability: exercises the one-shot fallback path."""

    name = "fake-plain"

    def __init__(self, content: str = "whole reply") -> None:
        self.content = content
        self.received_messages: list[list[LLMMessage]] = []

    async def generate(  # noqa: RUF029
        self, messages: list[LLMMessage], **kwargs: object
    ) -> LLMResponse:
        self.received_messages.append(messages)
        return LLMResponse(
            content=self.content,
            model="fake-plain-model",
            provider=self.name,
            usage=LLMUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[Conversation.__table__, ChatMessage.__table__],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _service(session: AsyncSession, provider: object) -> ChatSessionService:
    return ChatSessionService(
        session=session,
        workflow=ChatWorkflow(provider=provider),  # type: ignore[arg-type]
    )


async def test_stream_turn_emits_full_event_sequence(db_session) -> None:
    provider = StreamingFakeProvider(["Nevada ", "leads ", "[C1]."])
    service = _service(db_session, provider)
    conv = await service.create_conversation(ConversationCreate())

    events = [
        event
        async for event in service.stream_turn(
            conv.id, MessageCreate(content="Where is lithium?")
        )
    ]

    assert [e["event"] for e in events] == ["start", "delta", "delta", "delta", "done"]
    assert events[0]["data"]["user_message_id"] >= 1
    assert "".join(e["data"]["text"] for e in events[1:-1]) == "Nevada leads [C1]."

    done = events[-1]["data"]
    assert done["role"] == "assistant"
    assert done["content"] == "Nevada leads [C1]."
    assert done["model"] == "fake-stream-model"
    assert done["prompt_tokens"] == 7
    assert done["citations"] == []  # no context offered -> no citations

    # Both turns persisted (query rows directly — the loaded Conversation's
    # relationship is cached in the identity map and does not refresh on commit).
    repo = ConversationRepository(db_session)
    persisted = await repo.list_messages(conv.id)
    assert [m.role for m in persisted] == ["user", "assistant"]
    assert persisted[-1].content == "Nevada leads [C1]."


async def test_stream_turn_falls_back_for_non_streaming_provider(db_session) -> None:
    provider = PlainFakeProvider("one shot reply")
    service = _service(db_session, provider)
    conv = await service.create_conversation(ConversationCreate())

    events = [
        event
        async for event in service.stream_turn(conv.id, MessageCreate(content="hello"))
    ]

    assert [e["event"] for e in events] == ["start", "delta", "done"]
    assert events[1]["data"]["text"] == "one shot reply"
    done = events[-1]["data"]
    assert done["content"] == "one shot reply"
    assert done["model"] == "fake-plain-model"
    assert done["prompt_tokens"] == 5


async def test_stream_turn_error_event_and_no_assistant_persisted(db_session) -> None:
    provider = StreamingFakeProvider(["partial ", "boom"], raise_after=1)
    service = _service(db_session, provider)
    conv = await service.create_conversation(ConversationCreate())

    events = [
        event
        async for event in service.stream_turn(conv.id, MessageCreate(content="hello"))
    ]

    assert [e["event"] for e in events] == ["start", "delta", "error"]
    assert events[-1]["data"]["code"] == "llm_provider_error"

    # The user turn survives; no assistant turn was persisted.
    repo = ConversationRepository(db_session)
    persisted = await repo.list_messages(conv.id)
    assert [m.role for m in persisted] == ["user"]


async def test_stream_turn_grounds_and_persists_citations(db_session) -> None:
    class _Ctx:
        async def retrieve(self, query: str, *, limit: int) -> list[ChatDocumentSource]:
            return [GroundedSource]

    provider = StreamingFakeProvider(["Per the document, Nevada leads [C1]."])
    service = ChatSessionService(
        session=db_session,
        workflow=ChatWorkflow(provider=provider),  # type: ignore[arg-type]
        context_provider=_Ctx(),  # type: ignore[arg-type]
    )
    conv = await service.create_conversation(
        ConversationCreate(context_mode="documents")
    )

    events = [
        event
        async for event in service.stream_turn(
            conv.id, MessageCreate(content="Where is lithium?")
        )
    ]

    # The grounded system prompt (with the excerpt) reached the provider.
    system_prompt = provider.received_messages[0][0].content
    assert "lithium.pdf" in system_prompt

    done = events[-1]["data"]
    assert [c["citation_key"] for c in done["citations"]] == ["C1"]
    assert done["citations"][0]["document_name"] == "lithium.pdf"


async def test_stream_turn_rejects_blank_before_streaming(db_session) -> None:
    service = _service(db_session, PlainFakeProvider())
    conv = await service.create_conversation(ConversationCreate())
    with pytest.raises(Exception, match="no usable text"):
        _ = [
            event
            async for event in service.stream_turn(
                conv.id, MessageCreate.model_construct(content="   ")
            )
        ]
    # Nothing was persisted for the rejected turn.
    assert await ConversationRepository(db_session).count_messages(conv.id) == 0