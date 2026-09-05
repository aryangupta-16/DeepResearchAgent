"""Long-term memory API (Phase 9).

Routes stay thin: validate the payload, delegate to :class:`MemoryService`,
and map domain objects to response schemas. No SQL / persistence logic here.

``POST /api/memory`` is the deterministic explicit mechanism. ``POST /api/memory/extract``
returns LLM candidates WITHOUT persisting them — memory is never auto-saved.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import get_memory_service
from app.common.exceptions import ValidationError
from app.memory.enums import MemoryType
from app.memory.schemas import (
    MemoryCreate,
    MemoryExtractionResult,
    MemoryListResponse,
    MemoryResponse,
    MemoryUpdate,
)
from app.memory.service import MemoryService

router = APIRouter()

MemoryServiceDep = Annotated[MemoryService, Depends(get_memory_service)]


def _as_response(memory: object) -> MemoryResponse:
    """Map an ORM memory to the public response schema."""
    return MemoryResponse.model_validate(memory)


@router.post("", status_code=201, response_model=MemoryResponse)
async def create_memory(
    payload: MemoryCreate,
    service: MemoryServiceDep,
) -> MemoryResponse:
    """Explicitly create a durable long-term memory (deterministic V1 mechanism)."""
    memory = await service.create_memory(payload)
    return _as_response(memory)


@router.post("/extract", response_model=MemoryExtractionResult)
async def extract_memory_candidates(
    body: dict[str, str],
    service: MemoryServiceDep,
) -> MemoryExtractionResult:
    """Validate LLM extraction of candidate memories from user text.

    Candidates are returned but NEVER persisted automatically — explicit
    ``POST /api/memory`` is the only write path into the store.
    """
    user_text = (body.get("text") or "").strip()
    if not user_text:
        raise ValidationError("text must not be empty.")
    return await service.extract_candidates(user_text)


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    service: MemoryServiceDep,
    owner_id: Annotated[str, Query(max_length=64)] = "default",
    memory_type: MemoryType | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    include_inactive: bool = False,
) -> MemoryListResponse:
    """List memories for an owner (active-first, bounded)."""
    memories = await service.list_memories(
        owner_id=owner_id,
        memory_type=memory_type,
        limit=limit,
        include_inactive=include_inactive,
    )
    return MemoryListResponse(
        memories=[_as_response(m) for m in memories],
        count=len(memories),
    )


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: UUID,
    service: MemoryServiceDep,
) -> MemoryResponse:
    """Return a single memory."""
    memory = await service.get_memory(memory_id)
    return _as_response(memory)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: UUID,
    payload: MemoryUpdate,
    service: MemoryServiceDep,
) -> MemoryResponse:
    """Partially update a memory (content, type, importance, active)."""
    memory = await service.update_memory(memory_id, payload)
    return _as_response(memory)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    service: MemoryServiceDep,
) -> Response:
    """Permanently delete a memory."""
    await service.delete_memory(memory_id)
    return Response(status_code=204)