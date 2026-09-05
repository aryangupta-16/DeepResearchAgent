"""LLM-based memory extraction (structured, validated).

Uses the existing :class:`LLMProvider` abstraction — never a vendor SDK. The
extractor returns validated :class:`MemoryExtractionResult` candidates; it is a
pure function of user-supplied text and NEVER persists anything and never sees
research sources / web pages / documents / evidence.

Malformed LLM output is raised as a domain :class:`ValidationError` so it can
never create database records.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.common.exceptions import ValidationError as AppValidationError
from app.llm.base import LLMMessage, LLMProvider
from app.memory.schemas import MemoryExtractionResult

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract durable long-term user memories from the user's own words. "
    "Extract only statements the user makes about themselves: interests, "
    "preferences, goals, ongoing context, and standing instructions. "
    "Never infer facts from research findings, sources, or web pages. "
    "Return only the JSON format requested."
)

_EXTRACTION_JSON_SHAPE = (
    '{"memories": [{"content": "statement", '
    '"memory_type": "interest|preference|goal|context|instruction|fact", '
    '"importance": 0.8, "source": "explicit|inferred"}]}'
)


def build_extraction_prompt(user_text: str) -> str:
    """Return the user-text extraction prompt (no prompts/log contents logged)."""
    return (
        f"User text:\n{user_text}\n\n"
        "Extract candidate long-term user memories from the text above.\n"
        "Return a JSON object with this exact shape and nothing else:\n"
        f"{_EXTRACTION_JSON_SHAPE}\n"
        "When no durable memory is present, return {\"memories\": []}."
    )


class MemoryExtractor:
    """Structured memory extraction via the configured LLM provider."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def extract(self, user_text: str) -> MemoryExtractionResult:
        """Extract + validate candidate memories from ``user_text``.

        Raises:
            MemoryExtractionError: when the LLM call fails.
            ValidationError: when the LLM output is malformed (never persisted).
        """
        from app.common.exceptions import MemoryExtractionError

        messages = [
            LLMMessage(role="system", content=_EXTRACTION_SYSTEM_PROMPT),
            LLMMessage(role="user", content=build_extraction_prompt(user_text)),
        ]
        try:
            response = await self._provider.generate(messages)
        except Exception as exc:
            raise MemoryExtractionError(
                "Memory extraction could not be completed."
            ) from exc

        try:
            return MemoryExtractionResult.model_validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise AppValidationError(
                "Memory extraction produced malformed output; nothing was stored."
            ) from exc