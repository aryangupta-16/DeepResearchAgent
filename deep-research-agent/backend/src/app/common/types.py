"""Shared low-level types (genuinely re-used across modules)."""

from typing import Any

type JSONValue = Any
"""A JSON-serializable value."""

type ProjectID = str
"""Identifier for a project/research run."""

type RunID = str
"""Identifier for a single research run/execution."""

type CorrelationID = str
"""Request/job correlation identifier used for tracing and logs."""