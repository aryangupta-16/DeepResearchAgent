"""Load context node.

Responsibilities:
1. Receive the ResearchJob ID from state.
2. Load the ResearchJob via the existing service/repository layer.
3. Populate graph state: research_job_id, query, current status.

The node never constructs SQLAlchemy sessions directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from app.workflows.deep_research.state import ResearchState

if TYPE_CHECKING:  # pragma: no cover
    from app.research.service import ResearchService

logger = logging.getLogger(__name__)


async def load_context(
    state: ResearchState,
    *,
    research_service: ResearchService,
) -> ResearchState:
    """Load the research job and seed workflow state from it.

    Phase 9: when memory is enabled, the job's owner's most relevant long-term
    memories are retrieved and injected as planner *context*. Memory failures
    (retrieval or usage tracking) are soft — they log and never fail the job.

    Raises:
        ResearchJobNotFoundError: if the job does not exist.
    """
    job = await research_service.get_research_job(UUID(state.run_id))

    # Phase 8: surface the job's document selection so later nodes can decide
    # whether to retrieve from uploaded documents.
    document_ids = [str(value) for value in (job.document_ids or [])]
    available_documents: list[str] = []
    if document_ids:
        from app.documents.repository import DocumentRepository

        repo = DocumentRepository(research_service.session)
        ready = {str(doc.id): doc.filename for doc in await repo.list_ready()}
        available_documents = [
            ready.get(document_id, "Unknown document") for document_id in document_ids
        ]

    memories = await _retrieve_memories(research_service, job)

    return state.model_copy(
        update={
            "run_id": str(job.id),
            "topic": job.query,
            "status": job.status.value,
            "document_ids": document_ids,
            "available_documents": available_documents,
            "memories": memories,
        }
    )


async def _retrieve_memories(research_service: ResearchService, job: object) -> list[object]:
    """Best-effort retrieval of the owner's relevant memories for this job.

    Never raises into the workflow: memory is an enhancement, not a dependency.
    """
    from app.config.settings import get_settings
    from app.memory.service import MemoryService

    settings = get_settings()
    if not settings.memory_enabled:
        return []

    try:
        memory_service = MemoryService(
            research_service.session,
            enabled=True,
            max_results=settings.memory_max_results,
        )
        memories = await memory_service.retrieve_relevant(
            job.query, owner_id=getattr(job, "owner_id", None) or "default"
        )
        if memories:
            # Telemetry only — must never break the job.
            await memory_service.mark_used([m.id for m in memories])
        return memories
    except Exception:
        logger.warning(
            "Memory retrieval skipped job=%s (continuing web/document research).",
            getattr(job, "id", "?"),
            exc_info=True,
        )
        return []