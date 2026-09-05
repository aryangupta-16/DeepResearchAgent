"""Unit tests for the long-term memory domain (Phase 9).

Covers: memory enums, schema validation, LLM extraction (validated output only),
and the planner-prompt boundary that keeps memory strictly *context*.
PostgreSQL-backed behaviour lives in the integration suite.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.agents.planner.prompts import build_planner_prompt
from app.common.exceptions import (
    MemoryNotFoundError,
    NotConfiguredError,
)
from app.common.exceptions import (
    ValidationError as AppValidationError,
)
from app.infrastructure.database.models.memory import Memory
from app.memory.enums import MemorySource, MemoryType
from app.memory.extraction import MemoryExtractor
from app.memory.relevance import content_hash, normalize_text, rank_memories, relevance_score
from app.memory.schemas import (
    MemoryContext,
    MemoryContextItem,
    MemoryCreate,
    MemoryExtractionItem,
    MemoryExtractionResult,
    MemoryUpdate,
)
from app.memory.service import MemoryService

# ---- Enums ----


def test_memory_type_enum_values() -> None:
    expected = {"preference", "interest", "goal", "context", "instruction", "fact"}
    assert {t.value for t in MemoryType} == expected


def test_memory_source_enum_values() -> None:
    assert {s.value for s in MemorySource} == {"explicit", "inferred"}


# ---- Schema validation ----


def test_memory_candidate_valid() -> None:
    candidate = MemoryExtractionItem(
        content="User is interested in humanoid robotics startups.",
        memory_type="interest",
        importance=0.8,
        source="explicit",
    )
    assert candidate.content.startswith("User is interested")
    assert getattr(candidate.memory_type, "value", candidate.memory_type) == "interest"
    assert getattr(candidate.source, "value", candidate.source) == "explicit"


def test_memory_candidate_rejects_unknown_type() -> None:
    with pytest.raises(PydanticValidationError):
        MemoryExtractionItem(
            content="x", memory_type="brand-preference", importance=0.5
        )


def test_memory_candidate_rejects_importance_out_of_range() -> None:
    for bad in (1.5, -0.1, 2.0):
        with pytest.raises(PydanticValidationError):
            MemoryExtractionItem(content="x", memory_type="interest", importance=bad)


def test_memory_candidate_rejects_empty_content() -> None:
    with pytest.raises(PydanticValidationError):
        MemoryExtractionItem(content="", memory_type="interest")


def test_memory_create_minimal() -> None:
    created = MemoryCreate(content="I am interested in robotics startups.")
    assert created.content.endswith("startups.")


def test_memory_create_rejects_empty() -> None:
    with pytest.raises(PydanticValidationError):
        MemoryCreate(content="   ")


def test_memory_update_all_optional() -> None:
    payload = MemoryUpdate()
    assert payload.importance is None
    assert payload.is_active is None
    partial = MemoryUpdate(importance=0.5)
    assert partial.importance == 0.5


# ---- LLM extraction (validated, never auto-persisted) ----


class _ScriptedProvider:
    """Minimal LLMProvider stand-in returning a fixed ``.content``."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = 0

    async def generate(self, messages):  # noqa: ANN001
        self.calls += 1
        return SimpleNamespace(content=self._content)


_VALID_PAYLOAD = json.dumps(
    {
        "memories": [
            {
                "content": "User is interested in humanoid robotics startups.",
                "memory_type": "interest",
                "importance": 0.8,
                "source": "explicit",
            }
        ]
    }
)


async def test_extraction_parses_valid_output() -> None:
    provider = _ScriptedProvider(_VALID_PAYLOAD)
    result = await MemoryExtractor(provider).extract("Remember that I like robots.")
    assert isinstance(result, MemoryExtractionResult)
    assert len(result.memories) == 1
    assert result.memories[0].content.startswith("User is interested")
    assert provider.calls == 1


async def test_extraction_malformed_json_never_yields_memories() -> None:
    provider = _ScriptedProvider("this is not json at all")
    with pytest.raises(AppValidationError):
        await MemoryExtractor(provider).extract("hello")


