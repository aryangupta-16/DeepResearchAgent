"""Pydantic schemas for the chat session API (Phase C1/C2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

#: Bounded turn content — same cap as the stateless chat endpoint.
ChatContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)
]

#: Bounded, optional conversation title.
ConversationTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]

ChatRole = Literal["user", "assistant"]

#: Per-conversation answer grounding (Phase C2).
ChatContextMode = Literal["none", "documents"]


class ChatCitation(BaseModel):
    """One document citation backing an assistant chat reply.

    Mirrors the persisted JSON snapshot on ``chat_messages.citations``. The
    marker the model wrote into the reply (``[C1]``) is stored as
    ``citation_key`` so the UI can link chips back to the source.
    """

    citation_key: str
    document_id: str
    document_name: str
    page_number: int | None = None
    excerpt: str = ""
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class ConversationCreate(BaseModel):
    """Payload for starting a new conversation."""

    title: ConversationTitle | None = None
    context_mode: ChatContextMode = "none"


class ConversationUpdate(BaseModel):
    """Partial conversation update (currently only the context mode)."""

    context_mode: ChatContextMode


class ConversationSummary(BaseModel):
    """Public representation of a conversation (without messages)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None = None
    # Defensive: tolerate NULL in pre-existing rows (migration 0009 added the
    # column with server_default="none", so new rows are always populated).
    context_mode: str | None = "none"
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]


class MessageCreate(BaseModel):
    """Payload for one user turn."""

    content: ChatContent


class MessageResponse(BaseModel):
    """One persisted chat turn, including provider/usage metadata + citations."""

    model_config = ConfigDict(from_attributes=True)

    # Autoincrement int (ordering-critical); conversations remain UUID-keyed.
    id: int
    conversation_id: UUID
    role: ChatRole
    content: str
    model: str | None = None
    provider: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    citations: list[ChatCitation] = Field(default_factory=list)
    created_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def _citations_default(cls, value: object) -> object:
        """ORM rows store ``NULL`` for uncited replies; expose ``[]`` instead."""
        return value if value is not None else []


class ConversationDetail(ConversationSummary):
    """Conversation with its full (persisted) message thread."""

    messages: list[MessageResponse]
