"""PostgreSQL-backed tests for the deep research workflow (success + failure).

The workflow now includes a citation-validation gate between synthesis and
finalize, so the fakes below are wired with the real EvidenceService + real
CitationValidatorAgent.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.citation_validator.agent import CitationValidatorAgent
from app.agents.planner.schemas import ResearchPlan, ResearchPlanTask
from app.agents.researcher.schemas import ResearchResult
from app.agents.synthesizer.schemas import ResearchReport, ResearchReportSection
from app.common.exceptions import (
    CitationValidationError,
    ResearcherError,
)
from app.evidence.service import EvidenceService
from app.research.enums import ResearchJobStatus, ResearchTaskStatus
from app.research.service import ResearchService
from app.workflows.deep_research.workflow import DeepResearchWorkflow


class FakePlanner:
    async def run(
        self,
        topic: str,
        *,
        available_documents: list[str] | None = None,
        user_context: list[str] | None = None,
    ) -> ResearchPlan:
        return ResearchPlan(
            objective=topic,
            tasks=[
                ResearchPlanTask(description="Research companies"),
                ResearchPlanTask(description="Research technical advances"),
            ],
        )


class FakeResearcher:
    async def run(
        self,
        *,
        query: str,
        task: str,
        research_job_id: UUID,
        research_task_id: UUID,
        document_context: list[object] | None = None,
    ) -> ResearchResult:
        return ResearchResult(task=task, summary=f"Summary for {task}", findings=[])


class FailingResearcher:
    async def run(
        self,
        *,
        query: str,
        task: str,
        research_job_id: UUID,
        research_task_id: UUID,
        document_context: list[object] | None = None,
    ) -> ResearchResult:
        raise ResearcherError("simulated research failure")


class FakeSynthesizer:
    async def run(
        self,
        query: str,
        results: list[object],
        evidence_index: dict[str, object] | None = None,
        *,
        max_tokens: int | None = None,
    ) -> ResearchReport:
        return ResearchReport(
            title="Final report",
            summary="Summary",
            sections=[
                ResearchReportSection(heading="Overview", content="Content")
            ],
            conclusion="Conclusion",
        )


async def test_full_workflow_completes_job(
    db_session_factory: async_sessionmaker,
) -> None:
    async with db_session_factory() as session:
        service = ResearchService(session)
        evidence_service = EvidenceService(session)
        job = await service.create_research_job(query="Current state of robotics")
        await service.start_research(job.id)

        workflow = DeepResearchWorkflow(
            research_service=service,
            planner=FakePlanner(),
            researcher=FakeResearcher(),
            synthesizer=FakeSynthesizer(),
            citation_validator=CitationValidatorAgent(evidence_service),
            evidence_service=evidence_service,
        )
        result = await workflow.run(job.id)

        assert result.status == "completed"
        assert result.final_report
        assert len(result.task_results) == 2

        final = await service.get_research_job(job.id)
        assert final.status == ResearchJobStatus.COMPLETED
        assert final.report_reference == result.final_report

        tasks = await service.get_research_tasks(job.id)
        assert len(tasks) == 2
        assert all(task.status == ResearchTaskStatus.COMPLETED for task in tasks)
        assert all(task.result for task in tasks)


async def test_workflow_fails_job_when_researcher_fails(
    db_session_factory: async_sessionmaker,
) -> None:
    async with db_session_factory() as session:
        service = ResearchService(session)
        evidence_service = EvidenceService(session)
        job = await service.create_research_job(query="Robotics")
        await service.start_research(job.id)

        workflow = DeepResearchWorkflow(
            research_service=service,
            planner=FakePlanner(),
            researcher=FailingResearcher(),
            synthesizer=FakeSynthesizer(),
            citation_validator=CitationValidatorAgent(evidence_service),
            evidence_service=evidence_service,
        )
        result = await workflow.run(job.id)

        assert result.status == "failed"
        final = await service.get_research_job(job.id)
        assert final.status == ResearchJobStatus.FAILED
        assert final.error

        tasks = await service.get_research_tasks(job.id)
        assert all(task.status == ResearchTaskStatus.FAILED for task in tasks)


class _OrphanCitationSynthesizer:
    """Report that cites a source id which does not exist for this job."""

    def __init__(self) -> None:
        self.orphan_source = "00000000-0000-0000-0000-0000000000ab"

    async def run(
        self,
        query: str,
        results: list[object],
        evidence_index: dict[str, object] | None = None,
        *,
        max_tokens: int | None = None,
    ) -> ResearchReport:
        return ResearchReport(
            title="Orphan report",
            summary="Summary",
            sections=[
                ResearchReportSection(
                    heading="Overview",
                    content="Content",
                    citation_source_ids=[self.orphan_source],
                )
            ],
            conclusion="",
        )


async def test_workflow_fails_when_citation_validation_fails(
    db_session_factory: async_sessionmaker,
) -> None:
    async with db_session_factory() as session:
        service = ResearchService(session)
        evidence_service = EvidenceService(session)
        job = await service.create_research_job(query="Robotics")
        await service.start_research(job.id)

        workflow = DeepResearchWorkflow(
            research_service=service,
            planner=FakePlanner(),
            researcher=FakeResearcher(),
            synthesizer=_OrphanCitationSynthesizer(),
            citation_validator=CitationValidatorAgent(evidence_service),
            evidence_service=evidence_service,
        )

        with pytest.raises(CitationValidationError):
            await workflow.run(job.id)


class _RecordingPlanner:
    """Fake planner that records the user context it was given."""

    def __init__(self) -> None:
        self.user_context: list[str] | None = None

    async def run(
        self,
        topic: str,
        *,
        available_documents: list[str] | None = None,
        user_context: list[str] | None = None,
    ) -> ResearchPlan:
        self.user_context = user_context
        return ResearchPlan(
            objective=topic,
            tasks=[ResearchPlanTask(description="Research companies")],
        )


async def test_workflow_injects_memory_as_planner_context(
    db_session_factory: async_sessionmaker,
) -> None:
    """Explicit memory must reach the planner as user context (never cited)."""
    async with db_session_factory() as session:
        from app.memory.schemas import MemoryCreate
        from app.memory.service import MemoryService

        service = ResearchService(session)
        evidence_service = EvidenceService(session)

        await MemoryService(session).create_memory(
            MemoryCreate(
                content="User is studying humanoid robotics startups.",
                owner_id="owner-1",
                memory_type="interest",
                importance=0.9,
            )
        )

        job = await service.create_research_job(
            query="Research the latest humanoid robotics companies",
            owner_id="owner-1",
        )
        await service.start_research(job.id)

        planner = _RecordingPlanner()
        workflow = DeepResearchWorkflow(
            research_service=service,
            planner=planner,
            researcher=FakeResearcher(),
            synthesizer=FakeSynthesizer(),
            citation_validator=CitationValidatorAgent(evidence_service),
            evidence_service=evidence_service,
        )
        result = await workflow.run(job.id)

        assert result.status == "completed"
        assert planner.user_context, "planner should receive user context"
        assert any(
            "humanoid robotics" in line.lower() for line in planner.user_context
        )

        # Memory is context only: it must never appear among the job's sources.
        sources = await evidence_service.list_sources_for_job(job.id)
        assert sources == []  # finds nothing to cite from memory alone