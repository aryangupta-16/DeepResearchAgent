"""Input policy guard: validates user research queries before job creation.

Rejects with :class:`app.common.exceptions.ValidationError` (HTTP 422) so the
API contract stays clean — malformed or abusive input never reaches the
pipeline. Kept deliberately conservative: a false rejection wastes a legitimate
research request, so heuristics target *unambiguous* hijack/abuse patterns only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.common.exceptions import ValidationError

# Unambiguous instruction-hijack patterns (case-insensitive). Intentionally
# narrow — "ignore previous instructions"-style attacks, not topic keywords
# that merely *mention* prompts.
_HIJACK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ignore_previous", r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions"),
    ("disregard_rules", r"disregard\s+(all\s+|any\s+)?(\w+\s+){0,2}"
                        r"(instructions|rules|guidelines|constraints)"),
    ("role_override", r"you\s+are\s+now\s+(a|an|the)"),
    ("system_prompt_probe", r"(reveal|show|print|repeat)\s+your\s+"
                            r"(system\s+)?(prompt|instructions)"),
    ("new_instructions", r"(new|updated)\s+(system\s+)?instructions\s*:"),
    ("developer_mode", r"(enter|enable|activate)\s+(developer|god|dan)\s+mode"),
)

# Basic abuse signals: control characters (except tab/newline) and extreme
# character repetition.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CHAR_SPAM = re.compile(r"(.)\1{40,}")


@dataclass(frozen=True)
class InputPolicyDecision:
    """Outcome of evaluating one query against the input policy."""

    accepted: bool
    normalized_query: str = ""
    violations: list[str] = field(default_factory=list)


class InputPolicyGuard:
    """Validates a research query; raises ``ValidationError`` on rejection."""

    def __init__(
        self,
        *,
        min_length: int = 3,
        max_length: int = 2000,
    ) -> None:
        self._min_length = max(1, min_length)
        self._max_length = max(self._min_length, max_length)

    def assess(self, query: str) -> InputPolicyDecision:
        """Evaluate the query without raising (exposed for tests/logging)."""
        normalized = " ".join((query or "").split())
        violations: list[str] = []

        if len(normalized) < self._min_length:
            violations.append(
                f"query too short (minimum {self._min_length} characters)"
            )
        if len(normalized) > self._max_length:
            violations.append(
                f"query too long (maximum {self._max_length} characters)"
            )
        if _CONTROL_CHARS.search(normalized):
            violations.append("query contains control characters")
        if _CHAR_SPAM.search(normalized):
            violations.append("query contains character spam")

        lowered = normalized.lower()
        for name, pattern in _HIJACK_PATTERNS:
            if re.search(pattern, lowered):
                violations.append(f"injection pattern detected: {name}")

        return InputPolicyDecision(
            accepted=not violations,
            normalized_query=normalized,
            violations=violations,
        )

    def check(self, query: str) -> str:
        """Validate and return the normalized query, or raise ``ValidationError``.

        The error message is deliberately generic: it never echoes which
        heuristic fired, so would-be attackers get no feedback for tuning.
        """
        decision = self.assess(query)
        if not decision.accepted:
            raise ValidationError(
                "Query rejected by the input policy. Please revise and retry."
            )
        return decision.normalized_query
