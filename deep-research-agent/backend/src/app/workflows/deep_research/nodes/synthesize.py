"""Synthesize node.

1. Collect completed task results from state.
2. Load the job's persisted sources (via the evidence service) as a source index.
3. Invoke SynthesizerAgent with the grounded results + source index.
4. Store the citation-aware final report in state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.config.settings import get_settings
from app.research.enums import ResearchJobStage
from app.workflows.deep_research.state import ResearchState

if TYPE_CHECKING:  # pragma: no cover
    from app.agents.synthesizer.agent import SynthesizerAgent
    from app.evidence.service import EvidenceService
    from app.research.service import ResearchService


async def synthesize(
    state: ResearchState,
    *,
    synthesizer: SynthesizerAgent,
    evidence_service: EvidenceService,
    research_service: ResearchService,
) -> ResearchState:
    """Combine task results + evidence into the final citation-aware report."""
    if not state.task_results:
        errors = [*state.errors, "No research results to synthesize."]
        return state.model_copy(update={"errors": errors})

    await research_service.mark_job_stage(UUID(state.run_id), ResearchJobStage.SYNTHESIZING)

    sources = await evidence_service.list_sources_for_job(UUID(state.run_id))
    evidence_index: dict[str, dict[str, object]] = {}
    for source in sources:
        evidence_items = await evidence_service.list_evidence_for_source(source.id)
        evidence_index[str(source.id)] = {
            "title": source.title,
            "url": source.url,
            "domain": source.domain or "",
            # Verbatim excerpts give the synthesizer the raw material it needs
            # for a detailed narrative (not just one-line claims).
            "evidence": [
                {
                    "claim": item.claim,
                    "excerpt": (item.excerpt or "")[:700],
                    "locator": item.locator or "",
                }
                for item in evidence_items[:10]
            ],
        }

    report = await synthesizer.run(
        query=state.topic,
        results=state.task_results,
        evidence_index=evidence_index,
        max_tokens=get_settings().synthesis_max_tokens,
    )
    return state.model_copy(
        update={
            "final_report": report.model_dump_json(indent=2),
            "status": "synthesizing",
        }
    )