"""API tests for asynchronous research submission (Phase 6).

``POST /api/research/{id}/run`` must enqueue the job and return **202** without
executing the workflow. Only ``pending`` jobs may be queued; anything else is a
409 conflict.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
import redis.asyncio as redis_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import get_settings
from app.infrastructure.queue.client import RedisJobQueue
from app.main import app
from app.research.enums import ResearchJobStatus
from app.research.service import ResearchService


@pytest.fixture
async def client(db_engine: object) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def queue() -> RedisJobQueue:
    settings = get_settings()
    return RedisJobQueue(
        redis_asyncio.from_url(settings.redis_url, decode_responses=True),
        queue_name=settings.research_queue_name,
    )


async def test_run_enqueues_pending_job_and_returns_202(
    client: httpx.AsyncClient, queue: RedisJobQueue, db_session_factory: async_sessionmaker
) -> None:
    created = (await client.post("/api/research", json={"query": "Robotics"})).json()
    job_id = created["id"]

    response = await client.post(f"/api/research/{job_id}/run")

    assert response.status_code == 202
    body = response.json()
    assert body["id"] == job_id
    assert body["status"] == "pending"  # worker has not started yet

    # The job id is now sitting in the research queue.
    task = await queue.dequeue(timeout=0)
    assert task is not None
    assert str(task.job_id) == job_id
    await queue.acknowledge(task)

    # The API never executed the workflow inline.
    async with db_session_factory() as session:
        service = ResearchService(session)
        final = await service.get_research_job(UUID(job_id))
        assert final.status == ResearchJobStatus.PENDING


async def test_run_is_idempotent_for_pending_jobs(
    client: httpx.AsyncClient, queue: RedisJobQueue
) -> None:
    created = (await client.post("/api/research", json={"query": "Robotics"})).json()
    job_id = created["id"]

    first = await client.post(f"/api/research/{job_id}/run")
    second = await client.post(f"/api/research/{job_id}/run")

    assert first.status_code == 202
    assert second.status_code == 202

    # Idempotency: only ONE queue message exists for the job.
    settings = get_settings()
    import redis.asyncio as redis_asyncio

    probe = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    depth = await probe.llen(settings.research_queue_name)
    await probe.aclose()
    assert depth == 1

    # Drain so other tests are unaffected.
    while (task := await queue.dequeue(timeout=0)) is not None:
        await queue.acknowledge(task)


async def test_run_rejects_completed_job_with_409(
    client: httpx.AsyncClient, db_session_factory: async_sessionmaker
) -> None:
    created = (await client.post("/api/research", json={"query": "Robotics"})).json()

    # Drive the job to completion directly (as the worker would).
    async with db_session_factory() as session:
        service = ResearchService(session)
        await service.start_research(UUID(created["id"]))
        await service.complete_research(UUID(created["id"]), report='{"title": "done"}')

    response = await client.post(f"/api/research/{created['id']}/run")

    assert response.status_code == 409
    assert response.json()["code"] == "research_job_invalid_state"


async def test_run_rejects_missing_job_with_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/research/00000000-0000-0000-0000-000000000000/run")
    assert response.status_code == 404


async def test_get_job_exposes_progress_fields(
    client: httpx.AsyncClient,
) -> None:
    created = (await client.post("/api/research", json={"query": "progress fields"})).json()

    body = (await client.get(f"/api/research/{created['id']}")).json()

    assert body["status"] == "pending"
    assert body["stage"] is None
    assert body["attempts"] == 0
    assert body["progress"] == {"completed_tasks": 0, "total_tasks": 0}
    assert body["report"] is None