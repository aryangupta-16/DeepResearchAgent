"""Per-job cost accounting service (Phase A3).

Bridges the in-memory usage buffer (:mod:`app.observability.usage`) to the
persistent ``job_usage`` ledger. The worker calls :meth:`flush_buffered_usage`
at safe commit points — after each attempt and in the reconciliation sweep —
so token costs are captured even for jobs that later fail or retry.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.job_usage import JobUsage
from app.infrastructure.database.repositories.job_usage import JobUsageRepository
from app.observability.usage import drain_usage_events

logger = logging.getLogger(__name__)


class UsageService:
    """Persists buffered per-job LLM usage events."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = JobUsageRepository(session)

    async def flush_buffered_usage(self) -> int:
        """Drain the in-memory buffer and persist rows; returns count written.

        Never raises: usage accounting must not fail a running job. On error
        the events are dropped with a warning (metrics already captured the
        token counts, so observability is not lost).
        """
        events = drain_usage_events()
        if not events:
            return 0
        try:
            rows = [
                JobUsage(
                    job_id=UUID(event.job_id),
                    provider=event.provider,
                    model=event.model,
                    prompt_tokens=event.prompt_tokens,
                    completion_tokens=event.completion_tokens,
                )
                for event in events
            ]
            return await self._repo.add_many(rows)
        except Exception:
            logger.warning(
                "Failed to persist %d usage events", len(events), exc_info=True
            )
            return 0

    async def totals_for_job(self, job_id: UUID) -> dict[str, int]:
        return await self._repo.totals_for_job(job_id)
