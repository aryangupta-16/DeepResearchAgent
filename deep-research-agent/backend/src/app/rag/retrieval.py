"""Document retrieval service.

Responsibility boundary: embed a query, search the vector store, resolve hits to
canonical PostgreSQL chunks, and return structured results. It never generates
text, touches research jobs, or manages evidence persistence.
"""

from __future__ import annotations

import logging
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.repository import DocumentRepository
from app.infrastructure.database.models.document import DocumentChunk
from app.infrastructure.vector_db.client import PgVectorStore
from app.rag.embeddings import EmbeddingProvider
from app.rag.schemas import DocumentRetrievalResult

logger = logging.getLogger(__name__)


class DocumentRetrievalService:
    """Semantic retrieval over processed documents."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        vector_store: PgVectorStore | None = None,
        top_k: int = 6,
        min_score: float = 0.2,
    ) -> None:
        self._session = session
        self._embeddings = embedding_provider
        self._vector_store = vector_store or PgVectorStore()
        self._top_k = max(1, top_k)
        # Discard weak matches: below this, chunks would add noise to prompts.
        self._min_score = min_score

    async def retrieve(
        self,
        query: str,
        *,
        document_ids: list[UUID] | None = None,
        top_k: int | None = None,
    ) -> list[DocumentRetrievalResult]:
        """Return the most relevant chunks for ``query``.

        Args:
            query: natural-language query.
            document_ids: optional filter restricting retrieval to these documents.
            top_k: override for the configured maximum number of chunks.
        """
        if not query.strip():
            return []

        started = time.perf_counter()
        k = top_k or self._top_k

        query_vectors = await self._embeddings.embed_texts([query])
        hits = await self._vector_store.search_similar_chunks(
            query_vectors[0], top_k=k, document_ids=document_ids or None
        )
        hits = [hit for hit in hits if hit.score >= self._min_score]
        if not hits:
            logger.info("Retrieved 0 chunks (query length=%d).", len(query))
            return []

        chunk_ids = [hit.chunk_id for hit in hits]
        rows = await self._session.scalars(
            select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
        )
        by_id = {row.id: row for row in rows}

        documents_repo = DocumentRepository(self._session)
        document_names = {
            document.id: document.filename
            for document in await documents_repo.list_ready()
        }

        results: list[DocumentRetrievalResult] = []
        for hit in hits:  # preserve similarity order
            row = by_id.get(hit.chunk_id)
            if row is None:  # pragma: no cover - vector store is always consistent
                continue
            results.append(
                DocumentRetrievalResult(
                    chunk_id=str(row.id),
                    document_id=str(row.document_id),
                    document_name=document_names.get(row.document_id, "Unknown document"),
                    page_number=row.page_number,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    score=round(hit.score, 4),
                    metadata=dict(row.metadata_json or {}),
                )
            )

        logger.info(
            "Retrieved %d chunk(s) in %.0f ms (top score=%.3f).",
            len(results),
            (time.perf_counter() - started) * 1000,
            results[0].score if results else 0.0,
        )
        return results