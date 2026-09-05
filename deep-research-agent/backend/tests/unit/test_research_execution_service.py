"""Unit tests for the research execution service (fakes only, no DB/Redis)."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.queue.tasks import ResearchJobTask
from app.research.enums import ResearchJobStatus
from app.research.execution_service import (
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_RETRY,
    OUTCOME_SKIPPED,
    ResearchExecutionService,
)


class _FakeRunner:
    """In-memory stand-in for the ResearchService execution surface."""

    def __init__(self, *, initial_status: ResearchJobStatus = ResearchJobStatus.PENDING) -> None:
        self.status = initial_status
        self.claims: list[int] = []
        self.resets = 0
        self.failures: list[str] = []
        self.closed = False
        self.workflow_calls = 0

    async def get_research_job(self, research_job_id):
        return type(
            "Job", (), {"id": research_job_id, "status": self.status}
        )()

    async def claim_for_running(self, research_job_id, *, attempt: int) -> bool:
        if self.status != ResearchJobStatus.PENDING:
            return False
        self.claims.append(attempt)
        self.status = ResearchJobStatus.RUNNING
        return True

    async def reset_job_to_pending(self, research_job_id) -> bool:
        self.resets += 1
        self.status = ResearchJobStatus.PENDING
        return True

    async def fail_research(self, research_job_id, *, error: str) -> None:
        self.failures.append(error)
        self.status = ResearchJobStatus.FAILED

    async def mark_job_stage(self, *args, **kwargs) -> None: ...
    async def update_job_progress(self, *args, **kwargs) -> None: ...

    def build_workflow(self, llm_provider=None):
        raise AssertionError("build_workflow must not be called when factory injected")

    async def close(self) -> None:
        self.closed = True


class _FakeWorkflow:
    def __init__(self, runner: _FakeRunner, *, outcome: str = "completed") -> None:
        self._runner = runner
        self._outcome = outcome
        self.run_calls: list[object] = []

    async def run(self, research_job_id):
        self.run_calls.append(research_job_id)
        self._runner.workflow_calls += 1
        if self._outcome == "raise":
            raise RuntimeError("simulated workflow crash")
        if self._outcome == "fail":
            self._runner.status = ResearchJobStatus.FAILED
            return "failed-state"
        self._runner.status = ResearchJobStatus.COMPLETED
        return "completed-state"


def _service(runner: _FakeRunner, workflow: _FakeWorkflow, *, max_retries: int = 2):
    return ResearchExecutionService(
        runner_factory=lambda: runner,
        workflow_factory=lambda r: workflow,
        max_retries=max_retries,
    )


def _task(*, attempt: int = 1) -> ResearchJobTask:
    return ResearchJobTask(job_id=uuid.uuid4(), attempt=attempt)


async def test_pending_claimed_then_completed() -> None:
    runner = _FakeRunner()
    workflow = _FakeWorkflow(runner)
    service = _service(runner, workflow)

    outcome = await service.execute(_task())

    assert outcome == OUTCOME_COMPLETED
    assert runner.status == ResearchJobStatus.COMPLETED
    assert runner.claims == [1]
    assert workflow.run_calls


async def test_non_pending_job_is_skipped() -> None:
    for status in (
        ResearchJobStatus.RUNNING,
        ResearchJobStatus.COMPLETED,
        ResearchJobStatus.FAILED,
    ):
        runner = _FakeRunner(initial_status=status)
        workflow = _FakeWorkflow(runner)
        service = _service(runner, workflow)
        task = _task()

        outcome = await service.execute(task)

        assert outcome == OUTCOME_SKIPPED
        assert workflow.run_calls == []  # never executed twice


async def test_workflow_exception_is_retried() -> None:
    runner = _FakeRunner()
    workflow = _FakeWorkflow(runner, outcome="raise")
    service = _service(runner, workflow, max_retries=2)

    outcome = await service.execute(_task(attempt=1))

    assert outcome == OUTCOME_RETRY
    assert runner.resets == 1
    assert runner.failures == []
    assert runner.status == ResearchJobStatus.PENDING


async def test_retry_exhaustion_fails_the_job() -> None:
    runner = _FakeRunner()
    workflow = _FakeWorkflow(runner, outcome="raise")
    service = _service(runner, workflow, max_retries=2)

    outcome = await service.execute(_task(attempt=2))

    assert outcome == OUTCOME_FAILED
    assert runner.resets == 0
    assert len(runner.failures) == 1
    assert runner.status == ResearchJobStatus.FAILED


async def test_graceful_workflow_failure_is_permanent() -> None:
    runner = _FakeRunner()
    workflow = _FakeWorkflow(runner, outcome="fail")
    service = _service(runner, workflow, max_retries=3)

    outcome = await service.execute(_task(attempt=1))

    assert outcome == OUTCOME_FAILED
    # Graceful failure (finalize marked it failed) is NOT retried.
    assert runner.resets == 0


async def test_runner_session_closed_after_execution() -> None:
    runner = _FakeRunner()
    service = _service(runner, _FakeWorkflow(runner))

    await service.execute(_task())

    assert runner.closed is True


@pytest.mark.parametrize("outcome", ["completed", "retry", "failed", "skipped"])
async def test_close_called_even_on_all_outcomes(outcome: str) -> None:
    class _BoomRunner(_FakeRunner):
        async def claim_for_running(self, research_job_id, *, attempt): 
            return True

    runner = _BoomRunner()
    workflow = _FakeWorkflow(runner, outcome=outcome if outcome != "skipped" else "raise")
    service = _service(runner, workflow, max_retries=5)

    try:
        await service.execute(_task())
    except Exception:  # pragma: no cover - defensive
        pass

    assert runner.closed is True