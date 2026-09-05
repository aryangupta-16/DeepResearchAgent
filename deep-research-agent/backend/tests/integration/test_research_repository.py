"""PostgreSQL-backed repository/service integration tests.

These require a reachable PostgreSQL (see ``tests/integration/README.md``).
Tests are skipped automatically when the database is unavailable.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.models import ResearchJob, ResearchTask
from app.infrastructure.database.repositories import (
    ResearchJobRepository,
    ResearchTaskRepository,
)
from app.research.enums import ResearchJobStatus, ResearchTaskStatus
from app.research.service import ResearchService


async def test_job_repository_create_get_update(
    db_session: AsyncSession,
) -> None:
    repository = ResearchJobRepository(db_session)
    job = ResearchJob(query="Capital markets in emerging markets", workflow_type="deep_research")
    await repository.create(job)
    await db_session.commit()
    job_id = job.id

    found = await repository.get_by_id(job_id)
    assert found is not None
    assert found.id == job_id
    assert found.status == ResearchJobStatus.PENDING
    assert found.created_at is not None

    found.status = ResearchJobStatus.RUNNING
    found.started_at = found.created_at
    await repository.update(found)
    await db_session.commit()

    refreshed = await repository.get_by_id(job_id)
    assert refreshed is not None
    assert refreshed.status == ResearchJobStatus.RUNNING
    assert refreshed.started_at is not None


async def test_job_repository_get_by_id_missing(db_session: AsyncSession) -> None:
    repository = ResearchJobRepository(db_session)
    assert await repository.get_by_id(uuid.uuid4()) is None


async def test_job_repository_list_by_status(db_session: AsyncSession) -> None:
    repository = ResearchJobRepository(db_session)
    for label in ("a", "b", "c"):
        job = ResearchJob(query=label, status=ResearchJobStatus.RUNNING)
        db_session.add(job)
    await db_session.commit()

    running = await repository.list_by_status(ResearchJobStatus.RUNNING)
    assert len(running) == 3

    pending = await repository.list_by_status(ResearchJobStatus.PENDING)
    assert pending == []

    all_jobs = await repository.list_by_status()
    assert len(all_jobs) == 3


async def test_task_repository_create_and_list_by_job(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        job_repository = ResearchJobRepository(session)
        job = ResearchJob(query="Root job")
        await job_repository.create(job)

        task_repository = ResearchTaskRepository(session)
        first = ResearchTask(research_job_id=job.id, description="sub-question one")
        second = ResearchTask(research_job_id=job.id, description="sub-question two")
        await task_repository.create(first)
        await task_repository.create(second)
        await session.commit()

        tasks = await task_repository.list_by_research_job(job.id)
        assert {task.description for task in tasks} == {
            "sub-question one",
            "sub-question two",
        }


async def test_task_repository_update_status(db_session: AsyncSession) -> None:
    job_repository = ResearchJobRepository(db_session)
    job = ResearchJob(query="job")
    await job_repository.create(job)
    await db_session.commit()

    task_repository = ResearchTaskRepository(db_session)
    task = ResearchTask(research_job_id=job.id, description="task")
    await task_repository.create(task)
    await db_session.commit()

    task.status = ResearchTaskStatus.RUNNING
    await task_repository.update(task)
    await db_session.commit()

    found = await task_repository.get_by_id(task.id)
    assert found is not None
    assert found.status == ResearchJobStatus.RUNNING


async def test_deleting_job_cascades_to_tasks(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        job_repository = ResearchJobRepository(session)
        job = ResearchJob(query="cascade me")
        await job_repository.create(job)

        task_repository = ResearchTaskRepository(session)
        await task_repository.create(
            ResearchTask(research_job_id=job.id, description="task")
        )
        await session.commit()

        await session.delete(job)
        await session.commit()

        assert await task_repository.list_by_research_job(job.id) == []


async def test_service_create_and_fetch_job(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        service = ResearchService(session)
        job = await service.create_research_job(query="Service level test")
        assert job.status == ResearchJobStatus.PENDING
        assert job.workflow_type == "deep_research"

        fetched = await service.get_research_job(job.id)
        assert fetched.id == job.id

        task = await service.create_research_task(
            research_job_id=job.id, description="planned question"
        )
        tasks = await service.get_research_tasks(job.id)
        assert [t.id for t in tasks] == [task.id]


async def test_service_get_missing_job_raises_not_found(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.common.exceptions import ResearchJobNotFoundError

    async with db_session_factory() as session:
        service = ResearchService(session)
        with pytest.raises(ResearchJobNotFoundError):
            await service.get_research_job(uuid.uuid4())