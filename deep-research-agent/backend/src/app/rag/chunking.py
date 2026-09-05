"""Deterministic RAG chunking.

Strategy (V1, deliberately simple):

1. Split each parsed page into paragraphs (blank-line separated).
2. Greedily pack consecutive paragraphs into a chunk until ``chunk_size``
   characters would be exceeded.
3. A single paragraph longer than ``chunk_size`` is hard-split on word
   boundaries with ``overlap`` characters of carry-over.
4. Every chunk records the 1-based page number it started on, so citations can
   always render "Document — Page N".

The algorithm is pure and deterministic: identical input always produces
identical chunks, which makes re-processing idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.tools.documents.parser import ParsedPage


@dataclass(frozen=True)
class ChunkDraft:
    """One produced chunk before persistence."""

    chunk_index: int
    page_number: int | None
    content: str


def chunk_pages(
    pages: list[ParsedPage],
    *,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[ChunkDraft]:
    """Chunk parsed pages into size-bounded, paragraph-aware drafts."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be in [0, chunk_size).")

    drafts: list[ChunkDraft] = []
    buffer: list[str] = []
    length = 0
    current_page: int | None = None

    def flush() -> None:
        nonlocal buffer, length, current_page
        if not buffer:
            return
        content = "\n\n".join(part for part in buffer if part)
        if content.strip():
            drafts.append(
                ChunkDraft(
                    chunk_index=len(drafts),
                    page_number=current_page,
                    content=content,
                )
            )
        buffer, length = [], 0

    for page in pages:
        for paragraph in _paragraphs(page.text):
            if not paragraph:
                continue

            # Hard-split oversized paragraphs on word boundaries.
            while len(paragraph) > chunk_size:
                flush()
                piece, paragraph = _split_with_overlap(paragraph, chunk_size, overlap)
                drafts.append(
                    ChunkDraft(
                        chunk_index=len(drafts),
                        page_number=page.page_number,
                        content=piece,
                    )
                )

            # Start a new chunk when adding this paragraph would overflow, or when
            # moving to a different page (keeps page metadata unambiguous).
            new_page = current_page is not None and current_page != page.page_number
            if buffer and (length + len(paragraph) > chunk_size or new_page):
                flush()

            if not buffer:
                current_page = page.page_number
            buffer.append(paragraph)
            length += len(paragraph) + 2  # account for the joining separator

    flush()
    return drafts


def _paragraphs(text: str) -> list[str]:
    """Split text into normalized paragraphs."""
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def _split_with_overlap(text: str, chunk_size: int, overlap: int) -> tuple[str, str]:
    """Cut ``text`` at ~``chunk_size`` chars, carrying back ``overlap`` chars.

    The cut lands after the last whole word that fits, so words are not chopped
    mid-token; the remainder keeps an overlapping tail for continuity.
    """
    window = text[:chunk_size]
    cut_at = window.rfind(" ")
    if cut_at <= 0:
        cut_at = chunk_size
    piece = text[:cut_at].strip()
    remainder = text[max(cut_at - overlap, 0):].strip()
    return piece, remainder