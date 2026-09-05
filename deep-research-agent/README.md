# Deep Research Agent

A modular, production-oriented platform for **citation-grounded deep research**.

Submit a research question; an asynchronous worker plans sub-questions, searches
the live web (**SerpApi**), fetches pages, extracts verifiable evidence, and
synthesizes a structured report where every claim carries a machine-readable
citation that resolves to a stored source in PostgreSQL.

```
Frontend ──► FastAPI ──► PostgreSQL (jobs/tasks/sources/evidence/report)
                │              ▲                ▲
                │              │ outbox/reclaim │
                ▼              │                │
              Redis (queue/lease) ──► Worker ──┘
                                       │
                     DeepResearchWorkflow (planner → researchers →
                     synthesizer → citation validation)
                                       │
                          OpenAI + SerpApi + page fetching
```

**Execution is asynchronous:** submissions return `202` immediately; a Redis-backed
worker performs the research. PostgreSQL is the source of truth; Redis is transient
transport (safe to flush); outbox + lease + reconciliation guarantee no job is lost
across Redis blips or worker crashes.

## Run it locally — step by step

> Going to production? Follow the full PaaS walkthrough in
> [`DEPLOYING.md`](DEPLOYING.md) (Railway + Supabase/R2 blob storage so uploaded
> documents survive redeploys).

**Option A — everything in Docker (recommended):**

1. Clone and enter the project:
   ```bash
   git clone <your-repo-url> deep-research-agent
   cd deep-research-agent
   ```
2. Create your env file and add your API keys:
   ```bash
   cp backend/.env.example backend/.env
   # edit backend/.env → set OPENAI_API_KEY and SEARCH_API_KEY (SerpApi)
   ```
3. Start all services (Postgres, Redis, API, worker, frontend):
   ```bash
   docker compose -f docker/docker-compose.yml up --build -d
   ```
4. Wait for readiness, then open the app:
   - Frontend → **http://localhost:3000**
   - API docs → **http://localhost:8000/docs** (check `GET /api/ready` → 200)
5. Submit a question on the home page and watch progress → report → citations.

Stop with `docker compose -f docker/docker-compose.yml down` (data persists; add `-v` only to wipe the database).

**Option B — infra in Docker, app processes on host:**

1. Same steps 1–2 as above.
2. Start only infrastructure: `docker compose -f docker/docker-compose.yml up -d postgres redis`
3. Backend API (terminal 1): `cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8000`
4. Worker (terminal 2): `cd backend && uv run python -m app.infrastructure.queue.workers`
5. Frontend (terminal 3): `cd frontend && npm install && cp .env.example .env.local && npm run dev`

## Components

- `backend/` — FastAPI API + background worker (one codebase, two processes). See [`backend/README.md`](backend/README.md).
- `frontend/` — Next.js + React + TypeScript web UI. See [`frontend/README.md`](frontend/README.md).
- `docker/` — Dockerfiles + `docker-compose.yml` for Postgres/Redis/API/Worker/Frontend.

## Service URLs (after startup)

Migrations apply automatically at startup — no manual database setup.

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| API | http://localhost:8000 |
| Swagger docs | http://localhost:8000/docs |
| Liveness | `GET /api/health` → `{"status":"ok"}` |
| Readiness | `GET /api/ready` → 200 when Postgres + Redis reachable |

Then open http://localhost:3000, ask a question (e.g. *"Research the current state
of humanoid robotics in 2026"*), watch progress advance, and click citation chips
to inspect evidence.

## Services & ports

| Service | Port | Notes |
| --- | --- | --- |
| frontend | `3000` | Next.js server |
| api | `8000` | FastAPI (`/docs` = OpenAPI UI) |
| postgres | `5432` | Named volume `postgres_data` persists all data |
| redis | `6379` | Transient queue/lease transport only |

