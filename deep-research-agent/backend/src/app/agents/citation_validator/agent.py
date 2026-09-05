"""Citation validator agent.

Validates *citation integrity*, not factual correctness. It checks that every
source id cited by a report:

- exists in the evidence store,
- belongs to the current research job, and
- has at least one supporting evidence item.

This is deliberately deterministic (no LLM) so the workflow gate is reliable.
"""

from __future__ import annotations

from uuid import UUID

from app.agents.citation_validator.schemas import (
    CitationIssue,
    CitationValidationResult,
)
from app.agents.synthesizer.schemas import ResearchReport
from app.common.exceptions import EvidenceNotFoundError
from app.evidence.service import EvidenceService


class CitationValidatorAgent:
    """Verifies citations in a report resolve to real, in-job evidence."""

    def __init__(self, evidence_service: EvidenceService) -> None:
        self._evidence = evidence_service

    async def run(
        self,
        *,
        report: ResearchReport,
        research_job_id: UUID,
    ) -> CitationValidationResult:
        cited: set[str] = set()
        for section in report.sections:
            cited.update(section.citation_source_ids)

        issues: list[CitationIssue] = []
        for raw_id in sorted(cited):
            try:
                source_id = UUID(raw_id)
            except (ValueError, AttributeError):
                issues.append(
                    CitationIssue(source_id=raw_id, message="invalid source id format")
                )
                continue

            try:
                source = await self._evidence.get_source(source_id)
            except EvidenceNotFoundError:
                issues.append(
                    CitationIssue(source_id=raw_id, message="missing source")
                )
                continue

            if source.research_job_id != research_job_id:
                issues.append(
                    CitationIssue(
                        source_id=raw_id,
                        message="source belongs to another research job",
                    )
                )
                continue

            evidence = await self._evidence.list_evidence_for_source(source.id)
            if not evidence:
                issues.append(
                    CitationIssue(
                        source_id=raw_id, message="source has no supporting evidence"
                    )
                )

        return CitationValidationResult(
            valid=not issues,
            issues=issues,
            checked_source_ids=sorted(cited),
        )