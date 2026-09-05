"""Pydantic schemas for the long-term memory domain.

These are the API / workflow contract. SQLAlchemy ORM objects are never passed
through LangGraph state or returned from routes — domain objects (below) are.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.memory.enums import MemorySource, MemoryType

#: Lightweight owner identity bound to a research job's ``owner_id``.
OwnerId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]

#: Free-form memory content; bounded to keep stored memory sane.
MemoryContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class MemoryCreate(BaseModel):
    """Payload for explicit memory creation (deterministic V1 mechanism)."""

    content: MemoryContent
    memory_type: MemoryType = MemoryType.CONTEXT
    source: MemorySource = MemorySource.EXPLICIT
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    owner_id: OwnerId = "default"


class MemoryUpdate(BaseModel):
    """Partial update payload (only present fields are applied)."""

    content: MemoryContent | None = None
    memory_type: MemoryType | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    is_active: bool | None = None


class MemoryResponse(BaseModel):
    """Public representation of one stored memory."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: str
    content: str
    memory_type: str
    source: str
    importance: float
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    use_count: int = 0
    is_active: bool = True


class MemoryListResponse(BaseModel):
    """Paged-ish list of memories (V1: flat, bounded by ``limit``)."""

    memories: list[MemoryResponse] = Field(default_factory=list)
    count: int = 0


# ---- Workflow context (LangGraph state) ----
#
# These objects are what actually reach the workflow. They are plain Pydantic
# values (never ORM rows) so graph state stays independent of persistence.


class MemoryContextItem(BaseModel):
    """One memory, rendered for planner/user context consumption."""

    id: str
    content: str
    memory_type: str
    importance: float
    source: str


class MemoryContext(BaseModel):
    """The set of memories available to a single research execution."""

    memories: list[MemoryContextItem] = Field(default_factory=list)

    @property
    def content_lines(self) -> list[str]:
        """Flat content strings for prompt injection (context only, never cited)."""
        return [memory.content for memory in self.memories]


# ---- LLM memory extraction (validated before anything may be persisted) ----


class MemoryExtractionItem(BaseModel):
    """A single structured memory candidate extracted from user text."""

    content: str = Field(..., min_length=1, max_length=2000)
    memory_type: MemoryType = MemoryType.CONTEXT
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    source: MemorySource = MemorySource.EXPLICIT


class MemoryExtractionResult(BaseModel):
    """Validated LLM extraction output.

    An endpoint may *return* these candidates but they are never persisted
    automatically — explicit creation is the only path into the store.
    """

    memories: list[MemoryExtractionItem] = Field(default_factory=list)