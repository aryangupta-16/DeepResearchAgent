"""Unit tests for research API schemas."""

import pytest
from pydantic import ValidationError

from app.research.schemas import DEFAULT_WORKFLOW_TYPE, ResearchCreateRequest


def test_valid_create_request_uses_default_workflow() -> None:
    request = ResearchCreateRequest(query="Research humanoid robotics")
    assert request.query == "Research humanoid robotics"
    assert request.workflow_type == DEFAULT_WORKFLOW_TYPE


def test_valid_create_request_explicit_workflow() -> None:
    request = ResearchCreateRequest(query="x", workflow_type="deep_research")
    assert request.workflow_type == "deep_research"


@pytest.mark.parametrize("query", ["", "   ", None])
def test_create_request_rejects_blank_query(query: str | None) -> None:
    with pytest.raises(ValidationError):
        ResearchCreateRequest(query=query)  # type: ignore[arg-type]


def test_create_request_rejects_blank_workflow_type() -> None:
    with pytest.raises(ValidationError):
        ResearchCreateRequest(query="x", workflow_type="  ")