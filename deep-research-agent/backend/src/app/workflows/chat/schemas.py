"""Pydantic schemas for the chat API.

V1 keeps chat stateless: a request carries a message and an optional, non-persistent
conversation history.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

ChatMessageField = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8000),
]

ChatRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """A single conversation turn provided by the client."""

    role: ChatRole
    content: ChatMessageField


class ChatRequest(BaseModel):
    """Payload for a chat turn."""

    message: ChatMessageField
    messages: list[ChatMessage] = Field(default_factory=list)


class UsageResponse(BaseModel):
    """Canonical token usage; fields are null when the provider reports none."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatResponse(BaseModel):
    """Assistant reply mapped from our internal LLM response."""

    message: str
    model: str
    provider: str
    usage: UsageResponse | None = None