"""Shared fixtures for PostgreSQL-backed integration tests.

Autouse cleanup empties every table after each test so tests are isolated even
though the schema itself lives for the whole session. The research Redis queue is
also flushed between tests (silently skipped when Redis is unreachable).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.postgres import Base


@pytest.fixture(autouse=True)
async def _clean_tables(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """Delete all rows after each integration test."""
    yield
    async with db_session_factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(table.delete())
        await session.commit()


@pytest.fixture(autouse=True)
async def _flush_research_queue() -> AsyncIterator[None]:
    """Drop queued/in-flight research messages between tests (best effort)."""
    yield
    try:
        from redis.asyncio import Redis

        from app.config.settings import get_settings

        settings = get_settings()
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.delete(settings.research_queue_name)
            inflight = [
                key async for key in client.scan_iter(match="research:inflight:*")
            ]
            if inflight:
                await client.delete(*inflight)
        finally:
            await client.aclose()
    except Exception:  # pragma: no cover - Redis optional for some suites
        pass