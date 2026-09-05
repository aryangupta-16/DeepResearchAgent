"""Observability: tracing (placeholder)."""

import logging

logger = logging.getLogger(__name__)


def setup_tracing(service_name: str, *, enabled: bool = False) -> None:
    """Initialize distributed tracing (e.g. OpenTelemetry) when providers are wired.

    No-op placeholder; call during app lifespan.
    """
    if not enabled:
        logger.info("Tracing disabled for service=%s", service_name)
        return

    raise NotImplementedError("Tracing provider integration not implemented yet.")