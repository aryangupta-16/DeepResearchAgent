"""Tool registry.

Tools perform *deterministic* operations (search, browse, fetch, parse). They do
not contain agentic orchestration. The registry lets workflows/agents resolve
tools by name, so concrete providers can be swapped via factory wiring.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.common.exceptions import NotFoundError

logger = logging.getLogger(__name__)

ToolFn = Callable[..., object]


class ToolRegistry:
    """Maps tool names to callables."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolFn] = {}

    def register(self, name: str, fn: ToolFn) -> None:
        self._tools[name] = fn
        logger.debug("Registered tool=%s", name)

    def get(self, name: str) -> ToolFn:
        if name not in self._tools:
            raise NotFoundError(f"Unknown tool: {name}")
        return self._tools[name]

    def list(self) -> list[str]:
        return sorted(self._tools)


tools = ToolRegistry()