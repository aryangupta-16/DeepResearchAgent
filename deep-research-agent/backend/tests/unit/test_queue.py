"""Unit tests for the Redis job queue (in-memory transport stub, no network)."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.queue.client import RedisJobQueue
from app.infrastructure.queue.tasks import ResearchJobTask


class _FakeRedis:
    """Minimal in-memory stand-in for redis.asyncio.Redis (list + kv ops)."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.kv: dict[str, str] = {}
        self.closed = False

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def blpop(self, keys: list[str], *, timeout: float = 0.0):
        for key in keys:
            values = self.lists.get(key)
            if values:
                return (key, values.pop(0))
        return None

    async def lpop(self, key: str):
        values = self.lists.get(key)
        if not values:
            return None
        return values.pop(0)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.kv[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.kv:
                del self.kv[key]
                removed += 1
        return removed

    async def exists(self, key: str) -> int:
        return 1 if key in self.kv else 0

    async def aclose(self) -> None:
        self.closed = True


def _task() -> ResearchJobTask:
    return ResearchJobTask(job_id=uuid.uuid4(), attempt=1)


async def test_enqueue_then_dequeue_round_trip() -> None:
    queue = RedisJobQueue(_FakeRedis())
    task = _task()

    await queue.enqueue(task)
    received = await queue.dequeue(timeout=0)

    assert received is not None
    assert received.job_id == task.job_id
    assert received.attempt == task.attempt


async def test_dequeue_returns_none_when_empty() -> None:
    queue = RedisJobQueue(_FakeRedis())

    assert await queue.dequeue(timeout=0) is None


async def test_dequeue_is_fifo() -> None:
    queue = RedisJobQueue(_FakeRedis())
    first, second = _task(), _task()

    await queue.enqueue(first)
    await queue.enqueue(second)

    assert (await queue.dequeue()).job_id == first.job_id
    assert (await queue.dequeue()).job_id == second.job_id


async def test_requeue_increments_attempt() -> None:
    queue = RedisJobQueue(_FakeRedis())
    task = _task()

    await queue.enqueue(task)
    received = await queue.dequeue()
    await queue.requeue(received)

    retried = await queue.dequeue()
    assert retried is not None
    assert retried.job_id == task.job_id
    assert retried.attempt == task.attempt + 1


async def test_acknowledge_is_safe_noop() -> None:
    queue = RedisJobQueue(_FakeRedis())
    await queue.acknowledge(_task())  # must not raise


async def test_lease_lifecycle() -> None:
    redis = _FakeRedis()
    queue = RedisJobQueue(redis)
    job_id = uuid.uuid4()

    await queue.start_lease(job_id)
    assert await redis.exists(f"research:inflight:{job_id}")

    await queue.renew_lease(job_id)
    assert await redis.exists(f"research:inflight:{job_id}")

    await queue.clear_lease(job_id)
    assert not await redis.exists(f"research:inflight:{job_id}")


async def test_close_closes_underlying_redis() -> None:
    redis = _FakeRedis()
    queue = RedisJobQueue(redis)

    await queue.close()

    assert redis.closed


def test_task_payload_serialization_shape() -> None:
    job_id = uuid.uuid4()
    task = ResearchJobTask(job_id=job_id)

    payload = task.model_dump_json()
    restored = ResearchJobTask.model_validate_json(payload)

    assert restored.job_id == job_id
    assert restored.attempt == 1
    # Only identity + attempt travel over the wire.
    assert set(ResearchJobTask.model_fields) == {"job_id", "attempt"}


def test_with_next_attempt_bumps_attempt_only() -> None:
    job_id = uuid.uuid4()
    task = ResearchJobTask(job_id=job_id, attempt=2)

    nxt = task.with_next_attempt()

    assert nxt is not task
    assert nxt.job_id == job_id
    assert nxt.attempt == 3


@pytest.mark.parametrize("bad", ["not json", '{"job_id": 123}', "{}"])
async def test_malformed_messages_are_dropped_not_raised(bad: str) -> None:
    redis = _FakeRedis()
    queue = RedisJobQueue(redis)
    await redis.rpush("research:queue", bad)

    assert await queue.dequeue(timeout=0) is None