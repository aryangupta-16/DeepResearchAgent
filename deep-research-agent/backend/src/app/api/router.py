"""Top-level API router assembling all sub-routers."""

from fastapi import APIRouter

from app.api.routes import (
    chat,
    conversations,
    documents,
    health,
    memory,
    research,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(
    conversations.router, prefix="/conversations", tags=["conversations"]
)
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])