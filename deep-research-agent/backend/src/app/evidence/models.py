"""ORM models for evidence.

The SQLAlchemy models live under ``app.infrastructure.database.models`` (shared
declarative base, discovered by Alembic). This module re-exports them so the
evidence domain has a single import surface.
"""

from __future__ import annotations

from app.infrastructure.database.models.evidence import ResearchEvidence
from app.infrastructure.database.models.research_source import ResearchSource

__all__ = ["ResearchSource", "ResearchEvidence"]