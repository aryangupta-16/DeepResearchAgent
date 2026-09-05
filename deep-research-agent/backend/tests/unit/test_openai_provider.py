"""Unit tests for the OpenAI provider translation/mapping logic.

The provider SDK (``openai.AsyncOpenAI``) is replaced with a fake client, so no
real API calls or keys are required.
"""

import pytest
from openai import APIConnectionError, AuthenticationError, RateLimitError

from app.common.exceptions import LLMProviderError, LLMRequestError
from app.llm.base import LLMMessage
from app.llm.providers.openai import OpenAIProvider


class _StubRequest:
    pass


class _StubResponse:
    def __init__(self, status_code: int = 401) -> None:
        self.status_code = status_code
        self.request = _StubRequest()
        self.headers = {}


class _ChoiceMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _ChoiceMessage(content)


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class _Completion:
    def __init__(self, content: str, *, with_usage: bool) -> None:
        self.choices = [_Choice(content)]
        self.usage = _Usage() if with_usage else None


class _FakeCompletions:
    def __init__(self, *, error: Exception | None = None, with_usage: bool = True) -> None:
        self.error = error
        self.with_usage = with_usage
        self.last_kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> _Completion:
        self.last_kwargs = kwargs
        if self.error is not None:
            raise self.error
        return _Completion("hi", with_usage=self.with_usage)


class _FakeClient:
    def __init__(self, *, error: Exception | None = None, with_usage: bool = True) -> None:
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions(error=error, with_usage=with_usage)


def _provider(client: _FakeClient) -> OpenAIProvider:
    provider = OpenAIProvider(api_key="sk-test", model="gpt-x")
    provider._client = client
    return provider


async def test_openai_translates_messages_and_maps_response() -> None:
    client = _FakeClient()
    provider = _provider(client)

    response = await provider.generate(
        [LLMMessage(role="user", content="hi")], temperature=0.5
    )

    sent = client.chat.completions.last_kwargs
    assert sent["model"] == "gpt-x"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert sent["temperature"] == 0.5

    assert response.content == "hi"
    assert response.model == "gpt-x"
    assert response.provider == "openai"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 5
    assert response.usage.total_tokens == 15


async def test_openai_passes_max_tokens() -> None:
    client = _FakeClient()
    provider = _provider(client)
    await provider.generate([LLMMessage(role="user", content="hi")], max_tokens=64)
    assert client.chat.completions.last_kwargs["max_tokens"] == 64


async def test_openai_handles_missing_usage() -> None:
    client = _FakeClient(with_usage=False)
    provider = _provider(client)
    response = await provider.generate([LLMMessage(role="user", content="hi")])
    assert response.usage is None


async def test_openai_auth_error_maps_to_request_error() -> None:
    client = _FakeClient(error=AuthenticationError("bad", response=_StubResponse(), body=None))
    provider = _provider(client)
    with pytest.raises(LLMRequestError):
        await provider.generate([LLMMessage(role="user", content="hi")])


async def test_openai_rate_limit_maps_to_provider_error() -> None:
    client = _FakeClient(error=RateLimitError("rl", response=_StubResponse(429), body=None))
    provider = _provider(client)
    with pytest.raises(LLMProviderError):
        await provider.generate([LLMMessage(role="user", content="hi")])


async def test_openai_connection_error_maps_to_provider_error() -> None:
    client = _FakeClient(
        error=APIConnectionError(message="no route", request=_StubRequest())
    )
    provider = _provider(client)
    with pytest.raises(LLMProviderError):
        await provider.generate([LLMMessage(role="user", content="hi")])