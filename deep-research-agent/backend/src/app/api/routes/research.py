"""Research job API.

Route handlers stay thin: they validate the request payload and delegate to the
research service. No SQLAlchemy or persistence logic lives here.

Phase 6: submission is asynchronous — both ``POST /api/research`` and
``POST /api/research/{id}/run`` persist/enqueue the job and return **202** without
executing the workflow. The worker performs the actual research.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response

from app.api.dependencies import get_research_service
from app.common.exceptions import (
    ResearchJobInvalidStateError,
    ValidationError,
)
from app.config.settings import get_settings
from app.documents.repository import DocumentRepository
from app.evidence.service import EvidenceService
from app.guardrails.input_policy import InputPolicyGuard
from app.research.enums import ResearchJobStatus
from app.research.export import (
    build_markdown,
    export_filename,
    parse_report_json,
)
from app.research.schemas import (
    JobProgress,
    ResearchCreateRequest,
    ResearchJobResponse,
    ResearchJobSummaryResponse,
    ResearchListResponse,
    ResearchSourcesResponse,
    ResearchTaskResponse,
    ResearchTasksResponse,
)
from app.research.service import ResearchService

router = APIRouter()

ResearchServiceDep = Annotated[ResearchService, Depends(get_research_service)]


def _job_response(job: object) -> ResearchJobResponse:
    """Map an ORM job to the API response (progress + report included)."""
    status = job.status
    response = ResearchJobResponse.model_validate(job)
    response.stage = getattr(job, "stage", None)
    response.attempts = getattr(job, "attempts", 0)
    response.progress = JobProgress(
        completed_tasks=getattr(job, "progress_completed_tasks", 0),
        total_tasks=getattr(job, "progress_total_tasks", 0),
    )
    if status == ResearchJobStatus.COMPLETED:
        response.report = getattr(job, "report_reference", None)
    return response


@router.post("", status_code=202, response_model=ResearchJobResponse)
async def create_research_job(
    payload: ResearchCreateRequest,
    service: ResearchServiceDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Optional client key: replaying a request with the same key "
                "returns the original job instead of creating a duplicate."
            ),
        ),
    ] = None,
) -> ResearchJobResponse:
    """Create a research job, enqueue it for the worker, and return immediately."""
    # Phase B2 input policy: length caps + injection heuristics + basic abuse
    # filtering. Rejections raise ValidationError → clean 422, logged + counted.
    settings = get_settings()
    guard = InputPolicyGuard(
        min_length=settings.guardrails_min_query_length,
        max_length=settings.guardrails_max_query_length,
    )
    normalized_query = guard.check(payload.query)

    normalized_key = (idempotency_key or "").strip() or None
    if normalized_key:
        max_length = settings.idempotency_key_max_length
        if len(normalized_key) > max_length:
            raise ValidationError(
                f"Idempotency-Key must be at most {max_length} characters."
            )
    job = await service.create_research_job(
        query=normalized_query,
        workflow_type=payload.workflow_type,
        document_ids=list(payload.document_ids) or None,
        owner_id=payload.owner_id,
        idempotency_key=normalized_key,
    )
    await service.submit_research_job(job.id)
    return _job_response(job)


@router.get("", response_model=ResearchListResponse)
async def list_research_jobs(
    service: ResearchServiceDep,
    limit: int = 25,
    offset: int = 0,
) -> ResearchListResponse:
    """Recent research jobs, newest first (history sidebar)."""
    jobs = await service.list_research_jobs(limit=limit, offset=offset)
    return ResearchListResponse(
        items=[ResearchJobSummaryResponse.model_validate(j) for j in jobs],
        count=len(jobs),
        limit=limit,
        offset=offset,
    )


@router.get("/{research_id}", response_model=ResearchJobResponse)
async def get_research_job(
    research_id: UUID,
    service: ResearchServiceDep,
) -> ResearchJobResponse:
    """Return the current state of a research job (status/stage/progress)."""
    job = await service.get_research_job(research_id)
    return _job_response(job)


@router.get("/{research_id}/tasks", response_model=ResearchTasksResponse)
async def get_research_tasks(
    research_id: UUID,
    service: ResearchServiceDep,
) -> ResearchTasksResponse:
    """Return the tasks belonging to a research job."""
    tasks = await service.get_research_tasks(research_id)
    return ResearchTasksResponse(
        research_id=research_id,
        tasks=[ResearchTaskResponse.model_validate(task) for task in tasks],
    )


async def _load_sources_payload(
    research_id: UUID, service: ResearchService
) -> list[dict[str, Any]]:
    """Sources + evidence for a job, with document names resolved (export view)."""
    evidence_service = EvidenceService(service.session)
    sources = await evidence_service.list_sources_for_job(research_id)
    documents = DocumentRepository(service.session)

    payload: list[dict[str, Any]] = []
    for source in sources:
        evidence = await evidence_service.list_evidence_for_source(source.id)
        document_name = None
        if source.document_id:
            document = await documents.get_by_id(source.document_id)
            document_name = document.filename if document else None
        payload.append(
            {
                "id": source.id,
                "url": source.url,
                "title": source.title,
                "domain": source.domain,
                "source_type": source.source_type or "web",
                "document_id": source.document_id,
                "document_name": document_name,
                "retrieved_at": source.retrieved_at,
                "evidence": evidence,
            }
        )
    return payload


@router.get(
    "/{research_id}/sources",
    response_model=ResearchSourcesResponse,
)
async def get_research_sources(
    research_id: UUID,
    service: ResearchServiceDep,
) -> ResearchSourcesResponse:
    """Return every source (with its evidence) captured for a research job.

    Read-only view used by the report UI to let users inspect the evidence behind
    citations and open the original web pages.
    """
    await service.get_research_job(research_id)  # 404 when missing
    payload = await _load_sources_payload(research_id, service)
    return ResearchSourcesResponse(research_id=research_id, sources=payload)


@router.get("/{research_id}/report.md")
async def export_report_markdown(
    research_id: UUID,
    service: ResearchServiceDep,
) -> Response:
    """Download the completed report as a detailed Markdown document.

    Includes every section, the conclusion, and the full source list with each
    evidence item (claim, excerpt, locator) — everything the report UI shows.
    """
    job = await service.get_research_job(research_id)  # 404 when missing
    if job.status != ResearchJobStatus.COMPLETED or not job.report_reference:
        raise ResearchJobInvalidStateError(
            "Report export is only available for completed research with a report."
        )
    report = parse_report_json(job.report_reference)
    if report is None:
        raise ResearchJobInvalidStateError(
            "The stored report could not be parsed for export."
        )
    sources = await _load_sources_payload(research_id, service)
    # The shared loader returns ORM evidence; the builder wants plain dicts.
    export_sources = []
    for source in sources:
        export_sources.append(
            {
                **source,
                "evidence": [
                    {
                        "claim": item.claim,
                        "excerpt": item.excerpt or "",
                        "locator": item.locator,
                    }
                    for item in source["evidence"]
                ],
            }
        )
    markdown = build_markdown(job.query, report, export_sources)
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{export_filename(str(research_id), "md")}"'
            )
        },
    )


@router.post("/{research_id}/run", status_code=202, response_model=ResearchJobResponse)
async def run_research_job(
    research_id: UUID,
    service: ResearchServiceDep,
) -> ResearchJobResponse:
    """Enqueue an existing pending job for asynchronous execution.

    Idempotency policy (V1): only ``pending`` jobs may be submitted.
    ``running``/``completed``/``failed`` jobs are rejected with **409** — create a
    new job to run the same query again.
    """
    job = await service.get_research_job(research_id)
    if job.status != ResearchJobStatus.PENDING:
        raise ResearchJobInvalidStateError(
            f"Cannot run research job in status {job.status.value!r}; "
            "only 'pending' jobs can be queued."
        )
    await service.submit_research_job(research_id)
    refreshed = await service.get_research_job(research_id)
    return _job_response(refreshed)