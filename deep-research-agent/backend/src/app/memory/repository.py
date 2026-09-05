"""Memory persistence (SQLAlchemy repository).

All memory SQL lives here. Services and routes never construct raw queries.

Retrieval is always bounded and filtered by ``owner_id`` + ``is_active`` so a
research request never loads the full table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.memory import Memory


class MemoryRepository:
    """Data-access boundary for :class:`Memory`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, memory: Memory) -> Memory:
        self._session.add(memory)
        await self._session.flush()
        return memory

    async def get_by_id(self, memory_id: UUID) -> Memory | None:
        return await self._session.get(Memory, memory_id)

    async def get_active_by_hash(self, owner_id: str, content_hash: str) -> Memory | None:
        return await self._session.scalar(
            select(Memory).where(
                Memory.owner_id == owner_id,
                Memory.content_hash == content_hash,
                Memory.is_active.is_(True),
            )
        )

    async def list_active(
        self,
        owner_id: str,
        *,
        memory_type: str | None = None,
        limit: int = 100,
    ) -> list[Memory]:
        """List active memories for an owner, most important first (bounded)."""
        statement = select(Memory).where(
            Memory.owner_id == owner_id,
            Memory.is_active.is_(True),
        )
        if memory_type:
            statement = statement.where(Memory.memory_type == memory_type)
        statement = statement.order_by(
            Memory.importance.desc(), Memory.updated_at.desc()
        ).limit(limit)
        return list(await self._session.scalars(statement))

    async def count_active(self, owner_id: str) -> int:
        result = await self._session.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.owner_id == owner_id, Memory.is_active.is_(True))
        )
        return int(result or 0)

    async def mark_used(self, memory_ids: list[UUID]) -> int:
        """Increment ``use_count`` + stamp ``last_used_at`` for the given ids.

        Returns the number of rows updated. Best-effort telemetry: callers must
        tolerate failures (research must never depend on usage tracking).
        """
        if not memory_ids:
            return 0
        result = await self._session.execute(
            update(Memory)
            .where(Memory.id.in_(memory_ids))
            .values(
                use_count=Memory.use_count + 1,
                last_used_at=datetime.now(UTC),
            )
        )
        return int(result.rowcount or 0)

    async def delete(self, memory_id: UUID) -> bool:
        memory = await self.get_by_id(memory_id)
        if memory is None:
            return False
        await self._session.delete(memory)
        await self._session.flush()
        return True