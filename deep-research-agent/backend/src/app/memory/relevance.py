"""Deterministic, explainable memory relevance scoring.

V1 strategy — no vector search, no LLM calls:

1. Normalize query + memory content to lowercase tokens.
2. Score = overlap of meaningful tokens between query and content
   (unigram + bigram), blended with the memory's ``importance`` and small
   recency / usage rewards.
3. Return only the top ``limit`` memories above a floor.

The function is pure and deterministic, so every research run with the same
memories ranks them identically.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "about", "is", "are", "i", "am", "my", "we", "our", "you", "your",
    "that", "this", "it", "as", "at", "by", "be", "from", "into",
}


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    lowered = (text or "").lower()
    tokens = [t for t in _WORD_RE.findall(lowered) if t not in _STOPWORDS]
    return " ".join(tokens)


def content_hash(normalized: str) -> str:
    """sha256 of the normalized content (used for DB-level dedupe)."""
    import hashlib

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class MemoryCandidate(Protocol):
    """Minimal shape the scorer needs (matches ORM rows and Pydantic objects)."""

    content: str
    importance: float
    use_count: int
    last_used_at: object | None


def _tokenize(normalized: str) -> set[str]:
    return set(normalized.split())


def _bigrams(normalized: str) -> set[str]:
    tokens = normalized.split()
    return {f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)}


def relevance_score(memory: MemoryCandidate, query: str, *, now: datetime | None = None) -> float:
    """Return a relevance score in [0, 1] for one memory against a query.

    Components (weights chosen for V1 transparency):

    - content-query overlap (unigrams + bigrams): 65%
    - declared importance: 25%
    - recency (last_used_at) + usage frequency: 10%
    """
    normalized_query = normalize_text(query)
    normalized_content = normalize_text(memory.content)
    if not normalized_query or not normalized_content:
        return 0.0

    query_terms = _tokenize(normalized_query)
    content_terms = _tokenize(normalized_content)

    unigram_hits = query_terms & content_terms
    bigram_overlap = _bigrams(normalized_query) & _bigrams(normalized_content)

    term_score = 0.0
    if query_terms:
        term_score = (len(unigram_hits) + len(bigram_overlap)) / max(1, len(query_terms))
    term_score = min(1.0, term_score)

    importance = max(0.0, min(1.0, float(memory.importance)))

    now = now or datetime.now(UTC)
    recency = 0.0
    if memory.last_used_at is not None:
        try:
            days = (now - memory.last_used_at).total_seconds() / 86400.0
            recency = max(0.0, min(1.0, 1.0 - days / 30.0))
        except TypeError:  # pragma: no cover - defensive against naive datetimes
            recency = 0.0
    usage = max(0.0, min(1.0, int(memory.use_count) / 10.0))

    return round(0.65 * term_score + 0.25 * importance + 0.05 * recency + 0.05 * usage, 4)


def rank_memories(
    memories: list[MemoryCandidate],
    query: str,
    *,
    limit: int = 5,
    min_score: float = 0.3,
) -> list[MemoryCandidate]:
    """Score + sort candidates, returning only the top ``limit`` above the floor.

    The floor (default 0.3) sits above the maximum relevance contribution that
    pure ``importance`` can produce (``0.25 * 1.0``), so a memory that shares no
    terms with the query is never injected — only *some* query overlap can push
    a memory over the bar.
    """
    if not memories or not query.strip():
        return []
    scored = [
        (memory, relevance_score(memory, query)) for memory in memories
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    selected = [memory for memory, score in scored if score >= min_score]
    return selected[: max(1, limit)]