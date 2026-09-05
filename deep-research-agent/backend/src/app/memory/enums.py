"""Memory domain enums.

Memory intentionally has a small, flat ontology — the point is durable user
context, not a knowledge-graph taxonomy.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryType(StrEnum):
    """Durable categories of user memory (V1)."""

    PREFERENCE = "preference"
    INTEREST = "interest"
    GOAL = "goal"
    CONTEXT = "context"
    INSTRUCTION = "instruction"
    FACT = "fact"


class MemorySource(StrEnum):
    """How a memory was created.

    - ``explicit``: directly provided by the user (high confidence).
    - ``inferred``: derived from repeated behavior (V1 does not auto-persist
      inferred memories — it must be an explicit caller decision).
    """

    EXPLICIT = "explicit"
    INFERRED = "inferred"