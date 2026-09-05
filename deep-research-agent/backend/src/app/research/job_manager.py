"""Research job manager (placeholder)."""

from __future__ import annotations


class JobManager:
    """Lives at the boundary between the API and the background worker.

    Hands off long-running research runs to the worker queue and reports status.
    """

    async def enqueue(self, run_id: str) -> None:
        raise NotImplementedError("JobManager not implemented yet.")