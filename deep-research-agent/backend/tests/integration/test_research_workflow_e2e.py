"""End-to-end test: real tools + real agents + real evidence against local mocks.

Launches one mock server exposing:

- an OpenAI-compatible chat API (structured JSON per prompt marker),
- a Serper-compatible search endpoint,
- demo HTML pages.

Then the REAL OpenAIProvider (pointed at the mock), REAL SerperSearchProvider
(pointing at ``/mock_search``), REAL FetchTool (fetches the demo pages) and REAL
EvidenceService/PostgreSQL run the whole LangGraph workflow end to end.

Requires the Postgres integration DB and a free port for the mock server.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.agents.citation_validator.agent import CitationValidatorAgent
from app.agents.planner.agent import PlannerAgent
from app.agents.researcher.agent import ResearcherAgent, ResearchLimits
from app.agents.synthesizer.agent import SynthesizerAgent
from app.agents.synthesizer.schemas import ResearchReport
from app.common.exceptions import AppError
from app.evidence.service import EvidenceService
from app.llm.providers.openai import OpenAIProvider
from app.research.enums import ResearchJobStatus, ResearchTaskStatus
from app.research.service import ResearchService
from app.tools.browser.tool import FetchTool
from app.tools.search.providers import SearchProviderConfig, SerperSearchProvider
from app.tools.search.tool import SearchTool
from app.workflows.deep_research.workflow import DeepResearchWorkflow

logger = logging.getLogger(__name__)

MOCK_DIR = Path(__file__).parent / "fixtures"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def mock_research_server():
    """Start the combined mock server; yield its base url."""
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(MOCK_DIR)}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "mock_openai:app",
            "--host", "127.0.0.1", f"--port={port}",
        ],
        cwd=str(MOCK_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"

    async def _wait_ready() -> None:
        probe = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        }
        for _ in range(50):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{base_url}/v1/chat/completions",
                        json=probe,
                        timeout=1.0,
                    )
                if response.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.ReadError, AppError):
                pass
            await asyncio.sleep(0.2)
        raise RuntimeError("mock server did not start in time")

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_wait_ready())
    loop.close()

    yield base_url

    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


async def test_full_workflow_with_real_tools_and_evidence(
    mock_research_server: str,
    db_session_factory,
) -> None:
    base_url = mock_research_server

    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-4o-mini",
        base_url=f"{base_url}/v1",
    )
    search_tool = SearchTool(
        SerperSearchProvider(
            SearchProviderConfig(api_key="test-key", endpoint=f"{base_url}/mock_search")
        )
    )
    fetch_tool = FetchTool(timeout_seconds=10.0, max_bytes=200_000)

    async with db_session_factory() as session:
        service = ResearchService(session)
        evidence_service = EvidenceService(session)

        workflow = DeepResearchWorkflow(
            research_service=service,
            planner=PlannerAgent(provider),
            researcher=ResearcherAgent(
                provider,
                search_tool=search_tool,
                fetch_tool=fetch_tool,
                evidence_service=evidence_service,
                limits=ResearchLimits(
                    max_search_queries=1,
                    max_pages_per_task=2,
                    max_evidence_per_task=3,
                    max_page_content_length=20_000,
                ),
            ),
            synthesizer=SynthesizerAgent(provider),
            citation_validator=CitationValidatorAgent(evidence_service),
            evidence_service=evidence_service,
        )

        job = await service.create_research_job(
            query="Current state of humanoid robotics"
        )
        await service.start_research(job.id)

        result = await workflow.run(job.id)

        assert result.status == "completed"
        assert result.final_report

        report = ResearchReport.model_validate_json(result.final_report)
        cited = {
            source_id
            for section in report.sections
            for source_id in section.citation_source_ids
        }
        assert cited, "report must contain machine-readable citations"
        assert "Humanoid Robotics" in report.title

        final = await service.get_research_job(job.id)
        assert final.status == ResearchJobStatus.COMPLETED
        # Full report is persisted (no truncation after migration 0002).
        assert final.report_reference == result.final_report

        # Real search + fetch must have persisted sources with evidence.
        sources = await evidence_service.list_sources_for_job(job.id)
        assert len(sources) >= 1
        source_ids = {str(source.id) for source in sources}
        assert cited <= source_ids, "every cited source must exist in the job"

        evidence = [
            item
            for source in sources
            for item in await evidence_service.list_evidence_for_source(source.id)
        ]
        assert len(evidence) >= 1

        tasks = await service.get_research_tasks(job.id)
        assert len(tasks) >= 2
        assert all(task.status == ResearchTaskStatus.COMPLETED for task in tasks)
        assert all(task.result and "source_ids" in task.result for task in tasks)

        logger.info(
            "e2e passed sources=%d evidence=%d cited=%d",
            len(sources),
            len(evidence),
            len(cited),
        )