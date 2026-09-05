#!/bin/sh
# Start both the API server and the background worker in the same container.
# Used by Railway to run both processes in a single service.
set -e

# Start the worker in the background
uv run python -m app.infrastructure.queue.workers &

# Start the API server in the foreground (Railway needs this for healthchecks)
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000