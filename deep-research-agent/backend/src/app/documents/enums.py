"""Document status enum and transition rules.

Mirrors :mod:`app.research.enums`: a single source of truth referenced by the ORM
models, API schemas, services, and the worker.
"""

from __future__ import annotations

from enum import StrEnum

from app.common.exceptions import ValidationError


class DocumentStatus(StrEnum):
    """Lifecycle of an uploaded document.

    pending → processing → ready
                    └──────► failed
    """

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


#: Allowed transitions per current status (empty set = terminal status).
DOCUMENT_STATUS_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.PENDING: frozenset(
        {DocumentStatus.PROCESSING, DocumentStatus.FAILED}
    ),
    DocumentStatus.PROCESSING: frozenset(
        {DocumentStatus.READY, DocumentStatus.FAILED}
    ),
    DocumentStatus.READY: frozenset(),
    DocumentStatus.FAILED: frozenset({DocumentStatus.PENDING}),  # explicit reprocess
}


class SourceType(StrEnum):
    """Provenance kind of a research source.

    ``web`` sources carry a URL; ``document`` sources reference an uploaded
    document (and, via evidence locators, a page number).
    """

    WEB = "web"
    DOCUMENT = "document"


def validate_document_status_transition(
    current: DocumentStatus,
    new: DocumentStatus,
) -> None:
    """Raise :class:`ValidationError` if the transition is not allowed."""
    allowed = DOCUMENT_STATUS_TRANSITIONS.get(current, frozenset())
    if new not in allowed:
        raise ValidationError(
            f"Cannot transition document from {current!r} to {new!r}."
        )