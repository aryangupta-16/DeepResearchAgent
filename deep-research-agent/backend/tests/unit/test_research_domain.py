"""Unit tests for research status enums and transition rules."""

import pytest

from app.common.exceptions import ValidationError
from app.research.enums import (
    ResearchJobStatus,
    ResearchTaskStatus,
    validate_job_status_transition,
    validate_task_status_transition,
)


def test_job_status_values() -> None:
    assert [status.value for status in ResearchJobStatus] == [
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]


def test_task_status_values() -> None:
    assert [status.value for status in ResearchTaskStatus] == [
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]


def test_pending_job_can_start_running() -> None:
    validate_job_status_transition(ResearchJobStatus.PENDING, ResearchJobStatus.RUNNING)


def test_pending_job_can_be_cancelled() -> None:
    validate_job_status_transition(
        ResearchJobStatus.PENDING, ResearchJobStatus.CANCELLED
    )


def test_running_job_can_complete() -> None:
    validate_job_status_transition(ResearchJobStatus.RUNNING, ResearchJobStatus.COMPLETED)


def test_running_job_can_fail() -> None:
    validate_job_status_transition(ResearchJobStatus.RUNNING, ResearchJobStatus.FAILED)


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (ResearchJobStatus.COMPLETED, ResearchJobStatus.CANCELLED),
        (ResearchJobStatus.COMPLETED, ResearchJobStatus.RUNNING),
        (ResearchJobStatus.FAILED, ResearchJobStatus.RUNNING),
        (ResearchJobStatus.CANCELLED, ResearchJobStatus.RUNNING),
        (ResearchJobStatus.PENDING, ResearchJobStatus.COMPLETED),
    ],
)
def test_invalid_job_transitions_raise(
    current: ResearchJobStatus, next_status: ResearchJobStatus
) -> None:
    with pytest.raises(ValidationError):
        validate_job_status_transition(current, next_status)


def test_pending_task_can_run() -> None:
    validate_task_status_transition(ResearchTaskStatus.PENDING, ResearchTaskStatus.RUNNING)


def test_running_task_can_complete() -> None:
    validate_task_status_transition(ResearchTaskStatus.RUNNING, ResearchTaskStatus.COMPLETED)


def test_running_task_can_be_cancelled() -> None:
    validate_task_status_transition(
        ResearchTaskStatus.RUNNING, ResearchTaskStatus.CANCELLED
    )


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (ResearchTaskStatus.PENDING, ResearchTaskStatus.COMPLETED),
        (ResearchTaskStatus.COMPLETED, ResearchTaskStatus.CANCELLED),
        (ResearchTaskStatus.CANCELLED, ResearchTaskStatus.RUNNING),
    ],
)
def test_invalid_task_transitions_raise(
    current: ResearchTaskStatus, next_status: ResearchTaskStatus
) -> None:
    with pytest.raises(ValidationError):
        validate_task_status_transition(current, next_status)