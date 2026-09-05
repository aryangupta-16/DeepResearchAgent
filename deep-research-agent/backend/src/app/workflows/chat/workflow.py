"""Simple chat workflow (no LangGraph in V1).

Proves the service/workflow/provider layer with a straight linear flow:
input → build messages → call LLM provider → return canonical response.
Streaming (Phase C) reuses the same message building and the provider's
optional ``generate_stream`` capability, falling back to a one-shot event
when the provider cannot stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMStreamEvent
from app.workflows.chat.prompts import CHAT_SYSTEM_PROMPT


class ChatWorkflow:
    """Orchestrates a single chat turn against an :class:`LLMProvider`."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def build_messages(
        self,
        message: str,
        *,
        history: list[LLMMessage] | None = None,
        system_prompt: str = CHAT_SYSTEM_PROMPT,
    ) -> list[LLMMessage]:
        messages: list[LLMMessage] = [LLMMessage(role="system", content=system_prompt)]
        if history:
            messages.extend(history)
        messages.append(LLMMessage(role="user", content=message))
        return messages

    async def run(
        self,
        message: str,
        *,
        history: list[LLMMessage] | None = None,
        system_prompt: str = CHAT_SYSTEM_PROMPT,
    ) -> LLMResponse:
        result = await self._provider.generate(
            self.build_messages(message, history=history, system_prompt=system_prompt)
        )
        return result

    def supports_streaming(self) -> bool:
        """True when the underlying provider streams tokens incrementally.

        Duck-typed: test fakes and third-party providers may not implement the
        optional capability at all.
        """
        checker = getattr(self._provider, "supports_streaming", None)
        return bool(checker and checker())

    async def run_stream(  # noqa: RUF029 - generator by design
        self,
        message: str,
        *,
        history: list[LLMMessage] | None = None,
        system_prompt: str = CHAT_SYSTEM_PROMPT,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Stream one chat turn; terminal event carries the aggregated response.

        Falls back to a single delta when the provider cannot stream — callers
        get an identical event shape either way.
        """
        messages = self.build_messages(
            message, history=history, system_prompt=system_prompt
        )
        stream = getattr(self._provider, "generate_stream", None)
        if stream is None:
            response = await self._provider.generate(messages)
            yield LLMStreamEvent(delta=response.content, response=response)
            return
        async for event in stream(messages):
            yield event


def get_chat_workflow() -> ChatWorkflow:
    """Factory used by the workflow registry (builds a provider from config)."""
    from app.llm.factory import get_llm_provider

    return ChatWorkflow(provider=get_llm_provider())