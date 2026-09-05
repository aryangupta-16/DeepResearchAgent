"""Unit tests for Phase C2 — document-grounded chat context.

Covers the deterministic citation contract ([C#] marker extraction), the
grounded system-prompt builder (guardrail-wrapped context block), and the
service's grounding flow with a fake retrieval provider (SQLite-backed).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.chat.citations import extract_citations
from app.chat.context import ChatDocumentSource, build_grounded_system_prompt
from app.chat.schemas import ConversationCreate, ConversationUpdate, MessageCreate
from app.chat.service import ChatSessionService
from app.common.exceptions import ValidationError
from app.guardrails.content import UNTRUSTED_BLOCK_START
from app.infrastructure.database.models.conversation import ChatMessage, Conversation
from app.infrastructure.database.postgres import Base
from app.llm.base import LLMMessage, LLMResponse, LLMUsage
from app.workflows.chat.prompts import CHAT_SYSTEM_PROMPT
from app.workflows.chat.workflow import ChatWorkflow

SRC1 = ChatDocumentSource(
    citation_key="C1",
    document_id="doc-1",
    document_name="Nevada lithium report.pdf",
    page_number=3,
    excerpt="Nevada hosts roughly 1% of the world's lithium reserves.",
    score=0.81,
)
SRC2 = ChatDocumentSource(
    citation_key="C2",
    document_id="doc-2",
    document_name="EV battery 2030.pdf",
    page_number=12,
    excerpt="Solid-state cells may halve pack cost by 2030.",
    score=0.66,
)
SRC3 = ChatDocumentSource(
    citation_key="C3",
    document_id="doc-3",
    document_name="untitled.pdf",
    page_number=None,
    excerpt="Caveat: reserve estimates vary by agency.",
    score=0.4,
)

# ---- Citation extraction ----


def test_extract_citations_picks_markers_in_first_seen_order() -> None:
    citations = extract_citations(
        "Nevada leads [C1]. Solid-state helps [C2]. And C1 again [C1].",
        [SRC1, SRC2],
    )
    assert [c.citation_key for c in citations] == ["C1", "C2"]
    assert citations[0].document_id == "doc-1"
    assert citations[0].page_number == 3
    assert citations[1].excerpt == SRC2.excerpt


def test_extract_citations_ignores_unknown_and_missing_markers() -> None:
    assert extract_citations("Unsupported [C9] and nothing here.", [SRC1, SRC2]) == []
    assert extract_citations("plain text without markers", [SRC1]) == []
    assert extract_citations(None, [SRC1]) == []


def test_extract_citations_accepts_lowercase_markers() -> None:
    citations = extract_citations("Answer [c1] per source.", [SRC1])
    assert len(citations) == 1
    assert citations[0].citation_key == "C1"


# ---- Grounded prompt builder ----


def test_grounded_prompt_wraps_context_and_pins_citation_contract() -> None:
    prompt = build_grounded_system_prompt([SRC1, SRC2])
    assert prompt.startswith(CHAT_SYSTEM_PROMPT)
    assert UNTRUSTED_BLOCK_START in prompt
    assert "[C1] Nevada lithium report.pdf (page 3)" in prompt
    assert "[C2] EV battery 2030.pdf (page 12)" in prompt
    assert "never invent citation keys" in prompt


def test_grounded_prompt_handles_unpaged_and_empty_sources() -> None:
    prompt = build_grounded_system_prompt([SRC3])
    assert "[C3] untitled.pdf" in prompt
    assert "(page" not in prompt
    assert build_grounded_system_prompt([]) == CHAT_SYSTEM_PROMPT


# ---- Service grounding (fake provider + SQLite) ----


class FakeContextProvider:
    """Returns a canned source list; optional failure for degrade tests."""

    def __init__(
        self,
        sources: list[ChatDocumentSource],
        *,
        raise_on_retrieve: Exception | None = None,
    ) -> None:
        self.sources = sources
        self.raise_on_retrieve = raise_on_retrieve
        self.calls: list[tuple[str, int]] = []

    async def retrieve(self, query: str, *, limit: int) -> list[ChatDocumentSource]:
        self.calls.append((query, limit))
        if self.raise_on_retrieve is not None:
            raise self.raise_on_retrieve
        return self.sources


class RecordingProvider:
    """Captures the system prompt each grounded turn was given."""

    name = "fake"

    def __init__(self, content: str = "reply") -> None:
        self.content = content
        self.system_prompts: list[str] = []

    async def generate(
        self, messages: list[LLMMessage], **kwargs: object
    ) -> LLMResponse:
        self.system_prompts.append(messages[0].content)
        return LLMResponse(
            content=self.content,
            model="fake-model",
            provider=self.name,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


@pytest.fixture
def provider() -> RecordingProvider:
    return RecordingProvider()


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


def _service(
    session: AsyncSession,
    provider: RecordingProvider,
    context_provider: FakeContextProvider | None,
    *,
    top_k: int = 4,
) -> ChatSessionService:
    return ChatSessionService(
        session=session,
        workflow=ChatWorkflow(provider=provider),
        context_provider=context_provider,  # type: ignore[arg-type]
        retrieval_top_k=top_k,
    )


async def test_documents_mode_grounds_turn_and_persists_citations(
    db_session, provider: RecordingProvider
) -> None:
    provider.content = "Nevada holds about 1% [C1]; solid-state may cut costs [C2]."
    ctx = FakeContextProvider([SRC1, SRC2])
    service = _service(db_session, provider, ctx)

    conv = await service.create_conversation(
        ConversationCreate(context_mode="documents")
    )
    reply = await service.send_message(
        conv.id, MessageCreate(content="What do the documents say about lithium?")
    )

    # Provider was consulted with the message and the configured top-k.
    assert ctx.calls == [("What do the documents say about lithium?", 4)]

    # The model received the grounded system prompt (not the plain one).
    assert provider.system_prompts
    assert "Nevada lithium report.pdf" in provider.system_prompts[0]
    assert provider.system_prompts[0] != CHAT_SYSTEM_PROMPT

    # Citations persisted: only markers that map to offered sources, in order.
    assert [c["citation_key"] for c in reply.citations] == ["C1", "C2"]
    assert reply.citations[0]["document_name"] == "Nevada lithium report.pdf"
    assert reply.citations[1]["page_number"] == 12


async def test_documents_mode_drops_unknown_markers(
    db_session, provider: RecordingProvider
) -> None:
    provider.content = "Invented [C9] and valid [C1]."
    ctx = FakeContextProvider([SRC1])
    service = _service(db_session, provider, ctx)

    conv = await service.create_conversation(
        ConversationCreate(context_mode="documents")
    )
    reply = await service.send_message(conv.id, MessageCreate(content="Anything?"))

    assert [c["citation_key"] for c in reply.citations] == ["C1"]


async def test_plain_mode_never_uses_context(
    db_session, provider: RecordingProvider
) -> None:
    provider.content = "No citations here."
    ctx = FakeContextProvider([SRC1])
    service = _service(db_session, provider, ctx)

    conv = await service.create_conversation(ConversationCreate())  # mode=none
    reply = await service.send_message(conv.id, MessageCreate(content="Hi"))

    assert not ctx.calls
    assert provider.system_prompts == [CHAT_SYSTEM_PROMPT]
    assert not reply.citations


async def test_missing_or_failing_context_provider_degrades_gracefully(
    db_session, provider: RecordingProvider
) -> None:
    ctx = FakeContextProvider([SRC1], raise_on_retrieve=RuntimeError("pgvector down"))
    service = _service(db_session, provider, ctx)

    conv = await service.create_conversation(
        ConversationCreate(context_mode="documents")
    )
    reply = await service.send_message(conv.id, MessageCreate(content="Still works?"))

    assert reply.content == provider.content  # answered anyway
    assert not reply.citations
    assert provider.system_prompts == [CHAT_SYSTEM_PROMPT]

    # Unconfigured (None) provider behaves identically.
    service = _service(db_session, provider, None)
    reply = await service.send_message(conv.id, MessageCreate(content="And again?"))
    assert not reply.citations
    assert provider.system_prompts[-1] == CHAT_SYSTEM_PROMPT


async def test_update_conversation_toggles_context_mode(
    db_session, provider: RecordingProvider
) -> None:
    service = _service(db_session, provider, FakeContextProvider([]))
    conv = await service.create_conversation(ConversationCreate())

    updated = await service.update_conversation(
        conv.id, ConversationUpdate(context_mode="documents")
    )
    assert updated.context_mode == "documents"

    updated = await service.update_conversation(
        conv.id, ConversationUpdate(context_mode="none")
    )
    assert updated.context_mode == "none"

    with pytest.raises(ValidationError):
        await service.update_conversation(
            conv.id,
            ConversationUpdate.model_construct(context_mode="articles"),  # type: ignore[arg-type]
        )


async def test_documents_mode_without_matches_answers_without_citations(
    db_session, provider: RecordingProvider
) -> None:
    provider.content = "I do not see this in the provided documents."
    service = _service(db_session, provider, FakeContextProvider([]))

    conv = await service.create_conversation(
        ConversationCreate(context_mode="documents")
    )
    reply = await service.send_message(conv.id, MessageCreate(content="Search me"))

    assert not reply.citations
    assert provider.system_prompts == [CHAT_SYSTEM_PROMPT]  # no block when empty