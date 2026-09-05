"""Task definitions shared by API and worker processes.

Both processes ship in the same codebase, so task payloads are defined exactly
once here. Redis carries entity identity + execution metadata; PostgreSQL is
always the source of truth.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

#: Queue where research job ids are pushed (`research:queue` by default).
DEFAULT_RESEARCH_QUEUE = "research:queue"
#: Queue where document processing tasks are pushed (`documents:queue`).
DEFAULT_DOCUMENT_QUEUE = "documents:queue"


class ResearchJobTask(BaseModel):
    """Payload for one research job execution attempt.

    Only job identity and the attempt number travel through Redis — the worker
    loads the full :class:`ResearchJob` from PostgreSQL using ``job_id``.
    """

    job_id: UUID
    attempt: int = Field(default=1, ge=1)

    def with_next_attempt(self) -> ResearchJobTask:
        """Return a new task for the next attempt of the same job."""
        return ResearchJobTask(job_id=self.job_id, attempt=self.attempt + 1)


class DocumentProcessingTask(BaseModel):
    """Payload for one document processing attempt."""

    document_id: UUID
    attempt: int = Field(default=1, ge=1)

    def with_next_attempt(self) -> DocumentProcessingTask:
        return DocumentProcessingTask(document_id=self.document_id, attempt=self.attempt + 1)