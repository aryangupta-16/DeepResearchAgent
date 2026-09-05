"""Research sub-task manager (placeholder)."""

from __future__ import annotations


class TaskManager:
    """Splits a research run into parallel, trackable sub-tasks."""

    async def create(self, run_id: str, sub_questions: list[str]) -> list[str]:
        raise NotImplementedError("TaskManager not implemented yet.")