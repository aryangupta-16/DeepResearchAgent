"""Conversation API (Phase C1).

Routes stay thin: validate the payload, delegate to
:class:`~app.chat.service.ChatSessionService`, map ORM rows to response
schemas. The LLM turn itself is synchronous by design — chat latency is
seconds and there is no long-running state, so the queue never sees it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_conversation_service
from app.chat.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
)
from app.chat.service import ChatSessionService

router = APIRouter()

ChatSessionDep = Annotated[ChatSessionService, Depends(get_conversation_service)]


@router.post("", status_code=201, response_model=ConversationSummary)
async def create_conversation(
    payload: ConversationCreate,
    service: ChatSessionDep,
) -> ConversationSummary:
    """Start a new chat session (optionally documents-grounded)."""
    conversation = await service.create_conversation(payload)
    return ConversationSummary.model_validate(conversation)


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    service: ChatSessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationListResponse:
    """List conversations, most recently active first."""
    conversations = await service.list_conversations(limit=limit, offset=offset)
    return ConversationListResponse(
        conversations=[
            ConversationSummary.model_validate(c) for c in conversations
        ]
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID,
    service: ChatSessionDep,
) -> ConversationDetail:
    """Fetch one conversation with its full persisted thread."""
    conversation = await service.get_conversation(conversation_id)
    detail = ConversationDetail.model_validate(conversation)
    # Messages come from the eager-loaded relationship; keep them ordered.
    detail.messages = [
        MessageResponse.model_validate(m) for m in conversation.messages
    ]
    return detail


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    service: ChatSessionDep,
) -> ConversationSummary:
    """Toggle context grounding for a conversation (e.g. ``documents``)."""
    conversation = await service.update_conversation(conversation_id, payload)
    return ConversationSummary.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    service: ChatSessionDep,
) -> Response:
    """Delete a conversation and (cascade) all of its messages."""
    await service.delete_conversation(conversation_id)
    return Response(status_code=204)


@router.post(
    "/{conversation_id}/messages", response_model=MessageResponse
)
async def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    service: ChatSessionDep,
) -> MessageResponse:
    """Send one user turn; returns the persisted assistant reply."""
    message = await service.send_message(conversation_id, payload)
    return MessageResponse.model_validate(message)


@router.post("/{conversation_id}/messages/stream")
async def send_message_stream(
    conversation_id: UUID,
    payload: MessageCreate,
    service: ChatSessionDep,
) -> StreamingResponse:
    """Send one user turn and stream the assistant reply as Server-Sent Events.

    Frames: ``start`` (user message id), ``delta`` (text chunks), ``done``
    (the full persisted assistant message), ``error`` (terminal failure).
    """
    await service.get_conversation(conversation_id)  # raise 404 before streaming

    async def event_frames() -> AsyncIterator[str]:
        async for event in service.stream_turn(conversation_id, payload):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

    return StreamingResponse(
        event_frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
