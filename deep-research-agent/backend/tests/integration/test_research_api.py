"""API tests for the research endpoints against PostgreSQL.

These exercise the app exactly as HTTP clients do (via ASGITransport) and are
skipped when PostgreSQL is unreachable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.evidence.service import EvidenceService
from app.infrastructure.database.postgres import get_session_factory
from app.main import app
from app.research.service import ResearchService


@pytest.fixture
async def client(db_engine: object) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client bound to the app; depends on an existing DB schema."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as http:
        yield http


async def _create_job(client: httpx.AsyncClient, query: str = "Research robotics") -> dict:
    response = await client.post(
        "/api/research", json={"query": query, "workflow_type": "deep_research"}
    )
    assert response.status_code == 202
    return response.json()


async def test_get_sources_for_job_with_evidence(
    client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker,
) -> None:
    created = await _create_job(client, query="sources please")
    job_id = UUID(created["id"])

    # Persist a source + evidence directly (as the worker would).
    async with db_session_factory() as session:
        service = ResearchService(session)
        await service.start_research(job_id)
        task = await service.create_research_task(
            research_job_id=job_id, description="task"
        )
        evidence_service = EvidenceService(session)
        source = await evidence_service.save_source(
            research_job_id=job_id,
            research_task_id=task.id,
            url="https://example.com/robots",
            title="Robotics Overview",
            domain="example.com",
            content="Humanoid robots are advancing.",
        )
        await evidence_service.save_evidence(
            research_job_id=job_id,
            research_task_id=task.id,
            source_id=source.id,
            claim="Humanoid robots are advancing quickly.",
            excerpt="Humanoid robots are advancing.",
            locator="paragraph 1",
        )

    response = await client.get(f"/api/research/{job_id}/sources")

    assert response.status_code == 200
    body = response.json()
    assert body["research_id"] == str(job_id)
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert source["url"] == "https://example.com/robots"
    assert source["title"] == "Robotics Overview"
    assert source["domain"] == "example.com"
    assert len(source["evidence"]) == 1
    assert source["evidence"][0]["claim"] == "Humanoid robots are advancing quickly."
    assert source["evidence"][0]["excerpt"] == "Humanoid robots are advancing."
    assert source["evidence"][0]["locator"] == "paragraph 1"


async def test_get_sources_empty_for_new_job(client: httpx.AsyncClient) -> None:
    created = await _create_job(client, query="no sources yet")

    response = await client.get(f"/api/research/{created['id']}/sources")

    assert response.status_code == 200
    assert response.json()["sources"] == []


async def test_get_sources_for_missing_job_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/research/{uuid4()}/sources")
    assert response.status_code == 404


async def test_export_report_markdown(
    client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker,
) -> None:
    """A completed job's report downloads as a detailed Markdown document."""
    created = await _create_job(client, query="export me")
    job_id = UUID(created["id"])

    async with db_session_factory() as session:
        service = ResearchService(session)
        await service.start_research(job_id)
        task = await service.create_research_task(
            research_job_id=job_id, description="task"
        )
        evidence_service = EvidenceService(session)
        source = await evidence_service.save_source(
            research_job_id=job_id,
            research_task_id=task.id,
            url="https://example.com/robots",
            title="Robotics Overview",
            domain="example.com",
            content="Humanoid robots are advancing.",
        )
        await evidence_service.save_evidence(
            research_job_id=job_id,
            research_task_id=task.id,
            source_id=source.id,
            claim="Humanoid robots are advancing quickly.",
            excerpt="Humanoid robots are advancing.",
            locator="paragraph 1",
        )
        await service.complete_research(
            job_id,
            report=json.dumps(
                {
                    "title": "Robotics in 2026",
                    "summary": "A short summary.",
                    "sections": [
                        {
                            "heading": "Development",
                            "content": "Humanoid robots advance quickly.",
                            "citation_source_ids": [str(source.id)],
                        }
                    ],
                    "conclusion": "The field is moving fast.",
                }
            ),
        )

    response = await client.get(f"/api/research/{job_id}/report.md")

    assert response.status_code == 200
    assert "markdown" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert body.startswith("# Robotics in 2026")
    assert "**Query:** export me" in body
    assert "## Development" in body
    assert "Sources: [1]" in body
    assert "## Sources" in body
    assert "**Robotics Overview** — example.com" in body
    assert "<https://example.com/robots>" in body
    evidence_line = (
        "- Humanoid robots are advancing quickly. \u2014 \u201cHumanoid robots "
        "are advancing.\u201d (paragraph 1)"
    )
    assert evidence_line in body


async def test_export_report_rejected_for_pending_job(
    client: httpx.AsyncClient,
) -> None:
    created = await _create_job(client, query="still pending")
    job_id = created["id"]
    response = await client.get(f"/api/research/{job_id}/report.md")
    assert response.status_code == 409


async def _create_job(client: httpx.AsyncClient, query: str = "Research robotics") -> dict:
    response = await client.post(
        "/api/research", json={"query": query, "workflow_type": "deep_research"}
    )
    assert response.status_code == 202
    return response.json()


async def test_create_research_job_returns_202_pending(client: httpx.AsyncClient) -> None:
    body = await _create_job(client, query="Research the current state of humanoid robotics")

    assert UUID(body["id"])
    assert body["query"] == "Research the current state of humanoid robotics"
    assert body["workflow_type"] == "deep_research"
    assert body["status"] == "pending"
    assert body["error"] is None
    assert body["started_at"] is None
    assert body["completed_at"] is None
    assert body["created_at"] is not None


async def test_create_research_job_uses_default_workflow(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/research", json={"query": "only query"})
    assert response.status_code == 202
    assert response.json()["workflow_type"] == "deep_research"


async def test_create_research_job_rejects_empty_query(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/research", json={"query": ""})
    assert response.status_code == 422

    response = await client.post("/api/research", json={})
    assert response.status_code == 422


async def test_get_research_job(client: httpx.AsyncClient) -> None:
    created = await _create_job(client, query="retrieve me")
    response = await client.get(f"/api/research/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["query"] == "retrieve me"
    assert body["status"] == "pending"


async def test_get_missing_research_job_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/research/{uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "research_job_not_found"
    assert "detail" in body


async def test_get_tasks_empty_for_new_job(client: httpx.AsyncClient) -> None:
    created = await _create_job(client, query="no tasks yet")
    response = await client.get(f"/api/research/{created['id']}/tasks")
    assert response.status_code == 200
    body = response.json()
    assert body["research_id"] == created["id"]
    assert body["tasks"] == []


async def test_get_tasks_returns_persisted_tasks(client: httpx.AsyncClient) -> None:
    created = await _create_job(client, query="with tasks")

    factory = get_session_factory()
    async with factory() as session:
        service = ResearchService(session)
        task = await service.create_research_task(
            research_job_id=UUID(created["id"]), description="planned sub-question"
        )
        task_id = str(task.id)

    response = await client.get(f"/api/research/{created['id']}/tasks")
    assert response.status_code == 200
    body = response.json()
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["id"] == task_id
    assert body["tasks"][0]["description"] == "planned sub-question"
    assert body["tasks"][0]["status"] == "pending"


async def test_get_tasks_for_missing_job_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/research/{uuid4()}/tasks")
    assert response.status_code == 404