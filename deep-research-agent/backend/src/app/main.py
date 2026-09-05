"""Composable FastAPI application for the deep research backend."""

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.router import api_router
from app.common.exceptions import AppError
from app.config.constants import APP_NAME, APP_VERSION
from app.config.settings import get_settings
from app.observability.context import bind_request_context
from app.observability.logging import get_logger, setup_logging
from app.observability.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS, render_metrics

logger = get_logger("app.main")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    setup_logging(debug=settings.debug)

    application = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        debug=settings.debug,
        lifespan=lifespan,
    )

    # Browser origins are environment-configured (never "*" in production).
    origins = [
        origin.strip()
        for origin in settings.cors_origins.split(",")
        if origin.strip()
    ]
    if origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type"],
        )

    application.add_exception_handler(AppError, _app_error_handler)

    @application.middleware("http")
    async def _observability_middleware(request: Request, call_next: object) -> Response:
        """Bind correlation ids, record request metrics, and emit one access log per request."""
        bind_request_context(request.headers.get("X-Request-ID"))
        method = request.method
        # Use the matched route's path template (e.g. ``/api/research/{job_id}``) so
        # metric label cardinality stays bounded by the endpoint set, not user-supplied ids.
        path = request.scope.get("route")
        endpoint_label = getattr(path, "path", None) or request.url.path
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handler stack still runs after BaseHTTPMiddleware
            # (ServerErrorMiddleware runs last); record a 500 so the outage is visible
            # in metrics even when the response never reaches us.
            duration = time.perf_counter() - start
            HTTP_REQUESTS.labels(method=method, endpoint=endpoint_label, status="500").inc()
            HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint_label).observe(duration)
            raise
        duration = time.perf_counter() - start
        HTTP_REQUESTS.labels(
            method=method, endpoint=endpoint_label, status=str(response.status_code)
        ).inc()
        HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint_label).observe(duration)
        logger.info(
            "http_request method=%s path=%s status=%d duration_ms=%.1f",
            method,
            request.url.path,
            response.status_code,
            duration * 1000,
        )
        return response

    @application.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        """Expose Prometheus metrics (scraped by the monitoring stack)."""
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    application.include_router(api_router, prefix="/api")

    return application


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Map application exceptions to clean, consistent HTTP responses.

    Raw database/vendor exceptions never reach API consumers: service code raises
    :class:`AppError` subclasses and this handler renders them.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


async def lifespan(app: FastAPI) -> None:  # noqa: ANN401 - FastAPI signature
    """Run application startup/shutdown hooks.

    Applies Alembic migrations first (idempotent — a no-op when the schema is
    already at head) so the API never serves requests against an unschematized
    database. Skipped when ``RUN_MIGRATIONS_ON_STARTUP=false`` (e.g. tests that
    build their own schema).
    """
    settings = get_settings()
    if settings.run_migrations_on_startup:
        from app.infrastructure.database.migrations import run_migrations_async

        await run_migrations_async()
    yield


app = create_app()
