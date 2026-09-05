"""Log/tracing correlation context.

Small, dependency-light correlation layer built on :mod:`contextvars`, so
request/job/task identifiers automatically attach to every log line in the
same async task — including across ``await`` boundaries — without threading
them through every function signature manually.

The API writes ``request_id``; the queue handler copies ``job_id`` /
``task_id`` from the message payload into the worker task context.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

# One contextvar per correlated identifier. Each defaults to empty and only
# appears in logs when actually set — no noisy null fields.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "job_id", default=""
)
task_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "task_id", default=""
)


def new_request_id() -> str:
    """Generate a fresh request id (short, unique, log-friendly)."""
    return uuid.uuid4().hex[:12]


def current_context() -> dict[str, str]:
    """Snapshot of all set correlation ids (empty keys are omitted)."""
    context: dict[str, str] = {}
    for key, var in (
        ("request_id", request_id_var),
        ("job_id", job_id_var),
        ("task_id", task_id_var),
    ):
        value = var.get()
        if value:
            context[key] = value
    return context


def bind_request_context(request_id: str | None = None) -> str:
    """Bind a request id for the current task; returns the bound value.

    An incoming ``request_id`` (e.g. from an ``X-Request-ID`` header) is
    honored so traces can span client → API → worker.
    """
    resolved = request_id or new_request_id()
    request_id_var.set(resolved)
    return resolved


def bind_job_context(job_id: str, task_id: str = "") -> None:
    """Bind job/task identifiers for the current worker task."""
    job_id_var.set(job_id)
    task_id_var.set(task_id or "")


def clear_job_context() -> None:
    """Reset job/task bindings (used between worker task iterations)."""
    job_id_var.set("")
    task_id_var.set("")


@contextmanager
def bound_context(
    *,
    request_id: str | None = None,
    job_id: str | None = None,
    task_id: str | None = None,
) -> Iterator[dict[str, str]]:
    """Temporarily bind ids within a block; restores prior values on exit.

    Useful in tests and in one-shot scripts; long-lived request/task contexts
    should use :func:`bind_request_context` / :func:`bind_job_context`.
    """
    tokens = []
    if request_id is not None:
        tokens.append((request_id_var, request_id_var.set(request_id)))
    if job_id is not None:
        tokens.append((job_id_var, job_id_var.set(job_id)))
    if task_id is not None:
        tokens.append((task_id_var, task_id_var.set(task_id)))
    try:
        yield current_context()
    finally:
        for var, token in tokens:
            var.reset(token)
