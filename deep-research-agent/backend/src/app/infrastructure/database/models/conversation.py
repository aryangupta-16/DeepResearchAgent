"""Conversation + chat message ORM models (Phase C1).

Conversations are durable chat sessions: quick answers without the deep-research
pipeline, sharing the same LLM/provider layer. ``owner_id`` is a nullable
lightweight string identity (mirrors ``research_jobs``/``memories``) so adding
authentication later requires no migration of existing history.

Token usage is stored per assistant message — the chat ledger that keeps chat
costs visible and separate from research job costs (Phase A funnel).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.postgres import Base


class Conversation(Base):
    """One chat session; messages belong to exactly one conversation."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner_created", "owner_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Nullable now so adding auth later doesn't require migrating history.
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Auto-derived from the first user message when not supplied by the client.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # ``none`` (plain chat, C1 default) | ``documents`` (answer grounded in the
    # uploaded-document RAG stack with [C#] citations — Phase C2).
    context_mode: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at, ChatMessage.id",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} title={self.title!r}>"


class ChatMessage(Base):
    """A single persisted chat turn (user or assistant) with usage metadata.

    The primary key is an autoincrement integer (not a UUID): message ordering
    must be deterministic even when several turns land within the same
    ``created_at`` tick — ``func.now()`` is transaction-fixed on PostgreSQL and
    second-granular on SQLite, so a monotonic id backs the history query.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # "user" | "assistant" (system prompts are built, never stored).
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Immutable snapshot of the citations backing this reply (Phase C2): a JSON
    # list of {citation_key, document_id, document_name, page_number, excerpt,
    # score}. Never queried into — returned as-is — so a portable JSON type.
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return (
            f"<ChatMessage id={self.id} role={self.role!r} "
            f"conversation={self.conversation_id}>"
        )
