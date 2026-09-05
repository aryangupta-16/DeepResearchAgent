"""Unit tests for the chat session domain (Phase C1).

Covers schema validation, history windowing, auto-titling, and usage mapping
against an in-memory SQLite database. PostgreSQL-backed API behaviour lives in
the integration suite.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.chat.repository import ConversationRepository
from app.chat.schemas import ConversationCreate, MessageCreate
from app.chat.service import ChatSessionService
from app.common.exceptions import ConversationNotFoundError, ValidationError
from app.infrastructure.database.models.conversation import ChatMessage, Conversation
from app.infrastructure.database.postgres import Base
from app.llm.base import LLMMessage, LLMResponse, LLMUsage
from app.workflows.chat.workflow import ChatWorkflow

# ---- Schema validation ----


def test_message_create_rejects_blank_content() -> None:
    with pytest.raises(PydanticValidationError):
        MessageCreate(content="   ")


def test_message_create_rejects_oversized_content() -> None:
    with pytest.raises(PydanticValidationError):
        MessageCreate(content="x" * 8001)


def test_message_create_strips_whitespace() -> None:
    assert MessageCreate(content="  hello  ").content == "hello"


def test_conversation_title_is_bounded() -> None:
    with pytest.raises(PydanticValidationError):
        ConversationCreate(title="x" * 201)


# ---- Fakes / fixtures ----


class RecordingProvider:
    """Captures the message lists it receives; returns a canned reply."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []
        self._n = 0

    async def generate(
        self, messages: list[LLMMessage], **kwargs: object
    ) -> LLMResponse:
        self.calls.append(messages)
        self._n += 1
        return LLMResponse(
            content=f"reply {self._n}",
            model="fake-model",
            provider=self.name,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _record):  # pragma: no cover - sqlite pragma
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        # Only the chat tables: the full metadata includes JSONB columns that
        # SQLite cannot compile (this suite exercises conversation logic only).
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


@pytest.fixture
def provider() -> RecordingProvider:
    return RecordingProvider()


def _service(
    session: AsyncSession, provider: RecordingProvider, *, window: int = 20
) -> ChatSessionService:
    return ChatSessionService(
        session=session,
        workflow=ChatWorkflow(provider=provider),
        history_window=window,
    )


# ---- Service behaviour ----

def _uuid() -> object:
    from uuid import uuid4

    return uuid4()


async def test_create_and_get_conversation(db_session, provider) -> None:
    service = _service(db_session, provider)
    created = await service.create_conversation(ConversationCreate(title="Test"))
    fetched = await service.get_conversation(created.id)
    assert fetched.id == created.id
    assert fetched.title == "Test"


async def test_get_missing_conversation_raises(db_session, provider) -> None:
    service = _service(db_session, provider)
    with pytest.raises(ConversationNotFoundError):
        await service.get_conversation(_uuid())


async def test_send_message_persists_turn_with_usage(db_session, provider) -> None:
    service = _service(db_session, provider)
    conv = await service.create_conversation(ConversationCreate())
    reply = await service.send_message(conv.id, MessageCreate(content="What is RAG?"))

    assert reply.role == "assistant"
    assert reply.content == "reply 1"
    assert reply.model == "fake-model"
    assert reply.provider == "fake"
    assert reply.prompt_tokens == 10
    assert reply.completion_tokens == 5

    messages = await ConversationRepository(db_session).list_messages(conv.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "What is RAG?"

    # Conversation auto-titled from the first user message.
    refreshed = await service.get_conversation(conv.id)
    assert refreshed.title == "What is RAG?"


async def test_send_message_replays_history_in_prompt(
    db_session, provider
) -> None:
    service = _service(db_session, provider)
    conv = await service.create_conversation(ConversationCreate())
    await service.send_message(conv.id, MessageCreate(content="first question"))
    await service.send_message(conv.id, MessageCreate(content="second question"))

    # Second call must carry: system + (user, assistant) + new user message.
    second_call = provider.calls[1]
    assert second_call[0].role == "system"
    assert [m.role for m in second_call[1:]] == ["user", "assistant", "user"]
    assert second_call[1].content == "first question"
    assert second_call[-1].content == "second question"


async def test_history_window_bounds_prompt(db_session, provider) -> None:
    service = _service(db_session, provider, window=4)
    conv = await service.create_conversation(ConversationCreate())
    for i in range(6):
        await service.send_message(conv.id, MessageCreate(content=f"question {i}"))

    # window=4 -> the last 4 persisted messages (the two most recent prior
    # turns: question 3 + question 4) before the new turn.
    last_call = provider.calls[-1]
    roles = [m.role for m in last_call[1:]]
    assert roles == ["user", "assistant", "user", "assistant", "user"]
    assert last_call[1].content == "question 3"
    assert last_call[2].content == "reply 4"
    assert last_call[3].content == "question 4"
    assert last_call[4].content == "reply 5"
    assert last_call[-1].content == "question 5"


async def test_send_message_rejects_blank(db_session, provider) -> None:
    service = _service(db_session, provider)
    conv = await service.create_conversation(ConversationCreate())
    # Schema layer rejects blank/whitespace-only content outright.
    with pytest.raises(PydanticValidationError):
        MessageCreate(content="   ")
    # Defense in depth: the service guard also refuses empty text (e.g. a
    # payload constructed bypassing validation).
    with pytest.raises(ValidationError):
        await service.send_message(
            conv.id, MessageCreate.model_construct(content="   ")
        )


async def test_delete_conversation_cascades_messages(db_session, provider) -> None:
    service = _service(db_session, provider)
    repo = ConversationRepository(db_session)
    conv = await service.create_conversation(ConversationCreate())
    await service.send_message(conv.id, MessageCreate(content="hello"))
    assert await repo.count_messages(conv.id) == 2

    await service.delete_conversation(conv.id)
    assert await repo.get(conv.id) is None
    assert await repo.count_messages(conv.id) == 0


async def test_delete_missing_conversation_raises(db_session, provider) -> None:
    service = _service(db_session, provider)
    with pytest.raises(ConversationNotFoundError):
        await service.delete_conversation(_uuid())


async def test_title_derivation_bounded_and_first_line(db_session) -> None:
    assert ChatSessionService._derive_title("  first line\nsecond line  ") == "first line"
    long = ChatSessionService._derive_title("x" * 200)
    assert len(long) <= 80
    assert long.endswith("…")


def test_models_are_registered_on_base() -> None:
    assert Conversation.__tablename__ == "conversations"
    assert ChatMessage.__tablename__ == "chat_messages"
