"""Unit tests for research service business validation (no database required)."""

import uuid

import pytest

from app.common.exceptions import ValidationError
from app.research.service import ResearchService


class _NoopSession:
    """Session stub that fails loudly if any database work is attempted.

    Used to prove business validation happens before persistence.
    """

    async def commit(self) -> None:
        raise AssertionError("commit should not be reached")

    async def rollback(self) -> None:
        raise AssertionError("rollback should not be reached")

    async def refresh(self, instance: object) -> None:
        raise AssertionError("refresh should not be reached")


async def test_create_research_job_rejects_blank_query_without_db() -> None:
    service = ResearchService(_NoopSession())  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        await service.create_research_job(query="   ")


async def test_create_research_task_rejects_blank_description_without_db() -> None:
    service = ResearchService(_NoopSession())  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        await service.create_research_task(
            research_job_id=uuid.uuid4(), description=""
        )