"""Health check endpoints.

- ``/health`` — liveness probe (process is up).
- ``/ready`` — readiness probe (required dependencies are reachable). Used by the
  Docker API healthcheck so the container only reports healthy once Postgres and
  Redis are actually available. Both keep the response small and fast.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.config.settings import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns OK when the API process is running."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict[str, Any]:
    """Readiness probe: verifies Postgres and Redis are reachable.

    200 + ``status: ready`` when all required dependencies answer; otherwise
    503 + ``status: degraded`` with per-check diagnostics. Never blocks longer
    than a short timeout, and never requires external providers.
    """
    from redis.asyncio import Redis
    from redis.exceptions import RedisError
    from sqlalchemy import text

    from app.infrastructure.database.postgres import get_engine

    settings = get_settings()
    checks: dict[str, str] = {}
    status = "ready"

    # PostgreSQL
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - environment dependent
        status = "degraded"
        checks["database"] = type(exc).__name__

    # Redis (timeout-bounded so a dead broker fails fast)
    redis_client = None
    try:
        redis_client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        await redis_client.ping()
        checks["redis"] = "ok"
    except (RedisError, OSError) as exc:  # pragma: no cover - environment dependent
        status = "degraded"
        checks["redis"] = type(exc).__name__
    finally:
        if redis_client is not None:
            await redis_client.aclose()

    response.status_code = 200 if status == "ready" else 503
    return {"status": status, "checks": checks, "app": settings.app_name}