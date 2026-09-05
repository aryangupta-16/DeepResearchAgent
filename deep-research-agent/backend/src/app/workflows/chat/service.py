"""Chat application service.

The route delegates here; the service owns the workflow and maps the provider
response into the API schema. No LLM calls happen directly in routes.
"""

from __future__ import annotations

from app.llm.base import LLMMessage, LLMProvider, LLMResponse
from app.workflows.chat.schemas import ChatResponse, UsageResponse
from app.workflows.chat.workflow import ChatWorkflow


class ChatService:
    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        workflow: ChatWorkflow | None = None,
    ) -> None:
        if workflow is not None:
            self._workflow = workflow
        elif provider is not None:
            self._workflow = ChatWorkflow(provider=provider)
        else:
            from app.llm.factory import get_llm_provider

            self._workflow = ChatWorkflow(provider=get_llm_provider())

    async def reply(
        self,
        message: str,
        *,
        history: list[LLMMessage] | None = None,
    ) -> ChatResponse:
        result = await self._workflow.run(message, history=history)
        return self._to_response(result)

    @staticmethod
    def _to_response(result: LLMResponse) -> ChatResponse:
        usage: UsageResponse | None = None
        if result.usage is not None:
            usage = UsageResponse(
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                total_tokens=result.usage.total_tokens,
            )
        return ChatResponse(
            message=result.content,
            model=result.model,
            provider=result.provider,
            usage=usage,
        )