async def test_extraction_non_object_output_rejected() -> None:
    provider = _ScriptedProvider('["i like ai", "another string"]')
    with pytest.raises(AppValidationError):
        await MemoryExtractor(provider).extract("hello")


async def test_extraction_memory_of_unknown_type_rejected() -> None:
    provider = _ScriptedProvider(
        json.dumps({"memories": [{"content": "x", "memory_type": "vibe"}]})
    )
    with pytest.raises(AppValidationError):
        await MemoryExtractor(provider).extract("hello")


async def test_extraction_invalid_item_rejects_whole_output() -> None:
    # Validation is strict: one malformed candidate rejects the entire result so
    # malformed LLM output can never partially reach the store.
    provider = _ScriptedProvider(
        json.dumps(
            {
                "memories": [
                    {"content": "", "memory_type": "interest"},
                    {
                        "content": "User prefers concise reports.",
                        "memory_type": "preference",
                        "importance": 0.6,
                        "source": "explicit",
                    },
                ]
            }
        )
    )
    with pytest.raises(AppValidationError):
        await MemoryExtractor(provider).extract("hello")


# ---- Planner boundary: memory is CONTEXT, never evidence ----


def test_planner_prompt_includes_memory_as_user_context() -> None:
    prompt = build_planner_prompt(
        "latest humanoid robotics companies",
        user_context=["User is interested in humanoid robotics startups."],
    )
    assert "User is interested in humanoid robotics startups." in prompt
    assert "USER CONTEXT" in prompt.upper()
    # Context must be framed as personalization, not as citable fact source.
    assert "context" in prompt.lower()


def test_planner_prompt_without_memory_has_no_context_block() -> None:
    prompt = build_planner_prompt("latest humanoid robotics companies")
    assert "USER CONTEXT" not in prompt.upper()


# ---- Relevance scoring (pure, deterministic, no DB) ----


def _mem(content: str, *, importance: float = 0.5, use_count: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        content=content, importance=importance, use_count=use_count, last_used_at=None
    )


def test_normalize_text_lowercases_and_strips_stopwords() -> None:
    assert normalize_text("I am interested in AI!") == "interested ai"


def test_content_hash_is_deterministic() -> None:
    # Real call pattern: normalize first, then hash (dedupe key for the DB).
    assert content_hash(normalize_text("interested ai")) == content_hash(
        normalize_text("  INTERESTED Ai! ")
    )
    assert content_hash(normalize_text("one thing")) != content_hash(
        normalize_text("another thing")
    )


def test_relevance_score_prefers_query_overlap() -> None:
    score = relevance_score(_mem("robotics startups"), "robotics")
    unrelated = relevance_score(_mem("cooking recipes"), "robotics")
    assert score > 0.2
    assert unrelated < score


def test_relevance_score_weighs_importance() -> None:
    high = relevance_score(_mem("robotics", importance=1.0), "robotics")
    low = relevance_score(_mem("robotics", importance=0.0), "robotics")
    assert high > low


def test_rank_memories_orders_and_limits() -> None:
    memories = [
        _mem("cooking recipes", importance=1.0),
        _mem("robotics startups", importance=0.5),
    ]
    ranked = rank_memories(memories, "robotics startups", limit=1)
    assert len(ranked) == 1
    assert "robotics" in ranked[0].content


def test_rank_memories_blank_query_is_empty() -> None:
    assert rank_memories([_mem("anything")], "   ") == []


def test_rank_memories_drops_irrelevant_high_importance() -> None:
    # No query-term overlap -> score stays under the floor even at high importance:
    # memory must share some terms with the query to be injected at all.
    assert rank_memories([_mem("cooking recipes", importance=1.0)], "robotics") == []


# ---- Workflow context domain objects ----


def test_memory_context_content_lines() -> None:
    context = MemoryContext(
        memories=[
            MemoryContextItem(
                id="mem-1",
                content="User is interested in robotics.",
                memory_type="interest",
                importance=0.8,
                source="explicit",
            )
        ]
    )
    assert context.content_lines == ["User is interested in robotics."]


