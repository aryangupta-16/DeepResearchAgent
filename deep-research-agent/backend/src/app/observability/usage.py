"""Per-job token usage accounting (Phase A3).

Providers report token usage on every response; this module buffers those
events with their *correlation context* (``job_id`` from the observability
contextvars) so the worker can persist them to the ``job_usage`` table without
threading a database session through the entire agent/LLM stack.

Design: the provider calls :func:`record_llm_usage` (pure, in-memory, never
raises); the worker drains the buffer via :func:`drain_usage_events` at safe
commit points (after each attempt + during reconciliation) and persists it
through :class:`app.research.usage_service.UsageService`. Events recorded
outside a job context (e.g. chat) are attributed to ``owner_scope`` callers
and intentionally not persisted here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from uuid import UUID

from app.guardrails.budget import budget_tracker
from app.observability.context import job_id_var


@dataclass(frozen=True)
class UsageEvent:
    """One LLM call's token usage, attributed to a research job when known."""

    job_id: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


_buffer: list[UsageEvent] = []
_lock = threading.Lock()


def record_llm_usage(
    *, provider: str, model: str, prompt_tokens: int, completion_tokens: int
) -> None:
    """Buffer one LLM call's usage for persistence (never raises).

    Events without a bound ``job_id`` context (API-side calls, chat) are
    dropped — deep-research cost accounting is per-job by design.
    """
    job_id = job_id_var.get()
    if not job_id or (prompt_tokens <= 0 and completion_tokens <= 0):
        return
    total = prompt_tokens + completion_tokens
    event = UsageEvent(
        job_id=job_id,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    with _lock:
        _buffer.append(event)
    # Phase B2 cost ceiling: the same funnel feeds the live per-job budget so
    # the research loop can halt a runaway job between tasks. Never raises.
    try:
        budget_tracker.record(UUID(job_id), total)
    except (ValueError, AttributeError):
        pass


def drain_usage_events() -> list[UsageEvent]:
    """Atomically remove and return all buffered events (worker-side flush)."""
    with _lock:
        events, _buffer[:] = list(_buffer), []
    return events


def buffered_usage_count() -> int:
    """Current buffer size (exposed for tests and health diagnostics)."""
    with _lock:
        return len(_buffer)
