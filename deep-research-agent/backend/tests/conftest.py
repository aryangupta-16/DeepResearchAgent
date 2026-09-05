"""Shared pytest fixtures.

PostgreSQL-backed fixtures require a reachable database (e.g. the Docker Compose
service) and are skipped automatically when the database is unreachable.

Test isolation: the suite never touches the developer's active database. When the
integration/test suite runs, ``DATABASE_URL``/``REDIS_URL`` are pointed at dedicated
``*_test`` databases/indexes (see :func:`app.config.settings.Settings`), so normal
test teardown can never drop or flush the developer's data.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.common.exceptions import LLMProviderError
from app.config.settings import (
    get_settings,
    get_test_database_url,
    get_test_redis_url,
)
from app.infrastructure.database import models as _models  # noqa: F401  (register ORM models)
from app.infrastructure.database.postgres import Base, get_engine
from app.llm.base import LLMMessage, LLMResponse, LLMUsage

logger = logging.getLogger(__name__)


def _point_settings_at_test_infra() -> None:
    """Redirect the process to isolated test infrastructure (idempotent).

    Runs at import time so the application-under-test, the repository fixtures, and
    the Redis cleaner all talk to dedicated test-only databases/indexes.
    """
    settings = get_settings()
    test_db = get_test_database_url(settings)
    test_redis = get_test_redis_url(settings)
    if settings.database_url != test_db:
        os.environ["DATABASE_URL"] = test_db
    if settings.redis_url != test_redis:
        os.environ["REDIS_URL"] = test_redis
    # Tests build their schema with ORM create_all; they must not also trigger
    # Alembic migrations (which would collide with the freshly-created tables).
    os.environ["RUN_MIGRATIONS_ON_STARTUP"] = "false"
    get_settings.cache_clear()
    # Existing cached engines/factories built against the dev URL must be dropped so
    # the next caller dials the test database instead.
    from app.infrastructure.database.postgres import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _ensure_database_exists(url: str) -> None:
    """Create ``url``'s database if it does not exist (never touches other DBs)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    # Connect to the server's maintenance DB, then create the (test) database.
    maintenance = parsed.set(database="postgres")
    engine = create_engine(maintenance, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": parsed.database}
            ).scalar()
            if not exists:
                quoted = parsed.database.replace('"', '""')
                conn.execute(text(f'CREATE DATABASE "{quoted}"'))
    finally:
        engine.dispose()


def _ensure_vector_extension(url: str) -> None:
    """Enable pgvector in the test database (needed by DocumentChunk.embedding).

    Best effort: when the Postgres server lacks pgvector, DB-backed tests that
    need embeddings will fail loudly instead of hanging.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    engine = create_engine(make_url(url), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("Could not enable pgvector for tests: %s", exc)
    finally:
        engine.dispose()


# Redirect the whole test session to isolated test infrastructure. This must happen
# at import time — before any test module imports the application — so `app` and all
# fixtures bind to the dedicated test database/Redis.
_point_settings_at_test_infra()


class FakeLLMProvider:
    """Deterministic, in-process :class:`LLMProvider` for tests.

    Records the messages it receives and returns a canned response, or raises a
    provided exception — no network or API key involved.
    """

    name = "fake"

    def __init__(
        self,
        content: str = "fake reply",
        model: str = "fake-model",
        *,
        raise_error: Exception | None = None,
        usage: LLMUsage | None = None,
    ) -> None:
        self.content = content
        self.model = model
        self.raise_error = raise_error
        self.usage = usage or LLMUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7)
        self.calls: list[list[LLMMessage]] = []
        self.last_kwargs: dict[str, object] = {}

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> LLMResponse:
        self.calls.append(messages)
        self.last_kwargs = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "model": model,
            "timeout": timeout,
        }
        if self.raise_error is not None:
            raise self.raise_error
        return LLMResponse(
            content=self.content,
            model=model or self.model,
            provider=self.name,
            usage=self.usage,
        )


@pytest.fixture
def fake_llm_provider() -> FakeLLMProvider:
    """A fresh instance of :class:`FakeLLMProvider`."""
    return FakeLLMProvider()


@pytest.fixture
def failing_llm_provider() -> FakeLLMProvider:
    """A fake provider that raises an application-level LLM error."""
    return FakeLLMProvider(raise_error=LLMProviderError("boom"))


@pytest.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Provide a clean PostgreSQL schema; skip when the DB is unreachable.

    Always runs against the isolated test database (never the developer's active
    database): the test DB is created on demand and its schema is dropped/created
    per session.
    """
    settings = get_settings()
    _ensure_database_exists(settings.database_url)
    _ensure_vector_extension(settings.database_url)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)

    try:
        async with engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("PostgreSQL unavailable (%s); skipping DB-backed tests.", exc)
        await engine.dispose()
        pytest.skip("PostgreSQL is not available")
        return  # pragma: no cover - never reached when skip raises

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    await get_engine().dispose()


@pytest.fixture(scope="session")
async def db_session_factory(
    db_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the shared test engine."""
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A fresh session for repository-level tests."""
    async with db_session_factory() as session:
        yield session