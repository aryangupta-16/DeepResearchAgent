"""Chat API.

Thin handlers: validate the request and delegate to the chat service. No LLM or
SDK logic lives here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_chat_service
from app.llm.base import LLMMessage
from app.workflows.chat.schemas import ChatRequest, ChatResponse
from app.workflows.chat.service import ChatService

router = APIRouter()

ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@router.get("")
def chat_info() -> dict[str, str]:
    """Lightweight endpoint marker (the chat endpoint itself is POST)."""
    return {"endpoint": "chat"}


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    service: ChatServiceDep,
) -> ChatResponse:
    """Run one stateless chat turn through the LLM provider."""
    history = [LLMMessage(role=item.role, content=item.content) for item in payload.messages]
    return await service.reply(payload.message, history=history)