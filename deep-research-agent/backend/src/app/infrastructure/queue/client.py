"""Redis-backed job queue.

The queue sits between the API process and the worker. It is a *transport*, not a
source of truth: messages carry ``ResearchJobTask`` identity (job id + attempt),
and PostgreSQL owns all durable job state.

Reliability model (V1, deliberately simple):

- **enqueue** — ``RPUSH`` the serialized task onto ``research:queue``.
- **dequeue** — ``BLPOP`` (bounded wait). The message is atomically removed; a
  worker that dies after popping leaves the job ``running`` in PostgreSQL, which a
  lease + startup reconciliation detects and reclaims.
- **acknowledge** — no-op for V1 (BLPOP already removed the message). Kept in the
  interface so consumers read the same call shape a true ack-based transport needs.
- **requeue** — push a new task with ``attempt + 1`` (bounded retries).
- **lease** — ``research:inflight:<job_id>`` key with a TTL refreshed by the
  worker while it executes; used to detect/recover stale running jobs.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from redis.asyncio import Redis

from app.config.settings import get_settings
from app.infrastructure.queue.tasks import DocumentProcessingTask, ResearchJobTask
from app.observability.metrics import DEAD_LETTER_MESSAGES

logger = logging.getLogger(__name__)

#: Key prefix for the per-job "in-flight" lease.
_INFLIGHT_PREFIX = "research:inflight"


def dead_letter_queue_name(queue_name: str) -> str:
    """The dead-letter list for a given queue (``<queue>:dlq``)."""
    return f"{queue_name}:dlq"


def _parse_payload(payload: object) -> ResearchJobTask | DocumentProcessingTask | None:
    """Parse a raw queue payload into one of the known task types."""
    try:
        return ResearchJobTask.model_validate_json(payload)
    except ValueError:
        pass
    try:
        return DocumentProcessingTask.model_validate_json(payload)
    except ValueError as exc:  # pragma: no cover - defensive; malformed message
        logger.warning("Unparseable queue message: %s", exc)
        return None


class JobQueue(Protocol):
    """Contract the worker + submission path depend on (transport-agnostic)."""

    queue_name: str

    async def enqueue(self, task: ResearchJobTask) -> None: ...
    async def dequeue(self, *, timeout: float = 0.0) -> ResearchJobTask | None: ...
    async def acknowledge(self, task: ResearchJobTask) -> None: ...
    async def requeue(self, task: ResearchJobTask) -> None: ...
    async def start_lease(self, job_id: object) -> None: ...
    async def renew_lease(self, job_id: object) -> None: ...
    async def clear_lease(self, job_id: object) -> None: ...
    async def close(self) -> None: ...


class RedisJobQueue:
    """A simple reliable queue on top of a Redis list."""

    queue_name: str

    def __init__(
        self,
        redis: Redis,
        *,
        queue_name: str = "research:queue",
        lease_timeout: float = 90.0,
    ) -> None:
        self._redis = redis
        self.queue_name = queue_name
        self._lease_timeout = lease_timeout

    # ---- producer ----

    async def enqueue(self, task: ResearchJobTask) -> None:
        await self._redis.rpush(self.queue_name, task.model_dump_json())

    async def enqueue_raw(self, queue_name: str, task: Any) -> None:
        """Push any typed task onto an explicit queue (multi-queue dispatch)."""
        await self._redis.rpush(queue_name, task.model_dump_json())

    # ---- consumer ----

    async def dequeue(self, *, timeout: float = 0.0) -> ResearchJobTask | None:
        """Pop one research task; ``timeout > 0`` blocks up to that many seconds.

        ``timeout <= 0`` performs a single non-blocking poll (never waits), which
        keeps tests and manual sweeps deterministic. Unparseable payloads are
        dead-lettered instead of silently dropped.
        """
        if timeout and timeout > 0:
            popped = await self._redis.blpop([self.queue_name], timeout=timeout)
        else:
            popped = await self._redis.lpop(self.queue_name)
        if popped is None:
            return None
        payload = popped[1] if isinstance(popped, tuple) else popped
        task = _parse_payload(payload)
        if task is None:
            await self.dead_letter_raw(self.queue_name, payload, reason="unparseable payload")
            return None
        return task

    async def dequeue_any(
        self, queue_names: list[str], *, timeout: float = 0.0
    ) -> tuple[str, ResearchJobTask | DocumentProcessingTask] | None:
        """Pop from the first non-empty of ``queue_names`` (typed dispatch).

        Uses a single ``BLPOP`` across all registered queues so the generic worker
        stays transport-agnostic and simply routes by the queue a message came
        from.
        """
        if not queue_names:
            return None
        if timeout and timeout > 0:
            popped = await self._redis.blpop(list(queue_names), timeout=timeout)
        else:
            popped = await self._redis.lpop(list(queue_names))
        if popped is None:
            return None
        queue_name, payload = popped if isinstance(popped, tuple) else (self.queue_name, popped)
        task = _parse_payload(payload)
        if task is None:
            await self.dead_letter_raw(queue_name, payload, reason="unparseable payload")
            return None
        return queue_name, task

    async def acknowledge(self, task: ResearchJobTask) -> None:
        # BLPOP already removed the message; kept for interface symmetry.
        del task

    async def requeue(self, task: ResearchJobTask) -> None:
        await self.enqueue(task.with_next_attempt())

    # ---- dead-letter (poisoned messages; Phase A) ----

    def _dlq_name(self, queue_name: str) -> str:
        return dead_letter_queue_name(queue_name)

    async def dead_letter_raw(
        self, queue_name: str, payload: object, *, reason: str
    ) -> None:
        """Move an unparseable/raw message to the queue's dead-letter list.

        The entry is a JSON envelope carrying the origin queue, the reason, and
        the original payload verbatim, so the admin script can inspect or replay
        it once the cause is fixed. Failure to dead-letter is logged but never
        raised — losing a poisoned message must not take the worker down.
        """
        envelope = {
            "queue": queue_name,
            "reason": reason,
            "failed_at": datetime.now(UTC).isoformat(),
            "payload": payload if isinstance(payload, (str, bytes)) else str(payload),
        }
        try:
            await self._redis.rpush(self._dlq_name(queue_name), json.dumps(envelope))
            DEAD_LETTER_MESSAGES.labels(queue=queue_name).inc()
            logger.warning(
                "Dead-lettered message from %s (reason=%s)", queue_name, reason
            )
        except Exception:  # pragma: no cover - Redis unavailable mid-crash
            logger.exception("Failed to dead-letter message from %s", queue_name)

    async def list_dead_letters(self, queue_name: str, *, limit: int = 50) -> list[dict]:
        """Inspect dead-lettered envelopes, oldest first (admin tooling)."""

        raw = await self._redis.lrange(self._dlq_name(queue_name), 0, limit - 1)
        entries: list[dict] = []
        for item in raw:
            try:
                entries.append(json.loads(item))
            except ValueError:
                entries.append({"queue": queue_name, "reason": "corrupt envelope",
                                "payload": str(item)})
        return entries

    async def requeue_dead_letter(self, queue_name: str) -> int:
        """Move every dead-lettered message back onto its origin queue.

        Returns the number of messages requeued. Entries whose payload still
        fails to parse are re-dead-lettered by the consumer (self-healing loop).
        """
        dlq = self._dlq_name(queue_name)
        moved = 0
        while True:
            payload = await self._redis.lpop(dlq)
            if payload is None:
                break
            raw = payload[1] if isinstance(payload, tuple) else payload
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                envelope = json.loads(raw)
            except ValueError:
                continue
            inner = envelope.get("payload", "")
            await self._redis.rpush(queue_name, inner)
            moved += 1
        return moved

    async def purge_dead_letter(self, queue_name: str) -> int:
        """Delete every dead-lettered message for a queue; returns count removed."""
        return int(await self._redis.delete(self._dlq_name(queue_name)) or 0)

    # ---- depth (queue health metric) ----

    async def depth(self, queue_name: str | None = None) -> int:
        """Number of messages currently waiting in a queue (or its DLQ)."""
        name = queue_name or self.queue_name
        return int(await self._redis.llen(name) or 0)

    # ---- lease (worker heartbeat; stale-job recovery) ----

    async def start_lease(self, job_id: object) -> None:
        await self._redis.set(
            f"{_INFLIGHT_PREFIX}:{job_id}", "1", ex=self._lease_timeout
        )

    async def renew_lease(self, job_id: object) -> None:
        await self._redis.set(
            f"{_INFLIGHT_PREFIX}:{job_id}", "1", ex=self._lease_timeout
        )

    async def clear_lease(self, job_id: object) -> None:
        await self._redis.delete(f"{_INFLIGHT_PREFIX}:{job_id}")

    # ---- lifecycle ----

    async def close(self) -> None:
        await self._redis.aclose()


def get_queue_client() -> JobQueue:
    """Factory: build the configured research queue client from settings."""
    from app.infrastructure.cache.redis import build_redis_client

    settings = get_settings()
    return RedisJobQueue(
        build_redis_client(),
        queue_name=settings.research_queue_name,
        lease_timeout=settings.research_job_lease_timeout,
    )


def get_document_queue_client() -> JobQueue:
    """Factory: build the document-processing queue client from settings."""
    from app.infrastructure.cache.redis import build_redis_client

    settings = get_settings()
    return RedisJobQueue(
        build_redis_client(),
        queue_name=settings.document_queue_name,
        lease_timeout=settings.research_job_lease_timeout,
    )