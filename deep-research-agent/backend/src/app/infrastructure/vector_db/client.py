"""Vector database client.

V1 implementation: **PostgreSQL + pgvector**. Chunk embeddings live on the
``document_chunks`` rows themselves (single source of truth — no duplicated
content in a second store), and similarity search runs as a ranked SQL query
using pgvector's cosine-distance operator with an HNSW index.

This keeps local development fully reproducible (one extra Docker image, zero
cloud services) while the interface below stays vendor-shaped: a future
specialized vector database can implement the same two methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.infrastructure.database.postgres import get_engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorSearchHit:
    """One similarity hit resolved to its canonical chunk."""

    chunk_id: UUID
    document_id: UUID
    score: float  # cosine similarity in [0, 1]


def _to_pg_vector(vector: list[float]) -> str:
    """Render a vector as a pgvector literal (``'[1,2,3]'``)."""
    return "[" + ",".join(f"{component:.8f}" for component in vector) + "]"


class PgVectorStore:
    """Similarity search over ``document_chunks.embedding`` via pgvector."""

    def __init__(self, engine: Any | None = None) -> None:
        self._engine = engine or get_engine()

    async def search_similar_chunks(
        self,
        query_vector: list[float],
        *,
        top_k: int = 6,
        document_ids: list[UUID] | None = None,
    ) -> list[VectorSearchHit]:
        """Return up to ``top_k`` chunks most similar to ``query_vector``.

        Cosine distance is converted to a similarity score in [0, 1]. When
        ``document_ids`` is provided, results are filtered to those documents.
        """
        if not query_vector:
            return []
        top_k = max(1, min(top_k, 50))

        filter_clause = ""
        params: dict[str, Any] = {
            "query_vector": _to_pg_vector(query_vector),
            "top_k": top_k,
        }
        if document_ids:
            # Bind as a Postgres uuid[] literal and cast explicitly. ANY() over a
            # bare string is type-ambiguous (and psycopg does not infer uuid[]),
            # so we pass the string and let the server cast it.
            params["document_ids"] = "{" + ",".join(str(u) for u in document_ids) + "}"
            filter_clause = "AND document_id = ANY(CAST(:document_ids AS uuid[]))"

        sql = text(
            f"""
            SELECT id AS chunk_id,
                   document_id,
                   1 - (embedding <=> CAST(:query_vector AS vector)) AS score
            FROM document_chunks
            WHERE embedding IS NOT NULL
              {filter_clause}
            ORDER BY embedding <=> CAST(:query_vector AS vector)
            LIMIT :top_k
            """
        )

        async with self._engine.connect() as connection:
            result = await connection.execute(sql, params)
            rows = result.fetchall()

        hits = [
            VectorSearchHit(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                score=max(0.0, min(1.0, float(row.score))),
            )
            for row in rows
        ]
        logger.debug("Vector search returned %d hit(s).", len(hits))
        return hits