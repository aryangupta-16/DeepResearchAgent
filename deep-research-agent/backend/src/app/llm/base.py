"""LLM provider abstraction.

Agents and workflows depend on :class:`LLMProvider` — the interface — rather than
any vendor SDK directly. This keeps the rest of the application vendor-independent.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from app.common.exceptions import AppError, LLMProviderError

logger = logging.getLogger(__name__)


@dataclass
class LLMMessage:
    """One chat turn in our canonical message format."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMUsage:
    """Token usage when the provider exposes it."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class LLMResponse:
    """Canonical assistant response, independent of any provider SDK."""

    content: str
    model: str
    provider: str
    usage: LLMUsage | None = None
    raw: object = None  # provider-specific payload, kept opaque and never leaked


@dataclass
class LLMStreamEvent:
    """One incremental streaming update.

    Intermediate events carry ``delta`` text; the terminal event carries the
    fully aggregated :class:`LLMResponse` (usage/model included when the
    provider reports it).
    """

    delta: str | None = None
    response: LLMResponse | None = None


class LLMProvider(Protocol):
    """Minimal interface every LLM provider satisfies."""

    name: str

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> LLMResponse:
        """Translate our messages, call the provider, and map back the response."""
        ...


class AsyncLLMProvider:
    """Concrete base: owns key/model lifetime and maps generic failures.

    Subclasses implement ``_generate`` (the vendor-specific call + mapping). The
    public ``generate`` wraps ``_generate`` with timing, logging, and error
    translation so vendor exceptions never escape as-is.
    """

    name: str = "base"
    default_model: str = ""

    def __init__(self, *, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or self.default_model

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> LLMResponse:
        target_model = model or self.model
        start = time.perf_counter()
        try:
            response = await self._generate(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=target_model,
                timeout=timeout,
            )
        except AppError:
            # Provider-translated errors pass through unchanged.
            logger.warning("LLM generation failed provider=%s model=%s", self.name, target_model)
            raise
        except Exception as exc:
            # Any otherwise-untranslated failure must stay inside our hierarchy.
            logger.exception("Unexpected LLM error provider=%s model=%s", self.name, target_model)
            raise LLMProviderError(
                f"LLM provider {self.name!r} failed unexpectedly."
            ) from exc

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "LLM generated provider=%s model=%s duration_ms=%.1f",
            self.name,
            target_model,
            duration_ms,
        )
        return response

    async def _generate(
        self,
        *,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int | None,
        model: str,
        timeout: float,
    ) -> LLMResponse:
        raise NotImplementedError(f"LLM provider {self.name!r} is not implemented yet.")

    # ---- Streaming (optional capability; Phase C) ----

    def supports_streaming(self) -> bool:
        """Whether this provider can stream tokens incrementally."""
        return False

    async def generate_stream(  # noqa: RUF029 - generator by design
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        """Yield :class:`LLMStreamEvent` updates; the terminal event carries the
        aggregated :class:`LLMResponse`.

        Default implementation: non-streaming fallback — callers get a single
        delta with the full content, so streaming-capable consumers work with
        every provider.
        """
        response = await self.generate(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            timeout=timeout,
        )
        yield LLMStreamEvent(delta=response.content, response=response)