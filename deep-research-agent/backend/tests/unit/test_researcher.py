"""Unit tests for the researcher agent (grounded, real-tools loop).

The researcher is exercised with fake tools + a fake evidence service (no network,
no DB). The LLM provider is routed by stable prompt markers (see
``app.agents.researcher.prompts``) so each step is deterministic:
generate queries → search → select → fetch → extract evidence → summarize.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.agents.researcher.agent import ResearcherAgent, ResearchLimits
from app.agents.researcher.schemas import ResearchResult
from app.common.exceptions import FetchError, LLMProviderError, ResearcherError
from app.llm.base import LLMResponse
from app.rag.schemas import DocumentRetrievalResult
from app.tools.browser.schemas import FetchedDocument, FetchInput
from app.tools.search.schemas import SearchQuery, SearchResponse, SearchResult


class _ScriptedProvider:
    """LLM provider that returns a canned JSON per prompt marker."""

    def __init__(
        self, by_marker: dict[str, str], fallback: str = '{"summary": ""}'
    ) -> None:
        self._by_marker = by_marker
        self._fallback = fallback
        self.user_prompts: list[str] = []

    async def generate(self, messages: list[object], **kwargs: object) -> LLMResponse:
        user = messages[-1].content
        self.user_prompts.append(user)
        for marker, content in self._by_marker.items():
            if marker in user:
                return LLMResponse(content=content, model="fake", provider="fake")
        return LLMResponse(content=self._fallback, model="fake", provider="fake")


class _FakeEvidence:
    """In-memory evidence stand-in (no ORM / DB)."""

    def __init__(self) -> None:
        self.sources: dict[object, object] = {}
        self.evidence: dict[object, object] = {}

    async def save_source(
        self,
        *,
        research_job_id: object,
        url: str,
        title: str = "",
        content: str = "",
        domain: str = "",
        research_task_id: object | None = None,
        **kw: object,
    ) -> object:
        source = SimpleNamespace(
            id=uuid.uuid4(),
            research_job_id=research_job_id,
            url=url,
            title=title,
            domain=domain,
            content=content,
            source_type="web",
            document_id=None,
        )
        self.sources[source.id] = source
        return source

    async def save_document_source(
        self,
        *,
        research_job_id: object,
        document_id: object,
        title: str,
        research_task_id: object | None = None,
        **kw: object,
    ) -> object:
        source = SimpleNamespace(
            id=uuid.uuid4(),
            research_job_id=research_job_id,
            url=None,
            title=title,
            domain=None,
            content=None,
            source_type="document",
            document_id=document_id,
        )
        self.sources[source.id] = source
        return source

    async def save_evidence(
        self,
        *,
        research_job_id: object,
        research_task_id: object,
        source_id: object,
        claim: str,
        excerpt: str = "",
        locator: str | None = None,
        **kw: object,
    ) -> object:
        item = SimpleNamespace(
            id=uuid.uuid4(),
            source_id=source_id,
            claim=claim,
            excerpt=excerpt,
        )
        self.evidence[item.id] = item
        return item


class _FakeSearch:
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    async def execute(self, input_data: object) -> SearchResponse:
        query = (
            input_data
            if isinstance(input_data, SearchQuery)
            else SearchQuery.model_validate(input_data)
        )
        return SearchResponse(query=query.query, results=list(self._results))


class _FakeFetch:
    """Returns one canned page per URL; unknown URLs raise FetchError."""

    def __init__(self, pages: dict[str, FetchedDocument]) -> None:
        self._pages = pages

    async def execute(self, input_data: object) -> FetchedDocument:
        fetch = (
            input_data
            if isinstance(input_data, FetchInput)
            else FetchInput.model_validate(input_data)
        )
        page = self._pages.get(fetch.url)
        if page is None:
            raise FetchError(f"unknown url {fetch.url}")
        return page


def _document(
    url: str, *, content: str = "SENTENCE here", title: str = "Page"
) -> FetchedDocument:
    return FetchedDocument(
        url=url,
        final_url=url,
        title=title,
        content=content,
        content_type="text/html",
        fetched_at="2024-01-01T00:00:00Z",
        status_code=200,
    )

async def test_researcher_returns_grounded_findings() -> None:
    provider = _ScriptedProvider(
        {
            "generate_search_queries": '{"queries": ["humanoid robotics"]}',
            "select_relevant_search_results": '{"indices": [0]}',
            "extract_evidence": '{"evidence": [{"claim": "Claim A", "excerpt": "SENTENCE"}]}',
            "summarize_findings": '{"summary": "Findings about humanoid robotics."}',
        }
    )
    evidence = _FakeEvidence()
    search = _FakeSearch(_search_results())
    fetch = _FakeFetch({"http://example.com/p1": _document("http://example.com/p1")})

    researcher = _agent(provider, evidence, search, fetch)
    result = await researcher.run(
        query="humanoid robotics",
        task="state of the field",
        research_job_id=uuid.uuid4(),
        research_task_id=uuid.uuid4(),
    )

    assert isinstance(result, ResearchResult)
    assert result.task == "state of the field"
    assert result.summary == "Findings about humanoid robotics."
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.claim == "Claim A"
    assert finding.evidence_ids, "evidence id must be recorded"
    assert finding.source_ids, "source id must be recorded"
    assert evidence.sources, "source must be persisted"
    assert evidence.evidence, "evidence must be persisted"


async def test_researcher_drops_unverified_excerpt() -> None:
    """Excerpts not present verbatim in the fetched page are not persisted."""

    provider = _ScriptedProvider(
        {
            "generate_search_queries": '{"queries": ["humanoid robotics"]}',
            "select_relevant_search_results": '{"indices": [0]}',
            "extract_evidence": '{"evidence": [{"claim": "Claim A", "excerpt": "NOT IN PAGE"}]}',
        }
    )
    evidence = _FakeEvidence()
    search = _FakeSearch(_search_results())
    fetch = _FakeFetch(
        {"http://example.com/p1": _document("http://example.com/p1")}
    )

    researcher = _agent(provider, evidence, search, fetch)
    result = await researcher.run(
        research_job_id=uuid.uuid4(),
        research_task_id=uuid.uuid4(),
        query="humanoid robotics",
        task="state of the field",
    )

    assert result.findings, "a claim still yields a finding even without a good excerpt"
    saved_evidence = list(evidence.evidence.values())[0]
    assert saved_evidence.excerpt == "", "unverified excerpt must not be stored"


async def test_researcher_continues_when_fetch_fails() -> None:
    provider = _ScriptedProvider(
        {
            "generate_search_queries": '{"queries": ["humanoid robotics"]}',
            "select_relevant_search_results": '{"indices": [0]}',
            "summarize_findings": '{"summary": "No findings survived."}',
        }
    )
    evidence = _FakeEvidence()
    search = _FakeSearch(_search_results())
    fetch = _FakeFetch({})  # every URL raises FetchError

    researcher = _agent(provider, evidence, search, fetch)
    result = await researcher.run(
        research_job_id=uuid.uuid4(),
        research_task_id=uuid.uuid4(),
        query="q",
        task="t",
    )

    assert result.summary == "No findings survived."
    assert len(result.findings) == 0
    assert not evidence.sources


async def test_researcher_maps_llm_failure_to_researcher_error() -> None:
    class _BoomProvider(_ScriptedProvider):
        async def generate(self, messages: list[object], **kwargs: object) -> LLMResponse:
            raise LLMProviderError("boom")

    researcher = _agent(
        _BoomProvider({}), _FakeEvidence(), _FakeSearch([]), _FakeFetch({})
    )
    with pytest.raises(ResearcherError):
        await researcher.run(
            research_job_id=uuid.uuid4(),
            research_task_id=uuid.uuid4(),
            query="q",
            task="t",
        )


def _document_chunk(
    text: str = "ACME ROBOTICS annual report 2026 figures.",
) -> DocumentRetrievalResult:
    return DocumentRetrievalResult(
        chunk_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        document_name="acme_report.pdf",
        page_number=2,
        chunk_index=3,
        content=text,
        score=0.42,
        metadata={},
    )


async def test_researcher_uses_document_context_evidence() -> None:
    """Hybrid mode: retrieved chunks become grounded DOCUMENT evidence first."""
    provider = _ScriptedProvider(
        {
            "generate_search_queries": '{"queries": ["acme robotics"]}',
            "select_relevant_search_results": '{"indices": []}',
            "extract_evidence": '{"evidence": [{"claim": "Doc claim", "excerpt": "figures"}]}',
            "summarize_findings": '{"summary": "document-driven"}',
        }
    )
    evidence = _FakeEvidence()
    doc = _document_chunk()
    researcher = _agent(
        provider, evidence, _FakeSearch(_search_results()), _FakeFetch({})
    )

    result = await researcher.run(
        query="acme acme",
        task="t",
        research_job_id=uuid.uuid4(),
        research_task_id=uuid.uuid4(),
        document_context=[doc],
    )

    assert result.summary == "document-driven"
    assert len(result.findings) == 1
    assert evidence.sources, "document source must be persisted"
    saved_source = next(iter(evidence.sources.values()))
    assert saved_source.source_type == "document"
    assert str(saved_source.document_id) == doc.document_id


def _search_results() -> list[SearchResult]:
    return [
        SearchResult(url="http://example.com/p1", title="Page 1", snippet="s1"),
        SearchResult(url="http://example.com/p2", title="Page 2", snippet="s2"),
    ]


def _limits() -> ResearchLimits:
    return ResearchLimits(
        max_search_queries=1, max_pages_per_task=1, max_evidence_per_task=1
    )


def _agent(
    provider: _ScriptedProvider,
    evidence: _FakeEvidence,
    search: _FakeSearch,
    fetch: _FakeFetch,
) -> ResearcherAgent:
    return ResearcherAgent(
        provider,
        search_tool=search,  # type: ignore[arg-type]
        fetch_tool=fetch,  # type: ignore[arg-type]
        evidence_service=evidence,  # type: ignore[arg-type]
        limits=_limits(),
    )