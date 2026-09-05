"""Planner agent.

Uses the LLM abstraction to decompose a topic into a structured research plan.
The agent only plans; it never researches.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.agents.planner.prompts import PLANNER_SYSTEM_PROMPT, build_planner_prompt
from app.agents.planner.schemas import ResearchPlan
from app.common.exceptions import AppError, PlannerError
from app.llm.base import LLMMessage, LLMProvider


class PlannerAgent:
    """Decomposes a research topic into structured research tasks."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def run(
        self,
        topic: str,
        *,
        available_documents: list[str] | None = None,
        user_context: list[str] | None = None,
    ) -> ResearchPlan:
        messages = [
            LLMMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=build_planner_prompt(
                    topic,
                    available_documents=available_documents,
                    user_context=user_context,
                ),
            ),
        ]
        try:
            response = await self._provider.generate(messages)
        except AppError as exc:
            raise PlannerError("Planner agent failed to produce a plan.") from exc

        try:
            return ResearchPlan.model_validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise PlannerError("Planner agent produced malformed output.") from exc