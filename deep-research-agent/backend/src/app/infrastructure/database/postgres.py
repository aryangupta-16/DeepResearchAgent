"""PostgreSQL engine/session wiring.

Infrastructure owns vendor implementations. Everything here is lazy: creating an
engine does not open connections; sessions are opened and closed per request by
the FastAPI dependency.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config.settings import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models (used by Alembic autogenerate)."""


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine (lazily created, never at import)."""
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async session factory."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)