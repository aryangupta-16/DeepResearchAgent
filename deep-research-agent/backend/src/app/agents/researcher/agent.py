"""Researcher agent.

Runs a *bounded, real* research loop per task using deterministic tools and the
LLM abstraction:

    generate search queries → search → select results → fetch pages →
    extract evidence → persist sources+evidence → produce grounded findings

The LLM decides *what* to search and extract; the tools do the actual work; the
evidence service persists sources/evidence with provenance. The agent never opens
a DB session or touches a vendor SDK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from app.agents.researcher.prompts import (
    RESEARCHER_SYSTEM_PROMPT,
    build_evidence_extraction_prompt,
    build_search_queries_prompt,
    build_selection_prompt,
    build_summary_prompt,
)
from app.agents.researcher.schemas import (
    ResearcherEvidenceItem,
    ResearcherEvidenceList,
    ResearcherQuerySet,
    ResearcherSourceSelection,
    ResearcherSummary,
    ResearchFinding,
    ResearchResult,
)
from app.common.exceptions import AppError, ResearcherError
from app.evidence.service import EvidenceService
from app.llm.base import LLMMessage, LLMProvider
from app.rag.schemas import DocumentRetrievalResult
from app.tools.browser.schemas import FetchInput
from app.tools.browser.tool import FetchTool
from app.tools.search.schemas import SearchQuery, SearchResult
from app.tools.search.tool import SearchTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchLimits:
    """Per-task bounds that prevent runaway research."""

    max_search_queries: int = 3
    max_pages_per_task: int = 5
    max_evidence_per_task: int = 8
    max_page_content_length: int = 200_000


def _verified_excerpt(excerpt: str, content: str) -> str:
    """Keep an excerpt only when it genuinely appears in the fetched content."""
    normalized_excerpt = " ".join(excerpt.split())
    if normalized_excerpt and normalized_excerpt in " ".join(content.split()):
        return excerpt[:500]
    return ""


class ResearcherAgent:
    """Researches a single task via bounded searching, fetching, and evidence."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        search_tool: SearchTool,
        fetch_tool: FetchTool,
        evidence_service: EvidenceService,
        limits: ResearchLimits | None = None,
    ) -> None:
        self._provider = provider
        self._search = search_tool
        self._fetch = fetch_tool
        self._evidence = evidence_service
        self._limits = limits or ResearchLimits()

    async def run(
        self,
        *,
        query: str,
        task: str,
        research_job_id: UUID,
        research_task_id: UUID,
        document_context: list[DocumentRetrievalResult] | None = None,
    ) -> ResearchResult:
        """Execute the bounded research loop for one task.

        ``document_context`` carries chunks retrieved from user-uploaded
        documents (Phase 8 hybrid mode); when empty the task is web-only.
        """
        fetched_urls: set[str] = set()
        evidence_rows: list[tuple[UUID, UUID, str]] = []  # (evidence_id, source_id, claim)

        # Phase 8: process retrieved document chunks FIRST so they are guaranteed
        # budget priority. Document evidence then naturally combines with web
        # evidence; the web loop below honors the remaining per-task allowance.
        if document_context:
            await self._process_document_context(
                query=query,
                chunks=document_context,
                research_job_id=research_job_id,
                research_task_id=research_task_id,
                evidence_rows=evidence_rows,
            )
            logger.info(
                "Researcher doc-context task=%s document_evidence=%d",
                research_task_id,
                len(evidence_rows),
            )

        candidates = await self._collect_search_results(query=query, task=task)

        for result in candidates:
            if len(fetched_urls) >= self._limits.max_pages_per_task:
                break
            if len(evidence_rows) >= self._limits.max_evidence_per_task:
                break
            url = str(result.url)
            if not url or url in fetched_urls:
                continue
            fetched_urls.add(url)

            try:
                document = await self._fetch.execute(
                    FetchInput(url=url, max_bytes=self._limits.max_page_content_length)
                )
            except AppError as exc:
                logger.warning(
                    "Fetch failed task=%s url=%s (%s)", research_task_id, url, exc
                )
                continue
            if not document.content.strip():
                continue

            source = await self._evidence.save_source(
                research_job_id=research_job_id,
                research_task_id=research_task_id,
                url=document.final_url or url,
                title=document.title or str(result.title),
                content=document.content[: self._limits.max_page_content_length],
                domain=str(result.domain) or "",
            )

            budget = self._limits.max_evidence_per_task - len(evidence_rows)
            if budget <= 0:
                break

            extracted = await self._extract_evidence(
                query=query,
                url=document.final_url or url,
                title=document.title,
                content=document.content[: self._limits.max_page_content_length],
                max_items=budget,
            )
            for item in extracted:
                if len(evidence_rows) >= self._limits.max_evidence_per_task:
                    break
                try:
                    saved = await self._evidence.save_evidence(
                        research_job_id=research_job_id,
                        research_task_id=research_task_id,
                        source_id=source.id,
                        claim=item.claim,
                        excerpt=_verified_excerpt(item.excerpt, document.content),
                        locator=item.locator,
                    )
                except AppError as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "Evidence save failed task=%s (%s)", research_task_id, exc
                    )
                    continue
                evidence_rows.append((saved.id, source.id, saved.claim))

        logger.info(
            "Researcher done task=%s pages_fetched=%d evidence=%d",
            research_task_id,
            len(fetched_urls),
            len(evidence_rows),
        )

        findings = [
            ResearchFinding(
                claim=claim,
                evidence_ids=[str(evidence_id)],
                source_ids=[str(source_id)],
            )
            for evidence_id, source_id, claim in evidence_rows
        ]
        summary = await self._summarize(query=query, task=task, findings=findings)
        return ResearchResult(task=task, summary=summary, findings=findings)

    # ---- Internal research steps ----

    async def _process_document_context(
        self,
        *,
        query: str,
        chunks: list[DocumentRetrievalResult],
        research_job_id: UUID,
        research_task_id: UUID,
        evidence_rows: list[tuple[UUID, UUID, str]],
    ) -> None:
        """Convert retrieved document chunks into grounded document evidence.

        One DOCUMENT-type source per uploaded document (deduplicated per job);
        each retrieved chunk contributes evidence whose locator preserves the
        page number for citation display.
        """
        for chunk in chunks:
            if len(evidence_rows) >= self._limits.max_evidence_per_task:
                break
            try:
                source = await self._evidence.save_document_source(
                    research_job_id=research_job_id,
                    research_task_id=research_task_id,
                    document_id=UUID(chunk.document_id),
                    title=chunk.document_name,
                )
            except AppError as exc:
                logger.warning(
                    "Document source save failed task=%s doc=%s (%s)",
                    research_task_id,
                    chunk.document_id,
                    exc,
                )
                continue

            budget = self._limits.max_evidence_per_task - len(evidence_rows)
            extracted = await self._extract_evidence(
                query=query,
                url=f"document:{chunk.document_id}",
                title=f"{chunk.document_name}"
                + (f" (page {chunk.page_number})" if chunk.page_number else ""),
                content=chunk.content[: self._limits.max_page_content_length],
                max_items=budget,
            )
            default_locator = (
                f"Page {chunk.page_number}"
                if chunk.page_number is not None
                else f"Chunk {chunk.chunk_index + 1}"
            )
            for item in extracted:
                if len(evidence_rows) >= self._limits.max_evidence_per_task:
                    break
                try:
                    saved = await self._evidence.save_evidence(
                        research_job_id=research_job_id,
                        research_task_id=research_task_id,
                        source_id=source.id,
                        claim=item.claim,
                        excerpt=_verified_excerpt(item.excerpt, chunk.content),
                        locator=item.locator or default_locator,
                    )
                except AppError as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "Document evidence save failed task=%s (%s)",
                        research_task_id,
                        exc,
                    )
                    continue
                evidence_rows.append((saved.id, source.id, saved.claim))

    async def _collect_search_results(self, *, query: str, task: str) -> list[SearchResult]:
        """Generate queries, search, and select relevant results (bounded)."""
        search_queries = await self._llm_search_queries(query=query, task=task)
        candidates: list[SearchResult] = []
        seen_urls: set[str] = set()

        for search_query in search_queries[: self._limits.max_search_queries]:
            try:
                response = await self._search.execute(
                    SearchQuery(query=search_query, limit=5)
                )
            except AppError as exc:
                logger.warning("Search failed task=%s (%s)", task, exc)
                continue
            if not response.results:
                continue

            if len(candidates) >= self._limits.max_pages_per_task:
                break
            selected = await self._llm_select_results(
                query=query, task=task, results=response.results
            )
            for index in selected:
                if index < 0 or index >= len(response.results):
                    continue
                if len(candidates) >= self._limits.max_pages_per_task:
                    break
                result = response.results[index]
                if str(result.url) in seen_urls:
                    continue
                seen_urls.add(str(result.url))
                candidates.append(result)
        return candidates

    async def _llm_search_queries(self, *, query: str, task: str) -> list[str]:
        content = await self._generate(build_search_queries_prompt(query, task))
        try:
            parsed = ResearcherQuerySet.model_validate_json(content)
        except (ValidationError, ValueError):
            return [task or query]
        queries = [q.strip() for q in parsed.queries if q.strip()]
        return queries or [task or query]

    async def _llm_select_results(
        self, *, query: str, task: str, results: list[SearchResult]
    ) -> list[int]:
        content = await self._generate(build_selection_prompt(query, task, results))
        try:
            parsed = ResearcherSourceSelection.model_validate_json(content)
        except (ValidationError, ValueError):
            return list(range(min(len(results), self._limits.max_pages_per_task)))
        indices = sorted({int(i) for i in parsed.indices})
        return indices or list(
            range(min(len(results), self._limits.max_pages_per_task))
        )

    async def _extract_evidence(
        self, *, query: str, url: str, title: str, content: str, max_items: int
    ) -> list[ResearcherEvidenceItem]:
        llm_content = await self._generate(
            build_evidence_extraction_prompt(query, url, title, content, max_items)
        )
        try:
            parsed = ResearcherEvidenceList.model_validate_json(llm_content)
        except (ValidationError, ValueError):
            return []
        return [item for item in parsed.evidence if item.claim.strip()][:max_items]

    async def _summarize(
        self, *, query: str, task: str, findings: list[ResearchFinding]
    ) -> str:
        content = await self._generate(build_summary_prompt(query, task, findings))
        try:
            parsed = ResearcherSummary.model_validate_json(content)
            if parsed.summary.strip():
                return parsed.summary.strip()
        except (ValidationError, ValueError):
            pass
        return "; ".join(finding.claim for finding in findings) or "No findings."

    async def _generate(self, user_prompt: str) -> str:
        """Call the LLM abstraction; translate failures into ResearcherError."""
        messages = [
            LLMMessage(role="system", content=RESEARCHER_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]
        try:
            response = await self._provider.generate(messages)
        except AppError as exc:
            raise ResearcherError("Researcher agent failed.") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise ResearcherError("Researcher agent failed unexpectedly.") from exc
        return response.content or ""


__all__ = ["ResearchLimits", "ResearcherAgent"]