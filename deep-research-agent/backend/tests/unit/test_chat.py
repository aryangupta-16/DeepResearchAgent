"""Unit tests for the chat workflow and chat service (mocked provider)."""

import pytest

from app.llm.base import LLMMessage, LLMResponse
from app.workflows.chat.schemas import ChatResponse
from app.workflows.chat.service import ChatService
from app.workflows.chat.workflow import ChatWorkflow


async def test_chat_workflow_builds_system_and_user_messages(fake_llm_provider) -> None:
    workflow = ChatWorkflow(provider=fake_llm_provider)
    await workflow.run("hello")

    assert len(fake_llm_provider.calls) == 1
    messages = fake_llm_provider.calls[0]
    assert messages[0].role == "system"
    assert messages[0].content
    assert messages[-1].role == "user"
    assert messages[-1].content == "hello"


async def test_chat_workflow_includes_history(fake_llm_provider) -> None:
    workflow = ChatWorkflow(provider=fake_llm_provider)
    history = [LLMMessage(role="assistant", content="prior answer")]
    await workflow.run("next", history=history)

    messages = fake_llm_provider.calls[0]
    contents = [m.content for m in messages]
    assert contents[1:] == ["prior answer", "next"]
    assert [m.role for m in messages] == ["system", "assistant", "user"]


async def test_chat_service_maps_response(fake_llm_provider) -> None:
    service = ChatService(provider=fake_llm_provider)
    response = await service.reply("hello")

    assert isinstance(response, ChatResponse)
    assert response.message == "fake reply"
    assert response.model == "fake-model"
    assert response.provider == "fake"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 3
    assert response.usage.completion_tokens == 4
    assert response.usage.total_tokens == 7


def test_chat_service_maps_response_without_usage() -> None:
    result = LLMResponse(content="hi", model="m", provider="openai", usage=None)
    response = ChatService._to_response(result)
    assert response.message == "hi"
    assert response.usage is None


def test_workflow_requires_provider() -> None:
    with pytest.raises(TypeError):
        ChatWorkflow()  # type: ignore[call-arg]