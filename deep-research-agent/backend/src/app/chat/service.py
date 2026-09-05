"""Chat session domain service (Phase C1/C2).

Responsibilities (thin, single-concern):

- create / list / fetch / update / delete conversations,
- persist each turn (user + assistant),
- bound the prompt history to the last N messages (``chat_history_window``),
- auto-title a conversation from its first user message,
- record provider/model + token usage per assistant message (chat stays visible
  in cost accounting, separate from research ``job_usage``),
- optional document grounding (``context_mode="documents"``): retrieve relevant
  uploaded-document excerpts, inject a cited context block, and persist only
  the citations the reply actually used (``[C#]`` markers → snapshots).

Chat is synchronous request/response by design — routing seconds-latency turns
through the outbox/worker queue would be architecture tourism (Phase C tradeoff
note in the plan). Deep research stays async; the lifecycles never mix.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.citations import extract_citations
from app.chat.context import (
    ChatContextProvider,
    ChatDocumentSource,
    build_grounded_system_prompt,
)
from app.chat.repository import ConversationRepository
from app.chat.schemas import (
    ChatCitation,
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
)
from app.common.exceptions import (
    AppError,
    ConversationNotFoundError,
    ValidationError,
)
from app.infrastructure.database.models.conversation import ChatMessage, Conversation
from app.llm.base import LLMMessage, LLMProvider, LLMResponse
from app.memory.service import MemoryService
from app.workflows.chat.prompts import CHAT_SYSTEM_PROMPT
from app.workflows.chat.workflow import ChatWorkflow

logger = logging.getLogger(__name__)

#: Max characters of the first user message used as the auto title.
_TITLE_MAX_CHARS = 80

#: Valid ``context_mode`` values (mirrors the schema Literal).
_VALID_CONTEXT_MODES = {"none", "documents"}


class ChatSessionService:
    """Conversational quick answers with durable history."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: LLMProvider | None = None,
        workflow: ChatWorkflow | None = None,
        repository: ConversationRepository | None = None,
        history_window: int = 20,
        context_provider: ChatContextProvider | None = None,
        retrieval_top_k: int = 4,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._session = session
        self._repo = repository or ConversationRepository(session)
        if workflow is not None:
            self._workflow = workflow
        elif provider is not None:
            self._workflow = ChatWorkflow(provider=provider)
        else:
            from app.llm.factory import get_llm_provider

            self._workflow = ChatWorkflow(provider=get_llm_provider())
        self._history_window = max(1, history_window)
        self._context_provider = context_provider
        self._retrieval_top_k = max(1, retrieval_top_k)
        self._memory_service = memory_service

    # ---- Conversation lifecycle ----

    async def create_conversation(
        self, payload: ConversationCreate, *, owner_id: str | None = None
    ) -> Conversation:
        conversation = Conversation(
            title=payload.title,
            owner_id=owner_id,
            context_mode=payload.context_mode,
        )
        created = await self._repo.create(conversation)
        await self._commit()
        logger.info("Conversation created id=%s", created.id)
        return created

    async def list_conversations(
        self, *, owner_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        return await self._repo.list(owner_id=owner_id, limit=limit, offset=offset)

    async def get_conversation(self, conversation_id: UUID) -> Conversation:
        conversation = await self._repo.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} not found."
            )
        return conversation

    async def update_conversation(
        self, conversation_id: UUID, payload: ConversationUpdate
    ) -> Conversation:
        """Update a conversation (currently only the context mode)."""
        conversation = await self.get_conversation(conversation_id)
        if payload.context_mode not in _VALID_CONTEXT_MODES:
            raise ValidationError(
                f"Unknown context_mode {payload.context_mode!r} "
                f"(expected one of {sorted(_VALID_CONTEXT_MODES)})."
            )
        conversation.context_mode = payload.context_mode
        await self._commit()
        await self._session.refresh(conversation)
        logger.info(
            "Conversation updated id=%s context_mode=%s",
            conversation.id,
            conversation.context_mode,
        )
        return conversation

    async def delete_conversation(self, conversation_id: UUID) -> None:
        removed = await self._repo.delete(conversation_id)
        if not removed:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} not found."
            )
        await self._commit()
        logger.info("Conversation deleted id=%s", conversation_id)

    # ---- Turns ----

    async def send_message(
        self, conversation_id: UUID, payload: MessageCreate
    ) -> ChatMessage:
        """Persist the user turn, reply through the LLM, persist the answer.

        Returns the assistant :class:`ChatMessage` (usage + citations included).
        The prompt history is windowed to the last ``history_window`` messages
        so prompts stay bounded no matter how long the conversation runs.

        In ``documents`` context mode the turn is grounded in uploaded-document
        excerpts: retrieval runs first, the system prompt gains a cited context
        block, and only the ``[C#]`` markers the reply actually used become
        persisted citations.
        """
        content = payload.content.strip()
        if not content:
            raise ValidationError("Message content contains no usable text.")

        conversation = await self.get_conversation(conversation_id)
        history, context_sources, system_prompt = await self._prepare_turn(
            conversation, content
        )

        # Persist the user turn (the answer must never be lost mid-turn
        # without the question that produced it).
        await self._repo.append_message(
            ChatMessage(conversation_id=conversation.id, role="user", content=content)
        )
        if conversation.title is None:
            conversation.title = self._derive_title(content)

        # Reply through the shared provider layer.
        result = await self._workflow.run(
            content, history=history, system_prompt=system_prompt
        )

        # Persist the assistant turn with usage metadata + citations.
        citations = extract_citations(result.content, context_sources)
        assistant_message = await self._persist_assistant(
            conversation, result, citations
        )
        logger.info(
            "Chat turn completed conversation=%s prompt_tokens=%s "
            "completion_tokens=%s citations=%d",
            conversation.id,
            assistant_message.prompt_tokens,
            assistant_message.completion_tokens,
            len(citations),
        )
        return assistant_message

    # ---- Turn plumbing (shared by sync + streaming paths) ----

    async def _prepare_turn(
        self, conversation: Conversation, content: str
    ) -> tuple[list[LLMMessage], list[ChatDocumentSource], str]:
        """Bounded history + optional grounding; persists nothing.

        The current turn is *excluded*: history is read before the user message
        is appended so it never eats into the window.
        """
        history_rows = await self._repo.list_messages(
            conversation.id,
            window=self._history_window,
        )
        history = [LLMMessage(role=row.role, content=row.content) for row in history_rows]

        context_sources: list[ChatDocumentSource] = []
        system_prompt = CHAT_SYSTEM_PROMPT
        if conversation.context_mode == "documents":
            context_sources = await self._retrieve_context(content)
            if context_sources:
                system_prompt = build_grounded_system_prompt(context_sources)

        # Inject relevant long-term memories as personalization context.
        memory_block = await self._build_memory_block(content)
        if memory_block:
            system_prompt = f"{system_prompt}\n\n{memory_block}"
        return history, context_sources, system_prompt

    async def _persist_assistant(
        self,
        conversation: Conversation,
        result: LLMResponse,
        citations: list[ChatCitation],
    ) -> ChatMessage:
        assistant_message = await self._repo.append_message(
            ChatMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=result.content,
                model=result.model,
                provider=result.provider,
                prompt_tokens=result.usage.prompt_tokens if result.usage else None,
                completion_tokens=(
                    result.usage.completion_tokens if result.usage else None
                ),
                citations=(
                    [citation.model_dump() for citation in citations] or None
                ),
            )
        )
        await self._commit()
        await self._session.refresh(assistant_message)
        return assistant_message

    async def stream_turn(  # noqa: RUF029 - generator by design
        self, conversation_id: UUID, payload: MessageCreate
    ):
        """Streaming variant of :meth:`send_message` for SSE transport.

        Yields framework-agnostic event dicts the route serializes into
        ``event:/data:`` frames:

        - ``start``: ``{"user_message_id": int}`` — user turn persisted
        - ``delta``: ``{"text": str}`` — incremental assistant text
        - ``done``: full assistant message payload (citations included)
        - ``error``: ``{"code": str, "message": str}`` — terminal failure

        The user turn is committed before streaming begins; the assistant turn
        is persisted only on success.
        """
        content = payload.content.strip()
        if not content:
            raise ValidationError("Message content contains no usable text.")

        conversation = await self.get_conversation(conversation_id)
        history, context_sources, system_prompt = await self._prepare_turn(
            conversation, content
        )
        user_message = await self._repo.append_message(
            ChatMessage(conversation_id=conversation.id, role="user", content=content)
        )
        if conversation.title is None:
            conversation.title = self._derive_title(content)
        await self._commit()
        yield {"event": "start", "data": {"user_message_id": user_message.id}}

        parts: list[str] = []
        result: LLMResponse | None = None
        try:
            async for event in self._workflow.run_stream(
                content, history=history, system_prompt=system_prompt
            ):
                if event.delta:
                    parts.append(event.delta)
                    yield {"event": "delta", "data": {"text": event.delta}}
                if event.response is not None:
                    result = event.response
        except AppError as exc:
            logger.warning(
                "Chat stream failed conversation=%s code=%s",
                conversation.id,
                exc.code,
            )
            yield {"event": "error", "data": {"code": exc.code, "message": exc.message}}
            return

        if result is None:  # defensive: stream ended without a terminal event
            result = LLMResponse(
                content="".join(parts), model="unknown", provider="unknown"
            )

        citations = extract_citations(result.content, context_sources)
        assistant_message = await self._persist_assistant(
            conversation, result, citations
        )
        logger.info(
            "Chat turn streamed conversation=%s prompt_tokens=%s "
            "completion_tokens=%s citations=%d",
            conversation.id,
            assistant_message.prompt_tokens,
            assistant_message.completion_tokens,
            len(citations),
        )
        yield {
            "event": "done",
            "data": MessageResponse.model_validate(assistant_message).model_dump(
                mode="json"
            ),
        }

    # ---- Context grounding ----

    async def _retrieve_context(self, content: str) -> list[ChatDocumentSource]:
        """Retrieve document context for a grounded turn (never raises)."""
        if self._context_provider is None:
            logger.info(
                "Context requested (%s) but no context provider is configured; "
                "answering without grounding.",
                self._context_provider,
            )
            return []
        try:
            return await self._context_provider.retrieve(
                content, limit=self._retrieval_top_k
            )
        except Exception:  # noqa: BLE001 - grounding is best-effort
            logger.warning(
                "Chat context retrieval failed; answering without grounding.",
                exc_info=True,
            )
            return []

    # ---- Long-term memory ----

    async def _build_memory_block(self, content: str) -> str | None:
        """Build a memory context block for the system prompt (never raises).

        Injects the most relevant active memories so the assistant can
        personalize its answer. Returns None when no memories exist or the
        memory service isn't configured.
        """
        if self._memory_service is None:
            return None
        try:
            memories = await self._memory_service.retrieve_relevant(content)
        except Exception:  # noqa: BLE001 - memory is best-effort
            logger.warning("Memory retrieval failed; proceeding without it.", exc_info=True)
            return None
        if not memories:
            return None
        lines = ["## Long-term memory", "Use the following facts about the user to personalize your answer. Do not mention this block itself."]
        for m in memories:
            lines.append(f"- {m.content}")
        return "\n".join(lines)

    # ---- Helpers ----

    @staticmethod
    def _derive_title(content: str) -> str:
        """First user message, first line, bounded — good enough for a list UI."""
        first_line = content.strip().splitlines()[0].strip()
        if len(first_line) > _TITLE_MAX_CHARS:
            return first_line[: _TITLE_MAX_CHARS - 1].rstrip() + "…"
        return first_line

    async def _commit(self) -> None:
        """Commit the current transaction, rolling back explicitly on failure."""
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
