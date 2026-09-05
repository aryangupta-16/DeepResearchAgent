"""Pydantic-settings based application configuration."""

from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables / .env.

    Secrets are never hard-coded here; they come from the environment (or a local
    ``.env`` file) and default to empty strings.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "deep-research-agent"
    environment: str = "development"
    debug: bool = False

    # CORS (comma-separated origins allowed to call the API from a browser)
    cors_origins: str = "http://localhost:3000"

    # Databases / infrastructure
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/deep_research"
    redis_url: str = "redis://localhost:6379/0"

    # Optional separate infra for the test suite (keeps tests off the dev DB/Redis).
    # Defaults are derived from DATABASE_URL / REDIS_URL when left empty.
    test_database_url: str = ""
    test_redis_url: str = ""

    # Vector DB
    vector_db_url: str = ""

    # Object / blob storage
    # S3-compatible (Supabase Storage, Vercel Blob, Cloudflare R2, AWS S3…).
    # Empty endpoint + bucket keeps the local-filesystem backend (development
    # only); on PaaS hosts with ephemeral disks these must be set so uploaded
    # documents survive redeploys.
    object_storage_endpoint: str = ""
    object_storage_bucket: str = ""
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_region: str = "us-east-1"
    # Path-style addressing is required by Supabase Storage, Vercel Blob, and R2.
    object_storage_force_path_style: bool = True

    # LLM provider (optional for now)
    llm_provider: str = ""  # "openai" | "anthropic" | "google"
    llm_model: str = ""
    llm_timeout: float = 60.0
    openai_base_url: str = ""

    # LLM provider API keys (optional for now)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # Search tool
    search_provider: str = ""  # "serper" for V1
    search_api_key: str = ""
    search_endpoint: str = "https://google.serper.dev/search"

    # Fetch/browser safety limits
    fetch_timeout_seconds: float = 15.0
    fetch_max_bytes: int = 2_000_000
    fetch_max_redirects: int = 5

    # Research tool limits (per-task bounds to prevent runaway research)
    # Phase 9: raised from 2/3/4 — deeper reports need a bigger evidence
    # base; the synthesizer cannot elaborate beyond what it is given.
    max_search_queries_per_task: int = 3
    max_pages_per_task: int = 5
    max_evidence_per_task: int = 8
    # Ceiling for the synthesis LLM call (detailed reports need room; the
    # default model gpt-4o-mini supports up to 16384 output tokens).
    synthesis_max_tokens: int = 8000
    max_page_content_length: int = 200_000

    # Research queue / async worker (Phase 6)
    research_queue_name: str = "research:queue"
    document_queue_name: str = "documents:queue"
    research_worker_max_retries: int = 2
    research_worker_poll_timeout: float = 1.0
    research_job_lease_timeout: float = 90.0
    research_outbox_sweep_interval: float = 10.0

    # ===== Reliability & observability (Phase A) =====
    # Worker exposes its Prometheus metrics on this internal port so the
    # monitoring stack can scrape process-local counters (jobs, LLM tokens…).
    worker_metrics_port: int = 9091
    # Idempotency: key header length cap for POST /api/research replays.
    idempotency_key_max_length: int = 128

    # ===== Guardrails (Phase B2) =====
    # Input policy: research query length caps (reject with a clean 422).
    guardrails_min_query_length: int = 3
    guardrails_max_query_length: int = 2000
    # Hard per-job token budget (prompt + completion). 0 disables the ceiling.
    job_token_budget: int = 250_000

    # Startup behavior: apply Alembic migrations at startup (idempotent, keeps a
    # fresh deployment correct without manual `alembic upgrade head`).
    run_migrations_on_startup: bool = True

    # ===== Documents / RAG (Phase 8) =====
    # Local root for stored upload binaries (object-storage abstraction backend).
    document_storage_path: str = "./storage/documents"
    # Upload guardrails; oversized uploads are rejected before processing.
    max_document_size_mb: int = 25
    # Deterministic chunking (characters) with paragraph-aware packing.
    document_chunk_size: int = 1200
    document_chunk_overlap: int = 150
    # Embeddings. Empty provider disables document *processing* only — the API
    # still boots and web-only research is unaffected.
    embedding_provider: str = ""  # "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_timeout: float = 60.0
    document_embedding_batch_size: int = 64
    # Retrieval bounds for hybrid research.
    vector_top_k: int = 6

    # ===== Long-term user memory (Phase 9) =====
    # Memory is context/personalization only — never evidence or a citation.
    # When disabled, research still runs; memory retrieval/creation/extraction
    # are simply skipped (and creation/extraction refuse loudly).
    memory_enabled: bool = True
    # Max relevant memories injected into the workflow as planner context.
    memory_max_results: int = 5

    # ===== Chat sessions (Phase C1) =====
    # Bounded prompt history: only the last N persisted messages are replayed
    # into each chat turn, so prompts never grow unbounded.
    chat_history_window: int = 20
    # Max document excerpts offered to a documents-grounded chat turn (C2).
    chat_context_top_k: int = 4


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()


def _render(url: Any) -> str:
    """Render a SQLAlchemy URL without the password for logging, with it for use."""
    return url.render_as_string(hide_password=False)


def get_test_database_url(settings: Settings | None = None) -> str:
    """Resolve the database the test suite must run against.

    Uses ``TEST_DATABASE_URL`` when configured; otherwise derives a dedicated
    ``<name>_test`` database from ``DATABASE_URL`` so tests never touch the
    developer's active database.
    """
    from sqlalchemy.engine import make_url

    settings = settings or get_settings()
    if settings.test_database_url:
        return settings.test_database_url
    url = make_url(settings.database_url)
    name = url.database or "postgres"
    if not name.endswith("_test"):
        name = f"{name}_test"
    return _render(url.set(database=name))


def get_test_redis_url(settings: Settings | None = None) -> str:
    """Resolve the Redis URL the test suite must use.

    Uses ``TEST_REDIS_URL`` when configured; otherwise uses a dedicated database
    index (15) so tests never flush the developer's active Redis keys.
    """
    from sqlalchemy.engine import make_url

    settings = settings or get_settings()
    if settings.test_redis_url:
        return settings.test_redis_url
    return _render(make_url(settings.redis_url).set(database="15"))