"""Deep research LangGraph workflow.

Conceptual graph:

START → load_context → plan → create_tasks → research → synthesize →
validate_citations → finalize → END

Nodes stay separate (one module each); this file only wires the graph and binds
dependencies. Conditional routing can be added later without restructuring.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.workflows.deep_research.nodes.create_tasks import create_tasks
from app.workflows.deep_research.nodes.finalize import finalize
from app.workflows.deep_research.nodes.load_context import load_context
from app.workflows.deep_research.nodes.plan import plan
from app.workflows.deep_research.nodes.research import research
from app.workflows.deep_research.nodes.synthesize import synthesize
from app.workflows.deep_research.nodes.validate_citations import validate_citations
from app.workflows.deep_research.state import ResearchState

if TYPE_CHECKING:  # pragma: no cover
    from app.agents.citation_validator.agent import CitationValidatorAgent
    from app.agents.planner.agent import PlannerAgent
    from app.agents.researcher.agent import ResearcherAgent
    from app.agents.synthesizer.agent import SynthesizerAgent
    from app.evidence.service import EvidenceService
    from app.llm.base import LLMProvider
    from app.research.service import ResearchService
    from app.tools.browser.tool import FetchTool
    from app.tools.search.tool import SearchTool

logger = logging.getLogger(__name__)


def _bind(node_fn, **deps):
    """Return an async LangGraph node that injects fixed dependencies."""

    async def _node(state: ResearchState) -> ResearchState:
        return await node_fn(state, **deps)

    return _node


class DeepResearchWorkflow:
    """Orchestrates planning, research, synthesis, citation validation, finalization."""

    def __init__(
        self,
        *,
        research_service: ResearchService,
        planner: PlannerAgent,
        researcher: ResearcherAgent,
        synthesizer: SynthesizerAgent,
        citation_validator: CitationValidatorAgent,
        evidence_service: EvidenceService,
        document_retriever: object | None = None,
    ) -> None:
        self._research_service = research_service
        self._planner = planner
        self._researcher = researcher
        self._synthesizer = synthesizer
        self._citation_validator = citation_validator
        self._evidence_service = evidence_service
        self._document_retriever = document_retriever
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(ResearchState)
        builder.add_node(
            "load_context", _bind(load_context, research_service=self._research_service)
        )
        builder.add_node(
            "plan",
            _bind(
                plan,
                planner=self._planner,
                research_service=self._research_service,
            ),
        )
        builder.add_node(
            "create_tasks", _bind(create_tasks, research_service=self._research_service)
        )
        builder.add_node(
            "research",
            _bind(
                research,
                researcher=self._researcher,
                research_service=self._research_service,
                document_retriever=self._document_retriever,
            ),
        )
        builder.add_node(
            "synthesize",
            _bind(
                synthesize,
                synthesizer=self._synthesizer,
                evidence_service=self._evidence_service,
                research_service=self._research_service,
            ),
        )
        builder.add_node(
            "validate_citations",
            _bind(
                validate_citations,
                validator=self._citation_validator,
                research_service=self._research_service,
            ),
        )
        builder.add_node(
            "finalize", _bind(finalize, research_service=self._research_service)
        )

        builder.add_edge(START, "load_context")
        builder.add_edge("load_context", "plan")
        builder.add_edge("plan", "create_tasks")
        builder.add_edge("create_tasks", "research")
        builder.add_edge("research", "synthesize")
        builder.add_edge("synthesize", "validate_citations")
        builder.add_edge("validate_citations", "finalize")
        builder.add_edge("finalize", END)
        return builder.compile()

    async def run(self, research_job_id: UUID) -> ResearchState:
        """Execute the full workflow for a job and return the final state."""
        initial = ResearchState(run_id=str(research_job_id))
        logger.info("Deep research workflow started job=%s", research_job_id)
        result = ResearchState.model_validate(await self._graph.ainvoke(initial))
        logger.info(
            "Deep research workflow finished job=%s status=%s",
            research_job_id,
            result.status,
        )
        return result


def _build_document_retriever(session: object) -> object | None:
    """Build the Phase 8 document retriever when embeddings are configured.

    Returns ``None`` for web-only deployments (no EMBEDDING_PROVIDER) — the
    workflow then behaves exactly as before.
    """
    from app.rag.embeddings import build_embedding_provider

    try:
        embedding_provider = build_embedding_provider()
    except Exception:
        logger.warning("Embedding provider misconfigured; running web-only.", exc_info=True)
        return None
    if embedding_provider is None:
        return None

    from app.config.settings import get_settings
    from app.rag.retrieval import DocumentRetrievalService

    settings = get_settings()
    return DocumentRetrievalService(
        session=session,  # type: ignore[arg-type]
        embedding_provider=embedding_provider,
        top_k=settings.vector_top_k,
    )


def build_deep_research_workflow(
    *,
    research_service: ResearchService,
    llm_provider: LLMProvider | None = None,
    evidence_service: EvidenceService | None = None,
    search_tool: SearchTool | None = None,
    fetch_tool: FetchTool | None = None,
    citation_validator: CitationValidatorAgent | None = None,
    document_retriever: object | None = None,
) -> DeepResearchWorkflow:
    """Factory used by the workflow registry.

    ``search_tool``/``fetch_tool``/``evidence_service``/``citation_validator`` are
    optional overrides (e.g. for tests); when omitted, real implementations are
    built from application settings. ``document_retriever`` defaults to a
    pgvector-backed retriever when embeddings are configured.
    """
    from app.agents.citation_validator.agent import CitationValidatorAgent
    from app.agents.planner.agent import PlannerAgent
    from app.agents.researcher.agent import ResearcherAgent, ResearchLimits
    from app.agents.synthesizer.agent import SynthesizerAgent
    from app.config.settings import get_settings
    from app.evidence.service import EvidenceService
    from app.llm.factory import get_llm_provider
    from app.tools.browser.tool import FetchTool
    from app.tools.search import build_search_provider
    from app.tools.search.tool import SearchTool

    provider = llm_provider or get_llm_provider()
    settings = get_settings()

    if evidence_service is None:
        evidence_service = EvidenceService(research_service._session)  # noqa: SLF001
    if search_tool is None:
        search_tool = SearchTool(build_search_provider(settings))
    if fetch_tool is None:
        fetch_tool = FetchTool(
            timeout_seconds=settings.fetch_timeout_seconds,
            max_bytes=settings.fetch_max_bytes,
            max_redirects=settings.fetch_max_redirects,
        )
    if citation_validator is None:
        citation_validator = CitationValidatorAgent(evidence_service)
    if document_retriever is None:
        document_retriever = _build_document_retriever(research_service._session)  # noqa: SLF001

    limits = ResearchLimits(
        max_search_queries=settings.max_search_queries_per_task,
        max_pages_per_task=settings.max_pages_per_task,
        max_evidence_per_task=settings.max_evidence_per_task,
        max_page_content_length=settings.max_page_content_length,
    )

    return DeepResearchWorkflow(
        research_service=research_service,
        planner=PlannerAgent(provider),
        researcher=ResearcherAgent(
            provider,
            search_tool=search_tool,
            fetch_tool=fetch_tool,
            evidence_service=evidence_service,
            limits=limits,
        ),
        synthesizer=SynthesizerAgent(provider),
        citation_validator=citation_validator,
        evidence_service=evidence_service,
        document_retriever=document_retriever,
    )