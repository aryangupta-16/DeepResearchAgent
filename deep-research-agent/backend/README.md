# Deep Research Agent — Backend

FastAPI backend for an agentic deep research platform. V1 implements a real deep
research workflow: planner → researchers (web search via **SerpApi**, page fetch) →
synthesizer → citation validation, with sources/evidence persisted in Postgres.

**Execution is asynchronous**: submissions return `202` immediately; a Redis-backed
worker process runs the research and updates status/stage/progress in Postgres.

## Prerequisites

- **Python 3.12** and [uv](https://docs.astral.sh/uv/)
- **Docker** (for PostgreSQL + Redis — optional if you already run them)
- API keys in `.env`: `OPENAI_API_KEY` (LLM) and `SEARCH_API_KEY` (SerpApi)

## 1. Get the code

```bash
git clone <your-repo-url> deep-research-agent
cd deep-research-agent/backend
```

## 2. Install dependencies

```bash
uv sync
```

## 3. Configure environment

```bash
cp .env.example .env
```

Then edit `.env` and set at minimum:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
SEARCH_PROVIDER=serpapi
SEARCH_API_KEY=<your-serpapi-key>
```

## 4. Start Postgres + Redis (Docker)

```bash
docker compose -f docker/docker-compose.yml up -d postgres redis   # from repo root
```

## 5. Run migrations

Migrations also apply automatically at API/worker startup (idempotent), so this
step is optional when using the defaults:

```bash
uv run alembic upgrade head
```

Useful companions: `uv run alembic current` (revision) and `uv run alembic check`
(models match migrations).

## 6. Start the API and the worker (two processes)

```bash
# terminal 1 — API
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# terminal 2 — research worker
uv run python -m app.infrastructure.queue.workers
```

Verify:

```bash
curl http://localhost:8000/api/health   # liveness: {"status":"ok"}
curl http://localhost:8000/api/ready    # readiness: 200 once Postgres+Redis reachable
```

Interactive docs: http://localhost:8000/docs

## 7. Run a deep research job

```bash
# submit (returns HTTP 202 immediately)
JOB_ID=$(curl -s -X POST http://localhost:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"query":"Current state of humanoid robotics in 2026","workflow_type":"deep_research"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

# the worker picks it up; poll status/stage/progress
curl http://localhost:8000/api/research/$JOB_ID
# {"status": "running", "stage": "researching", "progress": {...}, ...}

# when done: completed + full report on the same endpoint
curl http://localhost:8000/api/research/$JOB_ID/tasks
```

Re-running a pending job (`POST /api/research/{id}/run`) re-enqueues it (still
`202`); non-pending jobs are rejected with `409`.

## Tests & lint

```bash
uv run pytest            # 180+ tests; DB-backed integration tests skip without Postgres
uv run ruff check .
uv run alembic check     # ORM models match migrations
```

### Test database isolation

Tests never touch your development database. By default the suite derives a
dedicated `deep_research_test` database and Redis db 15 from `DATABASE_URL` /
`REDIS_URL` (creating the test database on demand). Override with
`TEST_DATABASE_URL` / `TEST_REDIS_URL`. Test teardown — schema drops and queue
flushes — only ever affects those isolated targets.

## Async execution notes

- **PostgreSQL is the source of truth** (jobs, tasks, sources, evidence, report).
- **Redis is transient transport** (`research:queue` list + per-job lease keys);
  it can be flushed without losing data.
- A small DB **outbox** (`research_job_outbox`) guarantees a submitted job is never
  lost if Redis is briefly down; the worker sweeps unpublished rows.
- Stale `running` jobs (worker crash) are reclaimed by the worker's periodic
  reconciliation after `RESEARCH_JOB_LEASE_TIMEOUT`: the job is atomically reset to
  `pending` and re-executed under the normal `pending → running` idempotency claim,
  so a recovered job can never run twice concurrently.
- Bounded retries: `RESEARCH_WORKER_MAX_RETRIES` whole-job attempts, then `failed`.

## Long-term user memory (Phase 9)

Durable, user-scoped memory (`preferences`, `interests`, `goals`, `context`,
`instructions`, `facts`) stored in PostgreSQL. Memory is **context, never
evidence**: it is injected into the planner as `USER CONTEXT`, and the report
can only cite real research sources / documents — never memory rows.

Memory is an enhancement, not a dependency. Research runs the same with
`MEMORY_ENABLED=false` (retrieval returns nothing; creation/extraction refuse
predictably with `HTTP 501`).

```bash
# Create an explicit memory (deterministic V1 mechanism)
curl -X POST http://localhost:8000/api/memory \
  -H 'Content-Type: application/json' \
  -d '{"content": "I am interested in humanoid robotics startups.", "memory_type": "interest"}'

curl http://localhost:8000/api/memory              # list mine (active first)
curl -X PATCH http://localhost:8000/api/memory/$ID -d '{"importance": 0.9}'
curl -X DELETE http://localhost:8000/api/memory/$ID
```

Relevant active memories are retrieved per research job (deterministic
term-overlap scoring + importance; top `MEMORY_MAX_RESULTS`) and passed to the
planner. Usage is tracked (`use_count` / `last_used_at`) best-effort — tracking
failures log and never fail a job. `POST /api/memory/extract` runs LLM
extraction and returns *candidates*; nothing is stored unless explicitly
created.

## .env reference (backend/.env)

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres DSN (default `postgresql+psycopg://postgres:postgres@localhost:5432/deep_research`) |
| `REDIS_URL` | Redis DSN (default `redis://localhost:6379/0`) |
| `CORS_ORIGINS` | Comma-separated browser origins allowed by CORS (default `http://localhost:3000`) |
| `RUN_MIGRATIONS_ON_STARTUP` | Apply Alembic migrations at API/worker startup (default `true`) |
| `TEST_DATABASE_URL` | Optional explicit test database (default derived `<db>_test`) |
| `TEST_REDIS_URL` | Optional explicit test Redis (default derived db `15`) |
| `LLM_PROVIDER` | `openai` |
| `LLM_MODEL` | Model override (empty = provider default) |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_BASE_URL` | Optional gateway/base URL (empty = official API) |
| `SEARCH_PROVIDER` | `serpapi` (or `serper`) |
| `SEARCH_API_KEY` | SerpApi key |
| `SEARCH_ENDPOINT` | `https://serpapi.com/search.json` |
| `RESEARCH_QUEUE_NAME` | Redis queue key (`research:queue`) |
| `RESEARCH_WORKER_MAX_RETRIES` | Whole-job retries (default 2) |
| `RESEARCH_JOB_LEASE_TIMEOUT` | Running-job lease seconds (default 90) |
| `RESEARCH_OUTBOX_SWEEP_INTERVAL` | Worker reconciliation cadence seconds (default 10) |