"""Idempotent programmatic Alembic migration runner.

Both the API process startup and the worker startup call :func:`run_migrations`
so a fresh deployment (or a freshly started component) always has the schema at
``head`` before it begins serving. ``alembic upgrade head`` is idempotent: on an
empty database it applies every migration, and on an up-to-date database it is a
no-op — so duplicate invocation across processes is safe and cheap.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

#: backend/ (repository root of the Python package)
_BACKEND_DIR = Path(__file__).resolve().parents[4]
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"
_SCRIPT_LOCATION = _BACKEND_DIR / "migrations"


def run_migrations(*, wait_for_database_seconds: float = 30.0) -> None:
    """Apply all pending migrations (no-op when already at head).

    If the database is not yet reachable, retry for up to ``wait_for_database_seconds``
    before raising — this smooths startup races when Postgres is still coming up.
    Raises the underlying connection error once the window elapses so startup fails
    loudly (never silently serves an unschematized database).
    """
    deadline = time.monotonic() + wait_for_database_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            cfg = Config(str(_ALEMBIC_INI))
            cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
            # Keep the host process's logging configuration intact (env.py honors this).
            os.environ["ALEMBIC_SKIP_LOG_CONFIG"] = "1"
            command.upgrade(cfg, "head")
            logger.info("Migrations are at head.")
            return
        except Exception as exc:  # noqa: BLE001 - retry transient DB startup
            last_error = exc
            logger.warning("Migration attempt failed (%s); retrying…", type(exc).__name__)
            time.sleep(0.5)

    if last_error is not None:
        # Bind a fresh config so env.py can attempt an offline-style URL render for
        # a clearer message without rethrowing only from the retried run.
        msg = (
            f"Database migrations did not complete after {wait_for_database_seconds:.0f}s: "
            f"{getattr(last_error, 'message', None) or last_error}. "
            "Check DATABASE_URL connectivity and that PostgreSQL is reachable."
        )
        raise RuntimeError(msg) from last_error


async def run_migrations_async(*, wait_for_database_seconds: float = 30.0) -> None:
    """Async wrapper around :func:`run_migrations` (runs in a thread executor).

    ``run_migrations`` is keyword-only, so bind the argument explicitly instead of
    passing it positionally through ``run_in_executor``.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: run_migrations(wait_for_database_seconds=wait_for_database_seconds),
    )