"""Hard per-job token budget (cost-ceiling guardrail).

The tracker is process-local: each research job runs inside exactly one worker
process, which is precisely where the token usage funnel
(:func:`app.observability.usage.record_llm_usage`) reports every LLM call.
Before each research task the workflow asks :meth:`JobBudgetTracker.ensure_within_budget`;
when the ceiling is crossed the job fails with a clear reason via the existing
graceful-failure path instead of silently overspending.

Design constraints:
- recording is a cheap dict increment under a lock (hot path — every LLM call),
- ``budget <= 0`` disables the ceiling (useful for tests/dev),
- per-worker-process accounting slightly *undercounts* retries that land on a
  different process — the persisted ``job_usage`` ledger (Phase A3) stays the
  source of truth for cost reporting; this guard is the live circuit breaker.
"""

from __future__ import annotations

import threading
from uuid import UUID

from app.common.exceptions import AppError


class BudgetExceededError(AppError):
    """Raised when a research job would exceed its hard token budget."""

    status_code = 400
    code = "job_budget_exceeded"


class JobBudgetTracker:
    """Tracks cumulative token usage per job and enforces a hard ceiling."""

    def __init__(self, *, default_budget: int = 250_000) -> None:
        self._default_budget = max(0, default_budget)
        self._lock = threading.Lock()
        self._usage: dict[UUID, int] = {}
        self._budgets: dict[UUID, int] = {}

    # -- configuration ---------------------------------------------------------

    def set_budget(self, job_id: UUID, budget: int) -> None:
        """Override the ceiling for one job (``<= 0`` disables it)."""
        with self._lock:
            self._budgets[job_id] = max(0, budget)

    # -- recording (called from the LLM usage funnel) ----------------------------

    def record(self, job_id: UUID, tokens: int) -> int:
        """Add consumed tokens to a job's tally; returns the new total.

        Never raises — enforcement is pull-based (:meth:`ensure_within_budget`)
        so the hot path stays exception-free and testable.
        """
        if tokens <= 0:
            return self.consumed(job_id)
        with self._lock:
            self._usage[job_id] = self._usage.get(job_id, 0) + tokens
            return self._usage[job_id]

    def consumed(self, job_id: UUID) -> int:
        with self._lock:
            return self._usage.get(job_id, 0)

    # -- enforcement (called from the research loop, before each task) -----------

    def ensure_within_budget(self, job_id: UUID) -> None:
        """Raise :class:`BudgetExceededError` when the job is over its ceiling."""
        with self._lock:
            budget = self._budgets.get(job_id, self._default_budget)
            used = self._usage.get(job_id, 0)
        if budget <= 0:  # disabled
            return
        if used >= budget:
            raise BudgetExceededError(
                f"Per-job token budget exhausted: {used} tokens used of a "
                f"{budget}-token ceiling. Increase the budget or narrow the query."
            )

    def remaining(self, job_id: UUID) -> int:
        """Tokens left before the ceiling (``-1`` when the budget is disabled)."""
        with self._lock:
            budget = self._budgets.get(job_id, self._default_budget)
            used = self._usage.get(job_id, 0)
        return -1 if budget <= 0 else max(0, budget - used)

    # -- lifecycle ---------------------------------------------------------------

    def forget(self, job_id: UUID) -> None:
        """Drop a finished job's tally (worker calls this in cleanup)."""
        with self._lock:
            self._usage.pop(job_id, None)
            self._budgets.pop(job_id, None)


#: Process-wide tracker used by the usage funnel and the research workflow.
budget_tracker = JobBudgetTracker()
