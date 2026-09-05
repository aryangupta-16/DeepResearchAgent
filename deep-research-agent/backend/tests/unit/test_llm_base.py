"""Unit tests for the LLM abstraction (no network)."""

import pytest

from app.common.exceptions import LLMProviderError
from app.llm.base import AsyncLLMProvider, LLMMessage, LLMResponse, LLMUsage


def test_llm_message_construction() -> None:
    message = LLMMessage(role="user", content="hello")
    assert message.role == "user"
    assert message.content == "hello"


def test_llm_response_construction() -> None:
    usage = LLMUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    response = LLMResponse(
        content="hi", model="m", provider="openai", usage=usage
    )
    assert response.content == "hi"
    assert response.model == "m"
    assert response.usage == usage
    assert usage.total_tokens == 3


class _RaisingProvider(AsyncLLMProvider):
    name = "test"
    default_model = "m"

    def __init__(self, *, error: type[Exception]) -> None:
        super().__init__(api_key="k")
        self._error = error

    async def _generate(self, **kwargs: object) -> LLMResponse:
        raise self._error("boom")


async def test_generate_passes_through_app_errors() -> None:
    provider = _RaisingProvider(error=LLMProviderError)
    with pytest.raises(LLMProviderError):
        await provider.generate([LLMMessage(role="user", content="hi")])


async def test_generate_wraps_unexpected_exceptions() -> None:
    provider = _RaisingProvider(error=RuntimeError)
    with pytest.raises(LLMProviderError):
        await provider.generate([LLMMessage(role="user", content="hi")])


async def test_generate_uses_default_model() -> None:
    class _OkProvider(AsyncLLMProvider):
        name = "test"
        default_model = "mm"

        def __init__(self) -> None:
            super().__init__(api_key="k")

        async def _generate(self, **kwargs: object) -> LLMResponse:
            self.seen_model = kwargs["model"]
            return LLMResponse(content="ok", model=kwargs["model"], provider=self.name)

    provider = _OkProvider()
    response = await provider.generate([LLMMessage(role="user", content="hi")])
    assert provider.seen_model == "mm"  # type: ignore[attr-defined]
    assert response.content == "ok"