"""Synthesizer agent.

Combines *grounded* research results into a structured, citation-aware report using
the LLM abstraction. The report is grounded only in the provided results and may
cite only the provided source ids.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.agents.synthesizer.prompts import (
    SYNTHESIZER_SYSTEM_PROMPT,
    build_synthesizer_prompt,
)
from app.agents.synthesizer.schemas import ResearchReport
from app.common.exceptions import AppError, SynthesisError
from app.llm.base import LLMMessage, LLMProvider


class SynthesizerAgent:
    """Combines research results into a coherent, citation-aware research report."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def run(
        self,
        query: str,
        results: list[object],
        evidence_index: dict[str, Any] | None = None,
        *,
        max_tokens: int | None = None,
    ) -> ResearchReport:
        """Generate a report from ``results`` and an optional source index.

        ``evidence_index`` maps source id → {"title", "url", "domain",
        "evidence": [{claim, excerpt, locator}]} so sections can carry
        machine-readable citations and the model can quote real excerpts.
        ``max_tokens`` forwards to the provider (detailed reports need room).
        """
        results_json = json.dumps(
            [result.model_dump() for result in results], indent=2
        )
        messages = [
            LLMMessage(role="system", content=SYNTHESIZER_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=build_synthesizer_prompt(query, results_json, evidence_index),
            ),
        ]
        try:
            response = await self._provider.generate(messages, max_tokens=max_tokens)
        except AppError as exc:
            raise SynthesisError("Synthesizer agent failed.") from exc

        try:
            return ResearchReport.model_validate_json(
                _strip_json_fences(response.content)
            )
        except (ValidationError, ValueError) as exc:
            raise SynthesisError("Synthesizer agent produced malformed output.") from exc


def _strip_json_fences(content: str) -> str:
    """Remove markdown code fences some models wrap JSON in.

    Handles ```json ... ``` and bare ``` ... ``` blocks; plain JSON passes
    through untouched.
    """
    text = content.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()