# ---- MemoryService with in-memory fakes (no database) ----


class _FakeSession:
    """Async session stand-in tracking commits."""

    def __init__(self) -> None:
        self.commits = 0

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


class _FakeMemoryRepository:
    """Repository stand-in with scripted behaviours."""

    def __init__(
        self,
        *,
        existing: Memory | None = None,
        active: list[Memory] | None = None,
    ) -> None:
        self.existing = existing
        self.active = active or []
        self.created: list[Memory] = []

    async def get_active_by_hash(self, owner_id: str, digest: str) -> Memory | None:
        return self.existing

    async def create(self, memory: Memory) -> Memory:
        self.created.append(memory)
        return memory

    async def list_active(
        self, owner_id: str, *, memory_type: str | None = None, limit: int = 100
    ) -> list[Memory]:
        return self.active

    async def mark_used(self, memory_ids: list) -> int:  # noqa: ANN001
        return len(memory_ids)

    async def get_by_id(self, memory_id: object) -> Memory | None:  # noqa: ANN001
        return None


async def test_service_create_memory_persists() -> None:
    session = _FakeSession()
    repo = _FakeMemoryRepository()
    service = MemoryService(session, repository=repo)

    memory = await service.create_memory(
        MemoryCreate(
            content="I am interested in robotics startups.",
            memory_type=MemoryType.INTEREST,
            importance=0.8,
        )
    )
    assert memory.owner_id == "default"
    assert len(repo.created) == 1
    assert repo.created[0].content == "I am interested in robotics startups."
    assert repo.created[0].memory_type == "interest"
    assert repo.created[0].importance == 0.8
    assert session.commits >= 1


async def test_service_create_deduplicates_active_memory() -> None:
    session = _FakeSession()
    existing = Memory(
        owner_id="default",
        content="I like AI",
        content_hash="hashtest",
        memory_type="context",
        source="explicit",
        importance=0.2,
    )
    repo = _FakeMemoryRepository(existing=existing)
    service = MemoryService(session, repository=repo)

    result = await service.create_memory(
        MemoryCreate(content="I like AI.", importance=0.9)
    )
    assert result is existing
    assert existing.importance == 0.9
    assert repo.created == []


async def test_service_disabled_blocks_creation() -> None:
    service = MemoryService(_FakeSession(), enabled=False)
    with pytest.raises(NotConfiguredError):
        await service.create_memory(MemoryCreate(content="x"))


async def test_service_retrieve_relevant_returns_context_items() -> None:
    repo = _FakeMemoryRepository(
        active=[
            Memory(
                owner_id="default",
                content="User is interested in robotics startups.",
                content_hash="robot",
                memory_type="interest",
                source="explicit",
                importance=0.8,
                use_count=0,
            ),
            Memory(
                owner_id="default",
                content="User prefers concise answers.",
                content_hash="concise",
                memory_type="preference",
                source="explicit",
                importance=0.9,
                use_count=0,
            ),
        ]
    )
    service = MemoryService(_FakeSession(), repository=repo)

    items = await service.retrieve_relevant("robotics startups", owner_id="default")
    assert items
    assert all(isinstance(item, MemoryContextItem) for item in items)
    assert items[0].content.startswith("User is interested")


async def test_service_retrieve_disabled_returns_empty() -> None:
    service = MemoryService(_FakeSession(), enabled=False)
    assert await service.retrieve_relevant("robotics startups") == []


async def test_service_mark_used_tracking_failure_is_silent() -> None:
    class _RaisingRepo(_FakeMemoryRepository):
        async def mark_used(self, memory_ids):  # noqa: ANN001
            raise RuntimeError("telemetry unavailable")

    service = MemoryService(_FakeSession(), repository=_RaisingRepo())
    # Usage tracking must never break research execution.
    await service.mark_used([str(uuid4())])


async def test_service_get_missing_memory_raises() -> None:
    service = MemoryService(_FakeSession(), repository=_FakeMemoryRepository())
    with pytest.raises(MemoryNotFoundError):
        await service.get_memory(uuid4())
