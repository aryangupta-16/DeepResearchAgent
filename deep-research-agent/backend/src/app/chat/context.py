"""Document grounding for chat sessions (Phase C2).

When a conversation's ``context_mode`` is ``documents``, the chat turn grounds
itself in the *same* RAG stack the research pipeline uses: embed the question,
retrieve document chunks via :class:`DocumentRetrievalService`, and hand the
model a labeled, delimited context block (the guardrail wrapper — RAG excerpts
are untrusted data, never instructions).

The citation keys ``[C1]…[Cn]`` follow the order of retrieved chunks, and only
those keys may ever appear in the reply (see :mod:`app.chat.citations`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.guardrails.content import delimit_untrusted
from app.rag.retrieval import DocumentRetrievalService
from app.workflows.chat.prompts import CHAT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatDocumentSource:
    """One retrieved document excerpt offered to the chat model."""

    citation_key: str  # ``C1``, ``C2``, … (the only marker allowed in the reply)
    document_id: str
    document_name: str
    page_number: int | None
    excerpt: str
    score: float


class ChatContextProvider(Protocol):
    """Retrieval boundary for grounded chat turns (injectable in tests)."""

    async def retrieve(self, query: str, *, limit: int) -> list[ChatDocumentSource]:
        """Return up to ``limit`` document sources relevant to ``query``.

        Callers treat retrieval failures as *no context* — a chat turn must
        degrade gracefully, never fail, when grounding is unavailable.
        """
        ...


class DocumentContextProvider:
    """Grounded-chat provider over the production document RAG stack."""

    def __init__(self, retrieval: DocumentRetrievalService) -> None:
        self._retrieval = retrieval

    async def retrieve(self, query: str, *, limit: int) -> list[ChatDocumentSource]:
        try:
            results = await self._retrieval.retrieve(query, top_k=max(1, limit))
        except Exception:  # noqa: BLE001 - grounding is best-effort
            logger.warning(
                "Chat document retrieval failed; answering without grounding.",
                exc_info=True,
            )
            return []
        return [
            ChatDocumentSource(
                citation_key=f"C{i + 1}",
                document_id=row.document_id,
                document_name=row.document_name,
                page_number=row.page_number,
                excerpt=row.content,
                score=row.score,
            )
            for i, row in enumerate(results)
        ]


def build_grounded_system_prompt(sources: list[ChatDocumentSource]) -> str:
    """Augment the chat system prompt with a cited, delimited context block.

    The excerpt bodies are wrapped by :func:`delimit_untrusted` (data-not-
    instructions + injection-flag observability), and the prompt pins the
    citation contract: only the listed ``[C#]`` keys may appear, inline, next
    to the claims they back.
    """
    if not sources:
        return CHAT_SYSTEM_PROMPT

    blocks: list[str] = []
    for source in sources:
        head = f"[{source.citation_key}] {source.document_name}"
        if source.page_number is not None:
            head += f" (page {source.page_number})"
        blocks.append(f"{head}\n{source.excerpt}")

    wrapped = delimit_untrusted("chat-document-context", "\n\n".join(blocks))
    return (
        f"{CHAT_SYSTEM_PROMPT}\n\n"
        "Document context is provided for this turn. Ground your answer in it. "
        "After each sentence that uses a fact from the context, add an inline "
        "citation like [C1] that matches the key shown next to that excerpt. "
        "Cite only the keys listed below — never invent citation keys. "
        "If the context does not answer the question, say that clearly and "
        "answer briefly from your own knowledge without citing.\n\n"
        f"{wrapped}"
    )