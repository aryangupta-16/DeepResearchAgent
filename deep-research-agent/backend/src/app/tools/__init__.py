"""Tools: deterministic operations. No agentic orchestration here.

Public surface:

- :class:`Tool` — abstract base for deterministic tools (search, browse, ...).
- :class:`ToolRegistry` — maps tool names to :class:`Tool` instances so agents
  can resolve tools by name. Concrete providers are injected by the factory
  wiring, keeping vendor SDKs out of agent code.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Tool(Protocol):
    """Contract for deterministic, side-effecting tools used by agents.

    A tool is *not* an agent: it performs a single well-defined operation
    (search, fetch, parse) and returns a typed result. Tools own no agentic
    orchestration and contain no LLM reasoning.
    """

    name: str
    description: str

    async def execute(self, input: Any) -> Any:  # noqa: A002 - semantic API
        """Run the tool against ``input`` and return a typed result."""
        ...


ToolInput = Any
ToolOutput = Any