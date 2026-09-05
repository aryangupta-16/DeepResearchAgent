"""Persistence for conversations and chat messages (Phase C1).

All SQL lives here; the service layer never builds queries. Every write is
flushed (so defaults like ``created_at`` resolve) and committed by the service.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infrastructure.database.models.conversation import ChatMessage, Conversation


class ConversationRepository:
    """Database access for the chat session domain."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Conversations ----

    async def create(self, conversation: Conversation) -> Conversation:
        self._session.add(conversation)
        await self._session.flush()
        await self._session.refresh(conversation)
        return conversation

    async def get(self, conversation_id: UUID) -> Conversation | None:
        """Fetch one conversation with its messages eagerly loaded."""
        result = await self._session.scalars(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
            .limit(1)
        )
        return result.first()

    async def list(
        self, *, owner_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        """Most-recently-updated conversations (newest activity first)."""
        query = select(Conversation).order_by(Conversation.updated_at.desc())
        if owner_id is not None:
            query = query.where(Conversation.owner_id == owner_id)
        query = query.limit(limit).offset(offset)
        result = await self._session.scalars(query)
        return list(result)

    async def delete(self, conversation_id: UUID) -> bool:
        """Hard-delete a conversation; messages cascade at the DB level."""
        result = await self._session.execute(
            select(Conversation.id).where(Conversation.id == conversation_id).limit(1)
        )
        if result.first() is None:
            return False
        await self._session.execute(
            Conversation.__table__.delete().where(  # type: ignore[attr-defined]
                Conversation.id == conversation_id
            )
        )
        return True

    async def count_messages(self, conversation_id: UUID) -> int:
        result = await self._session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
        )
        return int(result or 0)

    # ---- Messages ----

    async def append_message(self, message: ChatMessage) -> ChatMessage:
        self._session.add(message)
        await self._session.flush()
        await self._session.refresh(message)
        return message

    async def list_messages(
        self, conversation_id: UUID, *, window: int | None = None
    ) -> list[ChatMessage]:
        """Messages in chronological order, optionally limited to the last
        ``window`` turns (bounded prompt history — prompts never grow
        unbounded)."""
        if window is not None:
            # Newest-first to grab the tail, then re-reverse chronologically.
            # NB: a fresh query — chaining .order_by() would append criteria,
            # not replace them.
            tail = await self._session.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                .limit(window)
            )
            return list(reversed(list(tail)))
        result = await self._session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
        return list(result)
