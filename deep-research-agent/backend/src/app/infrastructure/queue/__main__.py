"""Deep research agent worker entrypoint.

Run with: ``uv run python -m app.infrastructure.queue.workers``
"""

from app.infrastructure.queue.workers import worker_main

if __name__ == "__main__":
    worker_main()