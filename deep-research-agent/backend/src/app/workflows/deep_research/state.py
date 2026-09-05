"""Deep research workflow state schema (Pydantic).

Represents the current run only — separate from long-term memory and from persisted
evidence/knowledge stores. Uses typed structures for agent outputs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.memory.schemas import MemoryContextItem


class ResearchState(BaseModel):
    """Workflow state for a single deep research execution.

    Represents the *current run* only — deliberately separate from long-term memory
    and from persisted evidence/knowledge stores.
    """

    run_id: str = Field(default_factory=lambda: "")
    topic: str = ""
    plan: Any = None  # planner output (list of sub-questions/tasks)
    # Phase 9: relevant long-term user memories as planner *context* (never
    # evidence, never citable). Populated by load_context when enabled.
    memories: list[MemoryContextItem] = Field(default_factory=list)
    # Phase 8: documents attached to this job (empty = web-only research).
    document_ids: list[str] = Field(default_factory=list)
    available_documents: list[str] = Field(default_factory=list)  # filenames only
    tasks: list[Any] = Field(default_factory=list)  # created research tasks
    task_results: list[Any] = Field(default_factory=list)  # per-task results
    final_report: str = ""
    errors: list[str] = Field(default_factory=list)
    iterations: int = 0
    status: str = "pending"
