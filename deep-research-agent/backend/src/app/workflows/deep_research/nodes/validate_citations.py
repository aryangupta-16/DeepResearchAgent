"""Citation validation node.

Gate between synthesis and finalize:

- validate every source id cited by the report against the evidence store,
- on success: continue to ``finalize`` (job → completed),
- on failure: raise :class:`CitationValidationError` (job → failed).

No automatic report repair in V1.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError

from app.agents.synthesizer.schemas import ResearchReport
from app.common.exceptions import CitationValidationError
from app.research.enums import ResearchJobStage
from app.workflows.deep_research.state import ResearchState

if TYPE_CHECKING:  # pragma: no cover
    from uuid import UUID

    from app.agents.citation_validator.agent import CitationValidatorAgent
    from app.research.service import ResearchService


logger = logging.getLogger(__name__)


async def validate_citations(
    state: ResearchState,
    *,
    validator: CitationValidatorAgent,
    research_service: ResearchService,
) -> ResearchState:
    """Verify the report's citations resolve to real, in-job sources with evidence."""
    await research_service.mark_job_stage(UUID(state.run_id), ResearchJobStage.VALIDATING)

    if not state.final_report:
        if not state.task_results:
            # Upstream research produced no results (e.g. every task failed).
            # finalize will fail the job; this is NOT a citation failure.
            return state.model_copy(update={"status": "failed"})
        raise CitationValidationError("Citation validation failed: no report to validate.")

    try:
        report = ResearchReport.model_validate_json(state.final_report)
    except ValidationError as exc:
        raise CitationValidationError(
            "Citation validation failed: stored report is not a valid ResearchReport."
        ) from exc

    result = await validator.run(report=report, research_job_id=UUID(state.run_id))
    if not result.valid:
        details = "; ".join(f"{i.source_id}: {i.message}" for i in result.issues)
        logger.warning(
            "Citation validation failed job=%s issues=%s", state.run_id, details
        )
        raise CitationValidationError(f"Citation validation failed: {details}")

    logger.info(
        "Citation validation passed job=%s sources=%d",
        state.run_id,
        len(result.checked_source_ids),
    )
    return state.model_copy(update={"status": "validated"})