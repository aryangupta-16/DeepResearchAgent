"""Agents package.

Each agent owns its own *reasoning* (LLM usage). Agents depend on interfaces
(LLM provider, tools) rather than on vendor-specific clients or infrastructure.
"""

from typing import Any, Protocol


class Agent(Protocol):
    """Minimal contract every agent satisfies.

    An agent receives a task and returns a structured result. Concrete agents
    decide internally how to reason (which LLM prompts/strategy to use).
    """

    # Keep the protocol narrow so new agents plug in without ceremony.
    async def run(self, task: Any) -> Any:  # noqa: ANN401 - generic by design
        ...