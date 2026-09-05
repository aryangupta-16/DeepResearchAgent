"""OpenAI embeddings provider.

The only module that knows about the OpenAI embeddings SDK. Inputs are batched
(``DOCUMENT_EMBEDDING_BATCH_SIZE``) so a large document becomes a handful of
network calls instead of one request per chunk.
"""

from __future__ import annotations

import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider:
    """Embed texts via the OpenAI ``/embeddings`` endpoint."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        timeout: float = 60.0,
        batch_size: int = 64,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)
        # Explicit base URL (mirrors the LLM provider): an empty exported
        # OPENAI_BASE_URL would otherwise break SDK request construction.
        resolved_base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "").strip()
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=resolved_base_url or "https://api.openai.com/v1",
            timeout=timeout,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` in batches; returns vectors in input order."""
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = await self._client.embeddings.create(
                input=batch,
                model=self.model,
            )
            batch_vectors = [item.embedding for item in response.data]
            if len(batch_vectors) != len(batch):
                logger.warning(
                    "Embedding batch size mismatch: sent=%d received=%d",
                    len(batch), len(batch_vectors),
                )
            vectors.extend(batch_vectors)
            logger.debug(
                "Embedded batch of %d text(s) with %s/%s.",
                len(batch), self.name, self.model,
            )

        if len(vectors) != len(texts):
            raise ValueError(
                f"Embedding provider returned {len(vectors)} vectors "
                f"for {len(texts)} inputs."
            )
        return vectors