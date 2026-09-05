# Scripts

Operational/utility scripts. Backend scripts live in `backend/scripts/` and run
from that directory via `uv run python -m scripts.<name>`.

## `dlq_admin` (backend/scripts/dlq_admin.py)

Inspect, replay, or purge dead-lettered queue messages (Phase A). Requires
`REDIS_URL` (and `DATABASE_URL` for settings) in the environment.

```sh
cd backend
uv run python -m scripts.dlq_admin list     [--queue research:queue] [--limit 50]
uv run python -m scripts.dlq_admin requeue  [--queue research:queue]
uv run python -m scripts.dlq_admin purge    [--queue research:queue] [--yes]
```

- `list` — show DLQ envelopes (reason, failed-at, original payload).
- `requeue` — move everything back to the origin queue; still-unparseable
  messages are re-dead-lettered by the worker (self-healing loop).
- `purge` — delete permanently (asks for confirmation unless `--yes`).
