"""Guardrails (Phase B2): thin, in-house protection for the research pipeline.

Three independent guards, each a small class with a clean interface so a
framework (NeMo Guardrails, Llama Guard, Presidio…) can be slotted in later
without touching call sites:

- :mod:`app.guardrails.input_policy` — validates user queries *before* a job
  is created (length caps, injection heuristics, basic abuse filtering) and
  rejects with a clean 422.
- :mod:`app.guardrails.content` — treats fetched web content as *data, never
  instructions*: delimited + labeled blocks in agent prompts and
  instruction-pattern flagging for observability.
- :mod:`app.guardrails.budget` — hard per-job token ceiling enforced inside
  the research loop; exceeded jobs fail with a clear reason instead of
  silently overspending.
"""

from __future__ import annotations

from app.guardrails.budget import BudgetExceededError, JobBudgetTracker
from app.guardrails.content import (
    UNTRUSTED_BLOCK_END,
    UNTRUSTED_BLOCK_START,
    UNTRUSTED_DATA_PREAMBLE,
    delimit_untrusted,
    flag_injection_patterns,
)
from app.guardrails.input_policy import InputPolicyGuard

__all__ = [
    "BudgetExceededError",
    "InputPolicyGuard",
    "JobBudgetTracker",
    "UNTRUSTED_BLOCK_END",
    "UNTRUSTED_BLOCK_START",
    "UNTRUSTED_DATA_PREAMBLE",
    "delimit_untrusted",
    "flag_injection_patterns",
]
