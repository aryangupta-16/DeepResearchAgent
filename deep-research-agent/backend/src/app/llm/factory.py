"""Provider factory: resolves an :class:`LLMProvider` based on configuration.

Selection is driven by settings (``LLM_PROVIDER`` / ``LLM_MODEL``). The factory
fails loudly with :class:`LLMNotConfiguredError` rather than silently falling
back to another provider.
"""

from __future__ import annotations

from app.common.exceptions import LLMNotConfiguredError
from app.config.settings import get_settings
from app.llm.base import LLMProvider


def get_llm_provider(provider: str | None = None) -> LLMProvider:
    """Return a configured provider, selected by settings (or an explicit name)."""
    settings = get_settings()
    selected = (provider or settings.llm_provider or "").strip().lower()

    if not selected:
        raise LLMNotConfiguredError(
            "No LLM provider configured. Set LLM_PROVIDER (e.g. 'openai')."
        )

    if selected == "openai":
        if not settings.openai_api_key:
            raise LLMNotConfiguredError("OPENAI_API_KEY is not configured.")
        from app.llm.providers.openai import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.llm_model or None,
            base_url=settings.openai_base_url or None,
            timeout=settings.llm_timeout,
        )

    if selected in ("anthropic", "google"):
        raise LLMNotConfiguredError(
            f"LLM provider {selected!r} is not implemented yet."
        )

    raise LLMNotConfiguredError(f"Unsupported LLM provider {selected!r}.")