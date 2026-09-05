"""RAG (searchable knowledge) ingestion (placeholder)."""

from __future__ import annotations


class IngestionService:
    """Ingests documents into the searchable knowledge base."""

    async def ingest(self, *, url: str, bytes_: bytes) -> str:
        raise NotImplementedError("IngestionService not implemented yet.")