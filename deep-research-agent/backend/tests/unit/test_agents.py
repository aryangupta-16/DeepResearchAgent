"""Unit tests for the planner and synthesizer agents.

Uses a fake LLM provider; no paid API calls. (Researcher-agent tests live in
``test_researcher.py`` because that agent now needs tools + evidence fakes.)
"""

import pytest

from app.agents.planner.agent import PlannerAgent
from app.agents.planner.schemas import ResearchPlan
from app.agents.researcher.schemas import ResearchResult
from app.agents.synthesizer.agent import SynthesizerAgent
from app.agents.synthesizer.schemas import ResearchReport
from app.common.exceptions import LLMProviderError, PlannerError, SynthesisError

PLAN_JSON = (
    '{"objective": "cover robotics", "tasks": '
    '[{"description": "Research companies", "notes": "public info"}, '
    '{"description": "Research technical advances", "notes": ""}]}'
)

RESULT_JSON = (
    '{"task": "Research companies", "summary": "companies are active", '
    '"findings": [{"claim": "Many companies exist", '
    '"evidence_ids": ["e1"], "source_ids": ["s1"]}]}'
)

REPORT_JSON = (
    '{"title": "Robotics report", "summary": "summary", '
    '"sections": [{"heading": "Overview", "content": "content", '
    '"citation_source_ids": ["s1"]}], "conclusion": "done"}'
)


async def test_planner_parses_valid_output(fake_llm_provider) -> None:
    fake_llm_provider.content = PLAN_JSON
    agent = PlannerAgent(fake_llm_provider)
    plan = await agent.run("humanoid robotics")

    assert isinstance(plan, ResearchPlan)
    assert plan.objective == "cover robotics"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].description == "Research companies"


async def test_planner_rejects_malformed_output(fake_llm_provider) -> None:
    fake_llm_provider.content = "this is not json"
    agent = PlannerAgent(fake_llm_provider)
    with pytest.raises(PlannerError):
        await agent.run("humanoid robotics")


async def test_planner_wraps_provider_errors(fake_llm_provider) -> None:
    fake_llm_provider.raise_error = LLMProviderError("boom")
    agent = PlannerAgent(fake_llm_provider)
    with pytest.raises(PlannerError):
        await agent.run("humanoid robotics")


async def test_synthesizer_parses_valid_output_with_citations(
    fake_llm_provider,
) -> None:
    fake_llm_provider.content = REPORT_JSON
    agent = SynthesizerAgent(fake_llm_provider)
    results = [ResearchResult.model_validate_json(RESULT_JSON)]
    report = await agent.run(
        "robotics",
        results,
        evidence_index={"s1": {"title": "Source", "url": "https://example.com"}},
    )

    assert isinstance(report, ResearchReport)
    assert report.title == "Robotics report"
    assert len(report.sections) == 1
    assert report.sections[0].citation_source_ids == ["s1"]


async def test_synthesizer_rejects_malformed_output(fake_llm_provider) -> None:
    fake_llm_provider.content = "not-json"
    agent = SynthesizerAgent(fake_llm_provider)
    with pytest.raises(SynthesisError):
        await agent.run(
            "robotics", [ResearchResult.model_validate_json(RESULT_JSON)]
        )


async def test_synthesizer_wraps_provider_errors(fake_llm_provider) -> None:
    fake_llm_provider.raise_error = LLMProviderError("boom")
    agent = SynthesizerAgent(fake_llm_provider)
    with pytest.raises(SynthesisError):
        await agent.run(
            "robotics", [ResearchResult.model_validate_json(RESULT_JSON)]
        )