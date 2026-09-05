"""Anthropic provider (placeholder — not implemented yet)."""

from __future__ import annotations

from app.llm.base import AsyncLLMProvider


class AnthropicProvider(AsyncLLMProvider):
    name = "anthropic"
    default_model = "claude-sonnet-4"

    def __init__(self, *, api_key: str, model: str | None = None) -> None:
        super().__init__(api_key=api_key, model=model)
        # TODO: instantiate Anthropic client from api_key here when wired.