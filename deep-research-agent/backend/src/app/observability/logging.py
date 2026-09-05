"""Structured logging via :mod:`structlog`.

Production output is one-JSON-object-per-line on stdout (queryable by any
log aggregator); ``DEBUG=true`` switches to a human-readable console format
for local development. Correlation ids (``request_id`` / ``job_id`` /
``task_id``) come from :mod:`app.observability.context` contextvars and are
merged into every event automatically — no per-call passing.

Standard-library ``logging`` (uvicorn, sqlalchemy, etc.) is routed *through*
structlog's processor pipeline too, so third-party log records get the same
JSON treatment and correlation ids.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.observability.context import current_context


def _merge_context(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor: merge correlation contextvars into the event."""
    event_dict.update(current_context())
    return event_dict


def setup_logging(debug: bool = False, *, service: str = "deep-research-agent") -> None:
    """Configure structlog + stdlib logging for the whole process.

    Safe to call more than once (reconfiguration replaces handlers/processors).
    """
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        _merge_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: structlog.typing.Processor
    if debug:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            # Route via stdlib so uvicorn/sqlalchemy records share the pipeline.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Silence noisy third-party loggers (access logs duplicate request middleware).
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to ``name``."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
