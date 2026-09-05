"""Unit tests for the deep research LangGraph structure (no DB required)."""

from app.workflows.deep_research.workflow import DeepResearchWorkflow


class _FakeAgent:
    async def run(self, *args: object, **kwargs: object) -> object:
        return None


def test_graph_has_expected_linear_flow() -> None:
    workflow = DeepResearchWorkflow(
        research_service=object(),  # type: ignore[arg-type]
        planner=_FakeAgent(),  # type: ignore[arg-type]
        researcher=_FakeAgent(),  # type: ignore[arg-type]
        synthesizer=_FakeAgent(),  # type: ignore[arg-type]
        citation_validator=_FakeAgent(),  # type: ignore[arg-type]
        evidence_service=object(),  # type: ignore[arg-type]
    )
    graph = workflow._graph.get_graph()

    node_ids = set(graph.nodes)
    assert {
        "load_context",
        "plan",
        "create_tasks",
        "research",
        "synthesize",
        "validate_citations",
        "finalize",
    } <= node_ids

    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("__start__", "load_context") in edges
    assert ("load_context", "plan") in edges
    assert ("plan", "create_tasks") in edges
    assert ("create_tasks", "research") in edges
    assert ("research", "synthesize") in edges
    assert ("synthesize", "validate_citations") in edges
    assert ("validate_citations", "finalize") in edges
    assert ("finalize", "__end__") in edges