"""Shared FastAPI dependencies.

Routes resolve request-scoped services here; database sessions are never created
manually inside route handlers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.infrastructure.database.postgres import get_session_factory
from app.llm.factory import get_llm_provider
from app.research.service import ResearchService
from app.workflows.chat.service import ChatService

if TYPE_CHECKING:  # pragma: no cover
    from app.chat.service import ChatSessionService
    from app.memory.service import MemoryService


def get_settings_dependency(request: Request) -> Settings:
    """Return the cached application settings."""
    return get_settings()


def get_request_context(request: Request) -> Iterator[dict]:
    """Placeholder request-scoped context (correlation id, tenant, audit)."""
    # TODO: attach request-scoped correlation ID, tenant, and audit context.
    yield {}


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped :class:`AsyncSession`.

    Transaction control is owned by the service layer; this dependency only
    guarantees rollback (on failure) and session closure.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_research_service(session: DbSession) -> ResearchService:
    """Build a request-scoped research service bound to the DB session.

    The queue client is injected so submissions are enqueued for the worker; if
    Redis is briefly unavailable the database outbox guarantees eventual delivery.
    """
    from app.infrastructure.queue.client import get_queue_client

    return ResearchService(
        session=session,
        queue=get_queue_client(),
    )


def get_chat_service() -> ChatService:
    """Build a chat service wired to the configured LLM provider."""
    return ChatService(provider=get_llm_provider())


def get_document_service(session: DbSession):
    """Build a document service bound to the DB session + configured storage."""
    from app.config.settings import get_settings
    from app.documents.service import DocumentService
    from app.infrastructure.storage.object_storage import build_object_store

    settings = get_settings()
    return DocumentService(
        session=session,
        object_store=build_object_store(),
        max_size_mb=settings.max_document_size_mb,
    )


def get_conversation_service(
    session: DbSession,
) -> ChatSessionService:
    """Build a request-scoped chat session service bound to the DB session.

    The LLM turn is synchronous request/response by design (Phase C tradeoff):
    no queue, no jobs — but history is windowed and usage is persisted. When
    an embedding provider is configured, documents-grounded conversations
    (``context_mode="documents"``) retrieve through the same RAG stack the
    research pipeline uses; otherwise they degrade to plain chat.
    """
    from app.chat.context import DocumentContextProvider
    from app.chat.service import ChatSessionService
    from app.common.exceptions import NotConfiguredError
    from app.rag.embeddings import build_embedding_provider
    from app.rag.retrieval import DocumentRetrievalService

    settings = get_settings()
    context_provider = None
    try:
        embedding = build_embedding_provider()
        if embedding is not None:
            context_provider = DocumentContextProvider(
                retrieval=DocumentRetrievalService(
                    session=session,
                    embedding_provider=embedding,
                    top_k=settings.vector_top_k,
                )
            )
    except NotConfiguredError:
        # Embedding provider configured but unusable (e.g. missing key):
        # chat still works, just without document grounding.
        context_provider = None
    return ChatSessionService(
        session=session,
        provider=get_llm_provider(),
        history_window=settings.chat_history_window,
        context_provider=context_provider,
        retrieval_top_k=settings.chat_context_top_k,
    )


def get_memory_service(session: DbSession) -> MemoryService:
    """Build a request-scoped memory service bound to the DB session.

    Honor the memory toggle so that disabled memory behaves predictably:
    creation/extraction refuse loudly, retrieval returns nothing.
    """
    from app.config.settings import get_settings
    from app.memory.service import MemoryService

    settings = get_settings()
    return MemoryService(
        session=session,
        enabled=settings.memory_enabled,
        max_results=settings.memory_max_results,
    )