"""Unit tests for the generic queue worker loop (fakes only, no Redis/DB)."""

from __future__ import annotations

import uuid

from app.infrastructure.queue.handlers import ACTION_ACK, ACTION_RETRY
from app.infrastructure.queue.tasks import ResearchJobTask
from app.infrastructure.queue.workers import process_next


class _FakeQueue:
    def __init__(self) -> None:
        self.pending: list[ResearchJobTask] = []
        self.acked: list[ResearchJobTask] = []
        self.requeued: list[ResearchJobTask] = []
        self.fail_next_dequeue = False

    async def enqueue(self, task: ResearchJobTask) -> None:
        self.pending.append(task)

    async def dequeue(self, *, timeout: float = 0.0):
        if self.fail_next_dequeue:
            self.fail_next_dequeue = False
            raise ConnectionError("redis down")
        if self.pending:
            return self.pending.pop(0)
        return None

    async def acknowledge(self, task: ResearchJobTask) -> None:
        self.acked.append(task)

    async def requeue(self, task: ResearchJobTask) -> None:
        nxt = task.with_next_attempt()
        self.requeued.append(nxt)
        self.pending.append(nxt)


class _FakeHandler:
    def __init__(self, action: str = ACTION_ACK) -> None:
        self.action = action
        self.handled: list[ResearchJobTask] = []

    async def handle(self, task: ResearchJobTask) -> str:
        self.handled.append(task)
        return self.action


async def test_worker_acks_successful_job() -> None:
    queue = _FakeQueue()
    handler = _FakeHandler(ACTION_ACK)
    task = ResearchJobTask(job_id=uuid.uuid4(), attempt=1)
    await queue.enqueue(task)

    did_work = await process_next(queue, handler, timeout=0)

    assert did_work is True
    assert handler.handled[0].job_id == task.job_id
    assert [t.job_id for t in queue.acked] == [task.job_id]
    assert not queue.requeued
    assert not queue.pending


async def test_worker_requeues_failed_job_with_next_attempt() -> None:
    queue = _FakeQueue()
    handler = _FakeHandler(ACTION_RETRY)
    task = ResearchJobTask(job_id=uuid.uuid4(), attempt=1)
    await queue.enqueue(task)

    await process_next(queue, handler, timeout=0)

    assert len(queue.requeued) == 1
    assert queue.requeued[0].attempt == 2
    assert not queue.acked
    # The retried message is back in the pending list.
    assert queue.pending and queue.pending[0].attempt == 2


async def test_worker_returns_false_when_queue_empty() -> None:
    queue = _FakeQueue()
    handler = _FakeHandler()

    assert await process_next(queue, handler, timeout=0) is False
    assert not handler.handled


async def test_worker_swallows_transport_errors_and_continues() -> None:
    """A Redis failure during dequeue must not crash the worker loop."""
    import asyncio

    from app.infrastructure.queue.workers import run_worker

    stop_event = asyncio.Event()

    class _OneShotFailQueue(_FakeQueue):
        def __init__(self) -> None:
            super().__init__()

        async def dequeue(self, *, timeout: float = 0.0):
            if self.fail_next_dequeue:
                self.fail_next_dequeue = False
                stop_event.set()  # end the loop after the failure
                raise ConnectionError("redis down")
            return await super().dequeue(timeout=timeout)

    queue = _OneShotFailQueue()
    handler = _FakeHandler()
    queue.fail_next_dequeue = True

    # run_worker catches the transport error and exits cleanly on stop_event.
    await asyncio.wait_for(
        run_worker(queue, handler, stop_event=stop_event, poll_timeout=0.0),
        timeout=2.0,
    )
    assert not handler.handled


async def test_worker_processes_messages_in_order() -> None:
    queue = _FakeQueue()
    handler = _FakeHandler(ACTION_ACK)
    ids = [uuid.uuid4() for _ in range(3)]
    for job_id in ids:
        await queue.enqueue(ResearchJobTask(job_id=job_id))

    for _ in ids:
        await process_next(queue, handler, timeout=0)

    assert [t.job_id for t in handler.handled] == ids