"""Application metrics via :mod:`prometheus_client`.

A small, deliberately curated instrument set — the numbers that actually
drive decisions (job outcomes/duration, LLM token spend, search usage, queue
health). Counters/histograms are module-level singletons so any module can
import and record; exposition happens at ``GET /metrics`` (API) and on the
worker's internal metrics port.

Label cardinality is kept low on purpose: user-controlled values (query text,
URLs) are never labels.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# ---- HTTP (API) -----------------------------------------------------------

HTTP_REQUESTS = Counter(
    "app_http_requests_total",
    "HTTP requests handled by the API.",
    ["method", "endpoint", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# ---- Research jobs ---------------------------------------------------------

JOB_TRANSITIONS = Counter(
    "app_job_transitions_total",
    "Research job status transitions.",
    ["from_status", "to_status"],
)
JOB_STAGE_DURATION = Histogram(
    "app_job_stage_duration_seconds",
    "Time spent per workflow stage.",
    ["stage"],
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
)
JOB_TOTAL_DURATION = Histogram(
    "app_job_duration_seconds",
    "End-to-end research job duration.",
    ["outcome"],
    buckets=(5, 15, 30, 60, 120, 300, 600, 1200),
)
JOBS_IN_FLIGHT = Gauge(
    "app_jobs_in_flight",
    "Research jobs currently claimed/running.",
)
JOB_FAILURES = Counter(
    "app_job_failures_total",
    "Jobs that ended in failure, by reason category.",
    ["reason"],
)

# ---- LLM / providers --------------------------------------------------------

LLM_CALLS = Counter(
    "app_llm_calls_total",
    "LLM provider calls.",
    ["agent", "outcome"],  # outcome: ok | error
)
LLM_TOKENS = Counter(
    "app_llm_tokens_total",
    "LLM tokens consumed (cost accounting).",
    ["agent", "kind"],  # kind: prompt | completion
)
LLM_CALL_DURATION = Histogram(
    "app_llm_call_duration_seconds",
    "LLM call latency.",
    ["agent"],
    buckets=(0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
PROVIDER_CIRCUIT_STATE = Gauge(
    "app_provider_circuit_open",
    "1 when a provider circuit breaker is open (fail-fast active).",
    ["provider"],
)

# ---- Search / fetch ----------------------------------------------------------

SEARCH_CALLS = Counter(
    "app_search_calls_total",
    "SerpApi search calls.",
    ["outcome"],  # outcome: ok | error
)
FETCH_CALLS = Counter(
    "app_fetch_calls_total",
    "Web page fetches.",
    ["outcome"],
)

# ---- Queue / worker -----------------------------------------------------------

QUEUE_DEPTH = Gauge(
    "app_queue_depth",
    "Messages waiting in a queue.",
    ["queue"],
)
TASK_RETRIES = Counter(
    "app_task_retries_total",
    "Task message retries (redeliveries).",
)
DEAD_LETTER_MESSAGES = Counter(
    "app_dead_letter_total",
    "Messages moved to the dead-letter queue.",
    ["queue"],
)
DOCUMENT_PROCESSED = Counter(
    "app_documents_processed_total",
    "Document processing outcomes.",
    ["outcome"],  # outcome: ready | failed
)

# ---- Document/RAG (Phase 8) ------------------------------------------------------

RAG_RETRIEVAL = Histogram(
    "app_rag_retrieval_chunks",
    "Chunks returned per retrieval call.",
    buckets=(0, 1, 2, 3, 5, 8, 12, 20),
)

# ---- Guardrails (Phase B2) ---------------------------------------------------

GUARDRAIL_VIOLATIONS = Counter(
    "app_guardrail_violations_total",
    "Requests/jobs blocked by a guardrail.",
    ["guard"],  # guard: input_policy | budget
)
GUARDRAIL_INJECTION_FLAGS = Counter(
    "app_guardrail_injection_flags_total",
    "Untrusted content blocks flagged for instruction-pattern hits.",
    ["pattern"],
)


def render_metrics() -> tuple[bytes, str]:
    """Render the Prometheus exposition payload (for ``GET /metrics``)."""
    return generate_latest(), CONTENT_TYPE_LATEST


def observe_stage(stage: str, duration_seconds: float) -> None:
    """Record one workflow stage's duration."""
    JOB_STAGE_DURATION.labels(stage=stage).observe(duration_seconds)
