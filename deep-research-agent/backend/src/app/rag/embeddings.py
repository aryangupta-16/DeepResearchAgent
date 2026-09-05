"""Embedding abstraction.

The document pipeline depends on this interface only — never on a vendor SDK.
Providers live in :mod:`app.rag.providers` (mirroring ``app.llm.providers``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.common.exceptions import NotConfiguredError


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface for embedding text into dense vectors."""

    name: str
    model: str
    dimensions: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts; returns one vector per input, same order."""
        ...


def build_embedding_provider() -> EmbeddingProvider | None:
    """Factory: build the configured embedding provider from settings.

    Returns ``None`` when no embedding provider is configured
    (``EMBEDDING_PROVIDER`` empty). Callers decide whether that is an error:
    web-only research runs fine without it, while document *processing* requires
    it and must fail loudly at that point.
    """
    from app.config.settings import get_settings

    settings = get_settings()
    selected = (settings.embedding_provider or "").strip().lower()
    if not selected:
        return None

    if selected == "openai":
        if not settings.openai_api_key:
            raise NotConfiguredError(
                "EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY."
            )
        from app.rag.providers.openai import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.embedding_model or "text-embedding-3-small",
            timeout=settings.embedding_timeout,
            batch_size=settings.document_embedding_batch_size,
        )

    raise NotConfiguredError(f"Unsupported EMBEDDING_PROVIDER {selected!r}.")