"""ORM models (SQLAlchemy).

Importing this package registers every model on the shared declarative base so
that Alembic can discover them.
"""

from app.infrastructure.database.models.conversation import ChatMessage, Conversation
from app.infrastructure.database.models.document import Document, DocumentChunk
from app.infrastructure.database.models.evidence import ResearchEvidence
from app.infrastructure.database.models.job_usage import JobUsage
from app.infrastructure.database.models.memory import Memory
from app.infrastructure.database.models.research_job import ResearchJob
from app.infrastructure.database.models.research_outbox import ResearchJobOutbox
from app.infrastructure.database.models.research_source import ResearchSource
from app.infrastructure.database.models.research_task import ResearchTask

__all__ = [
    "ResearchJob",
    "ResearchTask",
    "ResearchSource",
    "ResearchEvidence",
    "ResearchJobOutbox",
    "Document",
    "DocumentChunk",
    "Memory",
    "JobUsage",
    "Conversation",
    "ChatMessage",
]