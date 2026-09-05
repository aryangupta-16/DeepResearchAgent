"""Deterministic asynchronous end-to-end test (Phase 6).

Flow under test:

    POST /api/research (HTTP 202, returns immediately)
        -> PostgreSQL pending job + outbox row
        -> Redis queue message
        -> worker iteration (process_next)
        -> ResearchJobHandler -> ResearchExecutionService
        -> real DeepResearchWorkflow over MOCK OpenAI / SerpApi / web pages
        -> PostgreSQL completed job with citations

Requires Docker PostgreSQL + Redis; skipped automatically otherwise.
No real OpenAI/SerpApi traffic happens.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import redis.asyncio as redis_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import get_settings
from app.evidence.service import EvidenceService
from app.infrastructure.queue.client import RedisJobQueue
from app.infrastructure.queue.handlers import ResearchJobHandler
from app.llm.providers.openai import OpenAIProvider
from app.main import app
from app.research.execution_service import ResearchExecutionService
from app.research.service import ResearchService
from app.tools.browser.tool import FetchTool
from app.tools.search.providers import SearchProviderConfig, SerperSearchProvider
from app.tools.search.tool import SearchTool
from app.workflows.deep_research.workflow import build_deep_research_workflow

logger = logging.getLogger(__name__)

MOCK_DIR = Path(__file__).parent / "fixtures"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def mock_research_server():
    """Start the combined mock server; yield its base url."""
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(MOCK_DIR)}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "mock_openai:app",
            "--host", "127.0.0.1", f"--port={port}",
        ],
        cwd=str(MOCK_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"

    async def _wait_ready() -> None:
        probe = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        }
        for _ in range(50):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{base_url}/v1/chat/completions", json=probe, timeout=1.0
                    )
                if response.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.ReadError):
                pass
            await asyncio.sleep(0.2)
        raise RuntimeError("mock server did not start in time")

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_wait_ready())
    loop.close()

    yield base_url

    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
async def redis_queue():
    settings = get_settings()
    try:
        client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Redis is not available: {exc}")
        return  # pragma: no cover
    queue = RedisJobQueue(
        client,
        queue_name=settings.research_queue_name,
        lease_timeout=settings.research_job_lease_timeout,
    )
    try:
        await client.delete(settings.research_queue_name)
        yield queue
    finally:
        await client.delete(settings.research_queue_name)
        await client.aclose()


@pytest.fixture
async def client(db_engine: object) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _workflow_factory_for(base_url: str):
    """Build the REAL workflow; only external transports point at mocks."""

    def _factory(research_service: ResearchService):
        provider = OpenAIProvider(
            api_key="test-key", model="gpt-4o-mini", base_url=f"{base_url}/v1"
        )
        search_tool = SearchTool(
            SerperSearchProvider(
                SearchProviderConfig(api_key="k", endpoint=f"{base_url}/mock_search")
            )
        )
        return build_deep_research_workflow(
            research_service=research_service,
            llm_provider=provider,
            search_tool=search_tool,
            fetch_tool=FetchTool(timeout_seconds=10.0),
        )

    return _factory


async def _drive_worker(
    redis_queue: RedisJobQueue,
    db_session_factory: async_sessionmaker[AsyncSession],
    base_url: str,
) -> bool:
    """Run worker iterations (identical wiring to the production worker)."""
    from app.infrastructure.queue.workers import process_next

    execution = ResearchExecutionService(
        runner_factory=lambda: ResearchService(session=db_session_factory()),
        workflow_factory=_workflow_factory_for(base_url),
        max_retries=get_settings().research_worker_max_retries,
    )
    handler = ResearchJobHandler(
        execution_service=execution,
        queue=redis_queue,
        lease_timeout_seconds=get_settings().research_job_lease_timeout,
    )

    processed = False
    while await process_next(redis_queue, handler, timeout=0):
        processed = True
    return processed


async def test_async_research_end_to_end(
    client: httpx.AsyncClient,
    redis_queue: RedisJobQueue,
    db_session_factory: async_sessionmaker[AsyncSession],
    mock_research_server: str,
) -> None:
    base_url = mock_research_server

    # --- 1. Submit: must return quickly with HTTP 202 -----------------------
    started = time.perf_counter()
    response = await client.post(
        "/api/research",
        json={"query": "State of humanoid robotics", "workflow_type": "deep_research"},
    )
    submission_latency = time.perf_counter() - started

    assert response.status_code == 202
    body = response.json()
    job_id = body["id"]
    assert body["status"] == "pending"
    assert submission_latency < 5.0, (
        f"submission took {submission_latency:.2f}s — must be near-instant"
    )

    # Job is durably pending in PostgreSQL before any worker runs.
    status_body = (await client.get(f"/api/research/{job_id}")).json()
    assert status_body["status"] == "pending"
    assert status_body["progress"] == {"completed_tasks": 0, "total_tasks": 0}

    # A queue message exists for the worker; put the identical message back
    # (enqueue, not requeue — the first attempt must stay attempt 1).
    queued = await redis_queue.dequeue(timeout=0)
    assert queued is not None
    assert str(queued.job_id) == job_id
    await redis_queue.enqueue(queued)

    # --- 2. Worker consumes and executes -----------------------------------
    did_work = await asyncio.wait_for(
        _drive_worker(redis_queue, db_session_factory, base_url), timeout=120.0
    )
    assert did_work is True

    # --- 3. Verify terminal state through the API --------------------------
    final = (await client.get(f"/api/research/{job_id}")).json()
    assert final["status"] == "completed"
    assert final["stage"] == "completed"
    assert final["attempts"] == 1
    assert final["error"] is None
    assert final["started_at"] is not None
    assert final["completed_at"] is not None
    assert final["report"], "completed job must expose its report"

    import json as jsonlib

    report = jsonlib.loads(final["report"])
    cited = {
        source_id
        for section in report["sections"]
        for source_id in section["citation_source_ids"]
    }
    assert cited, "report must contain machine-readable citations"

    assert final["progress"]["total_tasks"] >= 2
    assert final["progress"]["completed_tasks"] == final["progress"]["total_tasks"]

    # --- 4. Verify durable evidence in PostgreSQL --------------------------
    async with db_session_factory() as session:
        service = ResearchService(session)
        evidence_service = EvidenceService(session)

        job = await service.get_research_job(UUID(job_id))
        assert job.status.value == "completed"

        tasks = await service.get_research_tasks(job.id)
        assert len(tasks) >= 2

        sources = await evidence_service.list_sources_for_job(job.id)
        assert len(sources) >= 1
        source_ids = {str(source.id) for source in sources}
        assert cited <= source_ids, "every citation must resolve to a stored source"

        evidence = [
            item
            for source in sources
            for item in await evidence_service.list_evidence_for_source(source.id)
        ]
        assert len(evidence) >= 1

    logger.info("async e2e passed job=%s latency=%.3fs", job_id, submission_latency)