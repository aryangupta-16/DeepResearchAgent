"""Task queue infrastructure (shared by API and worker processes).

The queue is a Redis-backed *transport* for research job ids; PostgreSQL remains
the source of truth for job/task/evidence state.
"""

from app.infrastructure.queue.client import JobQueue, RedisJobQueue, get_queue_client
from app.infrastructure.queue.handlers import (
    ACTION_ACK,
    ACTION_RETRY,
    JobHandler,
    ResearchJobHandler,
)
from app.infrastructure.queue.tasks import DEFAULT_RESEARCH_QUEUE, ResearchJobTask

__all__ = [
    "JobQueue",
    "RedisJobQueue",
    "get_queue_client",
    "ResearchJobTask",
    "DEFAULT_RESEARCH_QUEUE",
    "JobHandler",
    "ResearchJobHandler",
    "ACTION_ACK",
    "ACTION_RETRY",
]