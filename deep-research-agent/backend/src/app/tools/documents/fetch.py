"""Document fetch / parse / chunk tools (placeholder interfaces)."""

from __future__ import annotations


def fetch_document(url: str, *, max_bytes: int = 10_000_000) -> bytes:
    """Download a document deterministically."""
    raise NotImplementedError("fetch_document not implemented yet.")


def parse_document(data: bytes, *, mime_type: str) -> str:
    """Extract plain text from a document (pdf/docx/etc.)."""
    raise NotImplementedError("parse_document not implemented yet.")


def chunk_text(text: str, *, max_chunk_size: int = 2000, overlap: int = 200) -> list[str]:
    """Split extracted text into chunks for RAG ingestion."""
    raise NotImplementedError("chunk_text not implemented yet.")