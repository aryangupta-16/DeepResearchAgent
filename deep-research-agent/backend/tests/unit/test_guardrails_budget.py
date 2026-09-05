"""Unit tests for the per-job token budget guardrail."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.guardrails.budget import BudgetExceededError, JobBudgetTracker


class TestJobBudget:
    def test_records_and_returns_totals(self) -> None:
        tracker = JobBudgetTracker(default_budget=100)
        job = uuid4()
        assert tracker.record(job, 40) == 40
        assert tracker.record(job, 30) == 70
        assert tracker.consumed(job) == 70
        tracker.forget(job)
        assert tracker.consumed(job) == 0

    def test_ignores_non_positive_tokens(self) -> None:
        tracker = JobBudgetTracker(default_budget=100)
        job = uuid4()
        assert tracker.record(job, 0) == 0
        assert tracker.record(job, -5) == 0

    def test_raises_when_budget_exhausted(self) -> None:
        tracker = JobBudgetTracker(default_budget=100)
        job = uuid4()
        tracker.record(job, 100)
        with pytest.raises(BudgetExceededError):
            tracker.ensure_within_budget(job)

    def test_passes_when_under_budget(self) -> None:
        tracker = JobBudgetTracker(default_budget=100)
        job = uuid4()
        tracker.record(job, 99)
        tracker.ensure_within_budget(job)  # no raise
        assert tracker.remaining(job) == 1

    def test_zero_budget_disables_ceiling(self) -> None:
        tracker = JobBudgetTracker(default_budget=0)
        job = uuid4()
        tracker.record(job, 10**9)
        tracker.ensure_within_budget(job)  # no raise
        assert tracker.remaining(job) == -1

    def test_per_job_budget_override(self) -> None:
        tracker = JobBudgetTracker(default_budget=1000)
        job = uuid4()
        tracker.set_budget(job, 50)
        tracker.record(job, 50)
        with pytest.raises(BudgetExceededError):
            tracker.ensure_within_budget(job)

    def test_jobs_are_isolated(self) -> None:
        tracker = JobBudgetTracker(default_budget=100)
        rich, poor = uuid4(), uuid4()
        tracker.set_budget(rich, 10_000)
        tracker.record(rich, 5_000)
        tracker.record(poor, 100)
        tracker.ensure_within_budget(rich)  # no raise
        with pytest.raises(BudgetExceededError):
            tracker.ensure_within_budget(poor)

    def test_error_message_is_actionable(self) -> None:
        tracker = JobBudgetTracker(default_budget=10)
        job = uuid4()
        tracker.record(job, 10)
        with pytest.raises(BudgetExceededError) as excinfo:
            tracker.ensure_within_budget(job)
        assert "budget" in str(excinfo.value).lower()
        assert "10" in str(excinfo.value)