If a port is occupied, startup fails clearly — this project never kills unrelated
processes. Stop whatever holds the port first (`lsof -nP -iTCP:<port> -sTCP:LISTEN`).

## Environment variables

Backend (`backend/.env`) — full list in [`backend/.env.example`](backend/.env.example):

| Variable | Required | Example | Secret? |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | `postgresql+psycopg://postgres:postgres@localhost:5432/deep_research` | contains password |
| `REDIS_URL` | yes | `redis://localhost:6379/0` | no |
| `CORS_ORIGINS` | no | `http://localhost:3000` | no |
| `LLM_PROVIDER` | yes* | `openai` | no |
| `LLM_MODEL` | no | empty = provider default (`gpt-4o-mini`) | no |
| `OPENAI_API_KEY` | yes* | `sk-…` | **yes** |
| `OPENAI_BASE_URL` | no | empty = official API | no |
| `SEARCH_PROVIDER` / `SEARCH_API_KEY` / `SEARCH_ENDPOINT` | yes* | `serpapi` / `<key>` / `https://serpapi.com/search.json` | key is **secret** |
| `RUN_MIGRATIONS_ON_STARTUP` | no | `true` | no |
| `TEST_DATABASE_URL` / `TEST_REDIS_URL` | no | derived automatically for tests | may contain password |

\* required *for research features*, not for boot: the API starts and reports
health without provider keys; errors surface only when that feature is invoked.

Frontend (`frontend/.env.local`) — see [`frontend/.env.example`](frontend/.env.example):

| Variable | Example | Secret? |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api` | no (browser-visible by design) |

Secrets are never committed: `.env` files are gitignored, `.env.example` ships
placeholders only, and no backend secret is exposed via any `NEXT_PUBLIC_*` variable.

## Migrations & data safety

Migrations apply automatically at API/worker startup (idempotent no-op at head).
Manual control:

```bash
cd backend
uv run alembic upgrade head     # apply pending
uv run alembic current          # show revision
uv run alembic check            # models match migrations?
```

- `docker compose restart` / `stop` / `start` **never** delete data.
- Only `docker compose down -v` deletes the PostgreSQL volume (explicit action).
- Startup never runs `DROP DATABASE`, `DROP TABLE`, or downgrades.

## Tests

```bash
cd backend  && uv run pytest && uv run ruff check . && uv run alembic check
cd frontend && npm test && npm run build && npm run lint
```

Tests are isolated from development data by default: the suite uses a dedicated
`deep_research_test` database and Redis db 15 (override with `TEST_DATABASE_URL`
/ `TEST_REDIS_URL`). Test teardown can never drop your dev tables or flush your
dev queue.

## Troubleshooting

| Symptom | Diagnosis |
| --- | --- |
| Port already in use | `lsof -nP -iTCP:<port> -sTCP:LISTEN`; stop the conflicting process yourself. |
| API restart-looping / unhealthy | `docker logs <api-container>`; verify `DATABASE_URL` / `REDIS_URL` and migration errors. |
| `/api/ready` → 503 | The `checks` object names the failing dependency (`database` / `redis`). |
| CORS error in browser | `CORS_ORIGINS` must include the frontend origin (default `http://localhost:3000`); confirm `NEXT_PUBLIC_API_URL` points at the reachable API. Also check for a stale process bound to port 8000 serving old code. |
| Worker not consuming | `docker logs <worker-container>`; expect `Running reconciliation sweep.` Jobs stuck `running` are auto-reclaimed ~90s after a crash (`RESEARCH_JOB_LEASE_TIMEOUT`). |
| Missing API key | Research features error clearly on use; the API still boots and serves health endpoints. Set keys in `backend/.env`, restart. |
| Migration failure | Startup retries ~30s then fails loudly. Check Postgres connectivity and `alembic current`. |

## Scope

This setup provides **reproducible local development / single-host deployment**
via Docker Compose — not a production topology. Managed databases, TLS, replicas,
and observability stack are deliberately out of scope for now.