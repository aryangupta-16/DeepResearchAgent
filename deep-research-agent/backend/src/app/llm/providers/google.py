"""Google (Gemini) provider (placeholder — not implemented yet)."""

from __future__ import annotations

from app.llm.base import AsyncLLMProvider


class GoogleProvider(AsyncLLMProvider):
    name = "google"
    default_model = "gemini-2.0-flash"

    def __init__(self, *, api_key: str, model: str | None = None) -> None:
        super().__init__(api_key=api_key, model=model)
        # TODO: instantiate Google/Gemini client from api_key here when wired.