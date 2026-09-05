"""Citation marker extraction for grounded chat replies (Phase C2).

The model writes inline markers like ``[C1]`` when it uses a document excerpt.
Extraction is deliberately deterministic and conservative:

- markers are collected in first-seen order (stable UI numbering),
- a key is only accepted if it names a source that was actually offered,
- repeated markers of the same key are dropped (one citation per source),
- any marker not in the offered set is ignored — never surfaced, never guessed.

This mirrors the report validator's spirit (deterministic, source-anchored)
without hiring an LLM: the offered set is small and the format is pinned.
"""

from __future__ import annotations

import re

from app.chat.context import ChatDocumentSource
from app.chat.schemas import ChatCitation

_CITATION_MARKER = re.compile(r"\[([Cc])(\d+)\]")


def extract_citations(
    reply: str | None, sources: list[ChatDocumentSource]
) -> list[ChatCitation]:
    """Return the citations the reply actually uses, restricted to ``sources``."""
    if not reply:
        return []
    by_key = {source.citation_key: source for source in sources}
    seen: set[str] = set()
    citations: list[ChatCitation] = []

    for match in _CITATION_MARKER.finditer(reply) if reply else []:
        key = f"C{int(match.group(2))}"
        if key in seen or key not in by_key:
            continue
        seen.add(key)
        source = by_key[key]
        citations.append(
            ChatCitation(
                citation_key=key,
                document_id=source.document_id,
                document_name=source.document_name,
                page_number=source.page_number,
                excerpt=source.excerpt,
                score=source.score,
            )
        )
    return citations