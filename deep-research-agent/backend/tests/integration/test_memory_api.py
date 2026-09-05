"""PostgreSQL-backed integration tests for long-term memory (Phase 9).

These exercise the deterministic explicit-memory mechanism through the service
and repository boundary and through the HTTP API. They run against the isolated
test database (see ``tests/conftest.py``) — the developer's active database is
never touched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.memory.enums import MemoryType
from app.memory.schemas import MemoryCreate, MemoryUpdate
from app.memory.service import MemoryService


@pytest.fixture
async def client(db_engine: object) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client bound to the app (backs onto the isolated test schema)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


# ---- Service / repository behaviour ----


async def test_service_create_and_get_memory(db_session: AsyncSession) -> None:
    service = MemoryService(db_session)
    created = await service.create_memory(
        MemoryCreate(
            content="I am interested in humanoid robotics.",
            memory_type=MemoryType.INTEREST,
            importance=0.8,
        )
    )
    fetched = await service.get_memory(created.id)
    assert fetched.content == "I am interested in humanoid robotics."
    assert fetched.memory_type == "interest"
    assert fetched.source == "explicit"
    assert fetched.is_active is True


async def test_service_deduplicates_by_normalized_content(db_session: AsyncSession) -> None:
    service = MemoryService(db_session)
    first = await service.create_memory(MemoryCreate(content="I like AI."))
    second = await service.create_memory(
        MemoryCreate(content="I like AI", importance=0.9)
    )
    assert first.id == second.id
    memories = await service.list_memories(owner_id="default")
    assert len(memories) == 1
    assert memories[0].importance == 0.9


async def test_service_owner_isolation(db_session: AsyncSession) -> None:
    service = MemoryService(db_session)
    await service.create_memory(
        MemoryCreate(content="Robotics interest", owner_id="alice")
    )
    assert await service.list_memories(owner_id="bob") == []
    assert await service.retrieve_relevant("robotics", owner_id="bob") == []
    alice_matches = await service.retrieve_relevant("robotics", owner_id="alice")
    assert len(alice_matches) == 1


async def test_service_update_deactivate_delete(db_session: AsyncSession) -> None:
    service = MemoryService(db_session)
    memory = await service.create_memory(
        MemoryCreate(content="I prefer short reports.")
    )
    updated = await service.update_memory(memory.id, MemoryUpdate(importance=0.9))
    assert updated.importance == 0.9

    await service.deactivate_memory(memory.id)
    assert await service.list_memories(owner_id="default") == []
    inactive = await service.list_memories(owner_id="default", include_inactive=True)
    assert len(inactive) == 1

    await service.delete_memory(memory.id)
    assert await service.list_memories(owner_id="default", include_inactive=True) == []


async def test_service_retrieval_orders_by_relevance(db_session: AsyncSession) -> None:
    service = MemoryService(db_session)
    await service.create_memory(
        MemoryCreate(
            content="User likes cooking.",
            memory_type=MemoryType.PREFERENCE,
            importance=1.0,
        )
    )
    await service.create_memory(
        MemoryCreate(
            content="User is interested in humanoid robotics startups.",
            memory_type=MemoryType.INTEREST,
            importance=0.6,
        )
    )
    items = await service.retrieve_relevant(
        "humanoid robotics startups", owner_id="default"
    )
    assert items
    assert items[0].content.startswith("User is interested")


async def test_service_mark_used_tracks_usage(db_session: AsyncSession) -> None:
    service = MemoryService(db_session)
    memory = await service.create_memory(MemoryCreate(content="Robotics interest."))
    items = await service.retrieve_relevant("robotics", owner_id="default")
    assert items
    await service.mark_used([item.id for item in items])
    fetched = await service.get_memory(memory.id)
    assert fetched.use_count >= 1
    assert fetched.last_used_at is not None


# ---- HTTP API ----


async def test_api_memory_crud(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/memory",
        json={"content": "I am interested in robotics.", "memory_type": "interest"},
    )
    assert created.status_code == 201
    body = created.json()
    memory_id = body["id"]
    assert body["source"] == "explicit"
    assert body["is_active"] is True

    listed = await client.get("/api/memory")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    fetched = await client.get(f"/api/memory/{memory_id}")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "I am interested in robotics."

    patched = await client.patch(f"/api/memory/{memory_id}", json={"importance": 0.9})
    assert patched.status_code == 200
    assert patched.json()["importance"] == 0.9

    deleted = await client.delete(f"/api/memory/{memory_id}")
    assert deleted.status_code == 204

    gone = await client.get(f"/api/memory/{memory_id}")
    assert gone.status_code == 404


async def test_api_memory_invalid_importance_rejected(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/memory", json={"content": "x", "importance": 1.7}
    )
    assert response.status_code == 422