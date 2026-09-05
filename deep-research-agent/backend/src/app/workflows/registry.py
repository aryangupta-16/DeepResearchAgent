"""Workflow registry.

Maps a workflow name to its factory. Application services look up workflows here
so routes never instantiate orchestration directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.common.exceptions import NotFoundError

logger = logging.getLogger(__name__)

WorkflowFactory = Callable[..., object]


class WorkflowRegistry:
    """Holds the set of available workflows by name."""

    def __init__(self) -> None:
        self._factories: dict[str, WorkflowFactory] = {}

    def register(self, name: str, factory: WorkflowFactory) -> None:
        self._factories[name] = factory
        logger.debug("Registered workflow=%s", name)

    def get(self, name: str, **kwargs: object) -> object:
        if name not in self._factories:
            raise NotFoundError(f"Unknown workflow: {name}")
        return self._factories[name](**kwargs)

    def list(self) -> list[str]:
        return sorted(self._factories)


registry = WorkflowRegistry()


def _chat_workflow(**kwargs: object) -> object:
    """Build the simple chat workflow from configuration."""
    _ = kwargs
    from app.workflows.chat.workflow import get_chat_workflow

    return get_chat_workflow()


def _deep_research_workflow(**kwargs: object) -> object:
    """Build the deep research workflow with injected dependencies."""
    from app.workflows.deep_research.workflow import build_deep_research_workflow

    return build_deep_research_workflow(**kwargs)


registry.register("chat", _chat_workflow)
registry.register("deep_research", _deep_research_workflow)