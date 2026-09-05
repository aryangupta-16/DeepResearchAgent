"""Research job/task status enums and transition rules.

These enums are the single source of truth for research statuses: the ORM models
(infrastructure), the API schemas (Pydantic), and the service all reference them.
"""

from __future__ import annotations

from enum import StrEnum

from app.common.exceptions import ValidationError


class ResearchJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchJobStage(StrEnum):
    """Coarse execution stage for progress tracking (not a state machine).

    Stored as a plain string on ``research_jobs.stage``; derived from the deep
    research workflow nodes.
    """

    PLANNING = "planning"
    RESEARCHING = "researching"
    SYNTHESIZING = "synthesizing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


#: Allowed transitions per current status (empty set = terminal status).
JOB_STATUS_TRANSITIONS: dict[ResearchJobStatus, frozenset[ResearchJobStatus]] = {
    ResearchJobStatus.PENDING: frozenset(
        {ResearchJobStatus.RUNNING, ResearchJobStatus.FAILED, ResearchJobStatus.CANCELLED}
    ),
    ResearchJobStatus.RUNNING: frozenset(
        {ResearchJobStatus.COMPLETED, ResearchJobStatus.FAILED, ResearchJobStatus.CANCELLED}
    ),
    ResearchJobStatus.COMPLETED: frozenset(),
    ResearchJobStatus.FAILED: frozenset(),
    ResearchJobStatus.CANCELLED: frozenset(),
}

TASK_STATUS_TRANSITIONS: dict[ResearchTaskStatus, frozenset[ResearchTaskStatus]] = {
    ResearchTaskStatus.PENDING: frozenset(
        {ResearchTaskStatus.RUNNING, ResearchTaskStatus.FAILED, ResearchTaskStatus.CANCELLED}
    ),
    ResearchTaskStatus.RUNNING: frozenset(
        {ResearchTaskStatus.COMPLETED, ResearchTaskStatus.FAILED, ResearchTaskStatus.CANCELLED}
    ),
    ResearchTaskStatus.COMPLETED: frozenset(),
    ResearchTaskStatus.FAILED: frozenset(),
    ResearchTaskStatus.CANCELLED: frozenset(),
}


def validate_job_status_transition(
    current: ResearchJobStatus,
    new: ResearchJobStatus,
) -> None:
    """Raise :class:`ValidationError` if the job transition is not allowed."""
    _validate_transition(current, new, JOB_STATUS_TRANSITIONS, "research job")


def validate_task_status_transition(
    current: ResearchTaskStatus,
    new: ResearchTaskStatus,
) -> None:
    """Raise :class:`ValidationError` if the task transition is not allowed."""
    _validate_transition(current, new, TASK_STATUS_TRANSITIONS, "research task")


def _validate_transition(
    current: object,
    new: object,
    transitions: dict[object, frozenset[object]],
    label: str,
) -> None:
    allowed = transitions.get(current, frozenset())
    if new not in allowed:
        raise ValidationError(
            f"Cannot transition {label} from {current!r} to {new!r}."
        )