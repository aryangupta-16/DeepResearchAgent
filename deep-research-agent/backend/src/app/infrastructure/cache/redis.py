"""Redis cache wiring (placeholder)."""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def build_redis_client() -> Redis:
    """Create a Redis client from settings (connection opens on first use).

    Timeouts are explicit so an unreachable/half-open broker fails fast instead of
    blocking a worker or request thread indefinitely — Redis is transient transport,
    and the PostgreSQL outbox guarantees no job is lost while it is down.
    """
    return Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=5.0,
        socket_timeout=15.0,
        health_check_interval=30,
    )