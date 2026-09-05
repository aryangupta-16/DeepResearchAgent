"""Long-term memory domain service.

Responsibilities (thin, single-concern):

- validate + deduplicate memory input,
- persist / update / deactivate / delete memories (PostgreSQL is the source
  of truth — Redis never stores permanent memory),
- retrieve relevant active memories for a research query (deterministic V1
  scoring, owner-filtered),
- track memory usage (best-effort telemetry),
- optionally run LLM memory *extraction* (validated output, never auto-saved).
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import (
    MemoryNotFoundError,
    NotConfiguredError,
    ValidationError,
)
from app.infrastructure.database.models.memory import DEFAULT_MEMORY_OWNER, Memory
from app.memory.enums import MemoryType
from app.memory.relevance import content_hash, normalize_text, rank_memories
from app.memory.repository import MemoryRepository
from app.memory.schemas import (
    MemoryContextItem,
    MemoryCreate,
    MemoryExtractionResult,
    MemoryUpdate,
)

logger = logging.getLogger(__name__)

#: Candidate cap for relevance ranking — retrieval never scans the entire table.
_CANDIDATE_LIMIT = 100


class MemoryService:
    """Operations over a single owner's long-term memory store."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: MemoryRepository | None = None,
        enabled: bool = True,
        max_results: int = 5,
    ) -> None:
        self._session = session
        self._repo = repository or MemoryRepository(session)
        self._enabled = enabled
        self._max_results = max(1, max_results)

    # ---- Creation (explicit only; the deterministic V1 mechanism) ----

    async def create_memory(self, payload: MemoryCreate) -> Memory:
        """Create one explicit memory, de-duplicating against active records.

        When an active memory with the same normalized content already exists
        for this owner, the existing row is *updated* (importance gets the max)
        instead of creating a duplicate.
        """
        self._require_enabled()
        normalized = normalize_text(payload.content)
        if not normalized:
            raise ValidationError("Memory content contains no usable text.")

        digest = content_hash(normalized)
        existing = await self._repo.get_active_by_hash(payload.owner_id, digest)
        if existing is not None:
            existing.importance = max(existing.importance, payload.importance)
            existing.memory_type = payload.memory_type.value
            existing.source = payload.source.value
            await self._session.flush()
            await self._commit()
            logger.info(
                "Memory deduplicated owner=%s memory_id=%s (merged into active row)",
                payload.owner_id, existing.id,
            )
            return existing

        memory = Memory(
            owner_id=payload.owner_id,
            content=payload.content.strip(),
            content_hash=digest,
            memory_type=payload.memory_type.value,
            source=payload.source.value,
            importance=max(0.0, min(1.0, payload.importance)),
        )
        await self._repo.create(memory)
        await self._commit()
        await self._session.refresh(memory)
        logger.info(
            "Memory created owner=%s memory_id=%s type=%s",
            memory.owner_id, memory.id, memory.memory_type,
        )
        return memory

    # ---- Retrieval (relevance-ordered, bounded, owner-filtered) ----

    async def retrieve_relevant(
        self,
        query: str,
        *,
        owner_id: str = DEFAULT_MEMORY_OWNER,
        memory_type: MemoryType | None = None,
    ) -> list[MemoryContextItem]:
        """Return the most relevant active memories as workflow context objects."""
        if not self._enabled or not query.strip():
            return []

        candidates = await self._repo.list_active(
            owner_id,
            memory_type=memory_type.value if memory_type else None,
            limit=_CANDIDATE_LIMIT,
        )
        ranked = rank_memories(candidates, query, limit=self._max_results)
        items = [
            MemoryContextItem(
                id=str(memory.id),
                content=memory.content,
                memory_type=memory.memory_type,
                importance=memory.importance,
                source=memory.source,
            )
            for memory in ranked
        ]
        if items:
            logger.info(
                "Memory retrieval owner=%s query_terms=%d matched=%d",
                owner_id, len(query.split()), len(items),
            )
        return items

    async def mark_used(self, memory_ids: list[str]) -> None:
        """Best-effort usage telemetry; never raises into the caller."""
        if not memory_ids:
            return
        try:
            parsed = [UUID(value) for value in memory_ids]
            updated = await self._repo.mark_used(parsed)
            await self._commit()
            logger.info(
                "Memory usage tracked memory_ids=%d updated=%d",
                len(parsed),
                updated,
            )
        except Exception:
            # Telemetry is secondary to research execution — log and continue.
            logger.warning(
                "Memory usage tracking failed; continuing without it.",
                exc_info=True,
            )

    # ---- CRUD ----

    async def get_memory(self, memory_id: UUID) -> Memory:
        memory = await self._repo.get_by_id(memory_id)
        if memory is None:
            raise MemoryNotFoundError(f"Memory {memory_id} not found.")
        return memory

    async def list_memories(
        self,
        *,
        owner_id: str = DEFAULT_MEMORY_OWNER,
        memory_type: MemoryType | None = None,
        limit: int = 100,
        include_inactive: bool = False,
    ) -> list[Memory]:
        """List memories for an owner (active-only by default, bounded)."""
        if include_inactive:
            result = await self._session.scalars(
                select(Memory)
                .where(Memory.owner_id == owner_id)
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
            return list(result)
        return await self._repo.list_active(
            owner_id,
            memory_type=memory_type.value if memory_type else None,
            limit=limit,
        )

    async def update_memory(self, memory_id: UUID, payload: MemoryUpdate) -> Memory:
        self._require_enabled()
        memory = await self.get_memory(memory_id)
        if payload.content is not None:
            normalized = normalize_text(payload.content)
            if not normalized:
                raise ValidationError("Memory content contains no usable text.")
            new_digest = content_hash(normalized)
            duplicate = await self._repo.get_active_by_hash(memory.owner_id, new_digest)
            if duplicate is not None and duplicate.id != memory.id:
                raise ValidationError(
                    "An active memory with this content already exists for the owner."
                )
            memory.content = payload.content.strip()
            memory.content_hash = new_digest
        if payload.memory_type is not None:
            memory.memory_type = payload.memory_type.value
        if payload.importance is not None:
            memory.importance = payload.importance
        if payload.is_active is not None:
            memory.is_active = payload.is_active
        await self._session.flush()
        await self._commit()
        await self._session.refresh(memory)
        logger.info("Memory updated owner=%s memory_id=%s", memory.owner_id, memory.id)
        return memory

    async def deactivate_memory(self, memory_id: UUID) -> Memory:
        memory = await self.get_memory(memory_id)
        memory.is_active = False
        await self._session.flush()
        await self._commit()
        logger.info("Memory deactivated owner=%s memory_id=%s", memory.owner_id, memory.id)
        return memory

    async def delete_memory(self, memory_id: UUID) -> None:
        removed = await self._repo.delete(memory_id)
        if not removed:
            raise MemoryNotFoundError(f"Memory {memory_id} not found.")
        await self._commit()
        logger.info("Memory deleted id=%s", memory_id)

    # ---- LLM extraction (candidates only; never auto-persisted) ----

    async def extract_candidates(self, user_text: str) -> MemoryExtractionResult:
        """Run validated LLM extraction. Returns candidates WITHOUT persisting."""
        self._require_enabled()
        from app.llm.factory import get_llm_provider
        from app.memory.extraction import MemoryExtractor

        provider = get_llm_provider()
        extractor = MemoryExtractor(provider)
        result = await extractor.extract(user_text)
        logger.info("Memory extraction produced %d candidate(s).", len(result.memories))
        return result

    # ---- Helpers ----

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise NotConfiguredError(
                "Long-term memory is disabled (MEMORY_ENABLED=false)."
            )

    async def _commit(self) -> None:
        """Commit the current transaction, rolling back explicitly on failure."""
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise