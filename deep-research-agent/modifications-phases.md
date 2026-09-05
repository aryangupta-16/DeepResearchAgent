# Implementation Plan — Reliability, Observability, Guardrails, Evals & Chat

Three phases. The ordering is deliberate: __you can't verify reliability work without observability__, __you can't judge guardrails/quality changes without evals__, and __chat ships last so it lands on a system you can see into and measure__.

---

## PHASE A — Reliability & Observability *(foundation; everything else depends on it)* — ✅ COMPLETE

__Goal:__ The system survives provider failures gracefully, never loses jobs silently, never overspends silently, and every job's behavior/cost is visible.

__Status (all verified live in Docker):__ JSON logs with request/job ids via contextvars (A1); `/metrics` on the API + worker Prometheus port `:9091` + opt-in Prometheus/Grafana compose profile with provisioned dashboard (A2); `job_usage` ledger — 29 rows / 21,839 prompt + 5,097 completion tokens persisted for the first smoke job, recorded via the in-memory usage buffer flushed at worker commit points (A3); tenacity retries + in-house circuit breaker + Redis DLQ with `scripts/dlq_admin.py` list/requeue/purge (self-healing replay verified) + `Idempotency-Key` on `POST /api/research` (partial unique index, replay returns the original job — verified) (A4); GitHub Actions CI: ruff + pytest + vitest/tsc + compose smoke (A5). Migration `0007_job_usage_idempotency` applied.

__Remaining (deferred, non-blocking):__ tests for circuit-breaker/retry paths; `JOB_TRANSITIONS` wiring in the execution service; `DOCUMENT_PROCESSED`/`RAG_RETRIEVAL` instrumentation at the document/RAG boundaries; Prometheus/Grafana containers validated once pulled.

### A1. Structured logging — `structlog`

- JSON logs with `request_id` / `job_id` / `task_id` bound via contextvars, threaded from API → queue payload → worker → agents → LLM calls.
- __Why structlog:__ industry standard for async Python; contextvars-based binding fits your async architecture; near-zero risk to add.
- __Tradeoff vs stdlib logging:__ one more dependency + a config migration of existing loggers; payoff is queryable logs. Worth it — retrofitting later is worse.
- Fix the known leak: Alembic's `fileConfig` silencing app loggers (already patched — make the solution structural in `logging.conf`/structlog init).

### A2. Metrics — OpenTelemetry + Prometheus + Grafana (in compose)

- `app/observability/` package: meter setup, histogram/counter helpers. Key instruments: job duration & outcome by stage, LLM tokens in/out per call, search-call count, queue depth, task retries, in-flight jobs.
- Expose `/metrics` on the API; worker exposes the same on an internal port. Add __Prometheus + Grafana as optional compose profiles__ (`--profile monitoring`) so the dev default stays light.
- __Tradeoff — this is the real decision:__ full LGTM stack (Loki/Tempo/Grafana) vs Prometheus+Grafana only vs pure SaaS (Grafana Cloud). My call: __Prometheus + Grafana self-hosted now, OTel SDK used from day one__ so you can export traces to Tempo/Grafana Cloud later without code changes. Skipping Loki/Tempo today saves ~4 containers; OTel keeps the door open.
- Sentry (SaaS, free tier) as an optional add-on for error aggregation — recommend but don't block the phase on it.

### A3. Per-job cost accounting *(the decision-driving metric)*

- Capture `usage` from every OpenAI response (you already normalize the provider layer — extend `LLMResponse` with `prompt_tokens`/`completion_tokens`) and SerpApi call counts; persist to a `job_usage` table keyed by job.
- Small aggregate endpoint + Grafana panel. __Exit criterion: you can answer "what did the depth changes cost per report?"__

### A4. Reliability mechanics — `tenacity` + a small circuit breaker

- Retries with exponential backoff + jitter on LLM/search/fetch calls (bounded, per-stage budgets, not just per-request timeouts).
- Circuit breaker around OpenAI/SerpApi: after N consecutive failures, fail fast for a cooldown window so jobs degrade to "unavailable" quickly instead of hanging 60s × every call.
- __Tradeoff:__ `aiobreaker`/library vs ~80 lines in-house. In-house: zero deps, fits your `AppError` model, easy to test — recommended at this scale. Tenacity is unambiguous (industry default).
- __Dead-letter path:__ after max attempts, job → `failed` with structured reason; poisoned payloads land in a Redis DLQ list with an inspect/requeue admin script. Verify the worker currently fails closed; fix if it loops.
- __Idempotency keys:__ `Idempotency-Key` header on `POST /api/research`, enforced by a unique constraint + replay of the original response. Prevents duplicate paid research on retry/double-click.

### A5. Minimal CI (gate for everything below)

- GitHub Actions: ruff + pytest + vitest + tsc + frontend build on every PR; a compose smoke test (up → health → submit mocked job → assert report) on main.
- __Why here:__ every subsequent phase lands safer and cheaper.

__Exit criteria:__ kill Redis mid-job → recovery, no silent loss, DLQ populated as designed; circuit breaker demonstrably fail-fasts; per-job cost visible in Grafana; CI green gate live.

---

## PHASE B — Guardrails & Evaluation *(measure, then protect)* — ✅ COMPLETE

__Shipped (B1):__ `backend/evals/` — versioned JSONL golden set (11 cases incl.
an intentional-violation canary), deterministic citation-integrity + rubric
scoring (reuses the production validator), mocked tier runner
(`python -m evals.runner --tier mocked`), score artifacts in `eval-results/`,
CI golden-set gate (`tests/unit/test_eval_harness.py`) + artifact upload, and
`.github/workflows/evals-nightly.yml` for live-LLM runs. Judge-precision
(DeepEval-style LLM-as-judge) is trend-only by design; the gate uses the
deterministic validator. Canary semantics: regular cases must have zero
violations, `*-broken` canaries must be *detected* (eval-of-the-evals).

__Shipped (B2):__ `backend/src/app/guardrails/` — `input_policy`
(query normalization, length caps, injection heuristics, 422 with
non-leaking message; wired into `POST /api/research`), `content`
(`delimit_untrusted` labeled blocks + `flag_injection_patterns` +
`GUARDRAIL_INJECTION_FLAGS` metric; researcher page content and synthesizer
evidence blocks both wrapped; both system prompts hardened), `budget`
(`JobBudgetTracker` hard per-job token ceiling; fed by the LLM usage funnel;
enforced before each research task → graceful job failure; `forget()` in
worker cleanup; `GUARDRAIL_VIOLATIONS` metric).

__Verified live:__ injection query → HTTP 422; clean job → completed
normally; guardrail metric families present on both api:8000 and worker:9091.

__Deferred (trend work, not blockers):__ retrieval recall@k metric (needs
hand-labeled RAG docs), live-tier trending dashboards, promptfoo A/B setup.

__Goal:__ Untrusted web content can't hijack the agent; quality changes become measurable; spend is hard-capped.

__Order inside the phase is evals-first__ — you want the measuring stick built *before* changing prompts.

### B1. Eval harness — `DeepEval` + golden dataset

- `evals/` package (separate from `app/`): a versioned JSONL golden set (30–50 queries with expected evidence/citations), runner scripts, scores as JSON artifacts.
- Metrics: __citation precision__ (does the excerpt support the claim — LLM-as-judge, rubric), citation integrity (reuse the existing deterministic validator — count violations), report rubric (grounding/coverage/depth), __retrieval recall@k__ for the RAG side on hand-labeled sample docs.
- __Tradeoff — the framework decision:__ DeepEval (pytest-native, fits your existing suite, general metrics) vs promptfoo (YAML-driven, superb for A/B-ing prompts, less code) vs Ragas (RAG-specific, opinionated). My call: __DeepEval as the CI gate__ + __promptfoo optional for prompt experiments__; skip Ragas — its opinions will fight your evidence model. Build no custom framework.
- Two tiers: mocked-provider evals on every PR (deterministic, free) + nightly live-LLM eval run. Trend the scores; use judge scores for *relative* comparison only — they're too noisy for absolute thresholds.

### B2. Guardrails — `app/guardrails/` package, in-house and small

- __Prompt-injection hardening (the real threat):__ fetched web content is *data, never instructions* — delimited + labeled blocks in researcher/synthesizer prompts, explicit untrusted-source system instructions, instruction-pattern flagging on fetched text, and structured-output validation as the backstop (you have this; it's why injection mostly fails structurally today). Add regression tests: a page full of injection payloads must yield zero behavioral change.
- __Input policy on user queries:__ length/type caps, abuse filter, injection heuristics — returns a clean 422, logged.
- __Cost ceiling guardrail:__ hard per-job token/credit budget (configurable) enforced in the research loop; exceeded → job fails with a clear reason instead of silently overspending.
- __Tradeoff — the honest one:__ NeMo Guardrails / Guardrails AI vs in-house. Those frameworks bring a DSL/validator ecosystem you don't need yet and would wrap — not replace — your existing evidence-grounding architecture. My call: __a thin in-house `guardrails/` module with clean interfaces__ (each guard = a small class: input policy, content delimiter, cost ceiling), explicitly designed so a framework can be slotted in later if requirements grow (e.g., PII/multi-tenant moderation, where Llama Guard/Presidio become relevant). Building it in-house keeps it ~200 testable lines instead of a new dependency graph.

__Exit criteria:__ injection test suite (attack corpus) passes; eval scores reported in CI artifacts; a golden-set regression fails the build when citation precision drops; per-job budget demonstrably halts an runaway job.

---

## PHASE C — Chat Interface with Sessions *(user-facing value, shipped last)* — ✅ COMPLETE

### C1. Session model — `app/chat/` backend package — ✅ COMPLETE

__Shipped:__ `backend/src/app/chat/` — `conversations` + `chat_messages` tables
(migration `0008`; conversation UUID-keyed, message id an autoincrement int so
same-second turns order deterministically). Routes
`POST/GET /api/conversations`, `GET/DELETE /api/conversations/{id}`,
`POST /api/conversations/{id}/messages`; thin `ChatSessionService` reuses the
existing (previously orphaned) `ChatWorkflow`, persists every turn with
provider/model + token usage, auto-titles from the first user message, and
windows prompt history to the last N messages (`chat_history_window`, default
20) so prompts never grow unbounded. `ConversationNotFoundError` added to the
domain hierarchy. Sync request/response by design — chat never touches the
queue; deep research stays async.

__Verified live (Docker):__ conversation created → real LLM answer in <1s with
`53/37` prompt/completion tokens recorded on the assistant message → detail
shows the persisted `user/assistant` thread → conversation survived an API
container restart → delete → 204. **Zero deep-research jobs created in the
last 10 min of chat use** (the 15 jobs present predate the smoke). Cost
accounting shows chat usage on the message row, separate from `job_usage`
(criteria 1, 2, 4 of the phase exit list).

__Tests:__ `tests/unit/test_chat_sessions.py` (14 tests; in-memory SQLite —
windowed history semantics, auto-titling, cascade delete, usage persistence,
schema validation) and `tests/integration/test_conversations_api.py` (4 tests
against the isolated Postgres test DB — full lifecycle, durability across
requests, 422/404 handling, provider-error → 502). SQLite ordering is a real
data-model trap that the tests caught (see the autoincrement pk note above).
Full suite: **195 unit + 46 integration passed**, ruff clean, Phase B eval
gate still green. `aiosqlite` added as a dev dependency for the unit fixture.

- Original C1 plan notes below (kept for reference):
- New tables: `conversations` (id, title, created_at, __nullable `user_id` now__
  — so adding auth later doesn't require migrating a table of history) and
  `messages` (id, conversation_id, role, content, usage tokens, created_at).
  One Alembic migration.
- API: `POST/GET /api/conversations`, `GET/DELETE /api/conversations/{id}`, `POST /api/conversations/{id}/messages`.
- __Tradeoff — sync vs queued:__ chat runs as a __plain synchronous request/response__. Routing it through outbox/Redis/worker would be architecture tourism: chat latency is seconds, there's no long-running state, and the queue exists to protect multi-minute jobs. Deep research stays async; the two lifecycles never mix.
- Wire the existing (currently orphaned) `chat` workflow into this surface; bounded conversation history windowing (last N messages) so prompts don't grow unbounded.

### C2. Chat context — the differentiator — ✅ COMPLETE

__Shipped:__ per-conversation grounding via `conversations.context_mode`
(`none` | `documents`, migration `0009`; `chat_messages.citations` is a JSON
snapshot column — portable type so the SQLite unit fixture keeps working).
`app/chat/context.py` grounds turns in the __same RAG stack research uses__
(`DocumentRetrievalService`), wraps excerpts with the guardrail
`delimit_untrusted` block (RAG content is untrusted data), and pins the
citation contract in the prompt. `app/chat/citations.py` extracts `[C#]`
markers deterministically: first-seen order, deduped, __only keys that map to
offered sources survive__ — invented markers are dropped, never surfaced.
Retrieval failure degrades gracefully to a plain answer (never fails a turn).
`PATCH /api/conversations/{id}` toggles the mode; the dependency builds the
`DocumentContextProvider` only when embeddings are configured.

__Tests:__ `tests/unit/test_chat_context.py` (11 tests: marker extraction,
prompt contract, grounded/plain/degraded flows with a fake provider) +
2 integration tests (PATCH toggle; grounded turn returns citations mapped to
sources via a fake context provider).

__Verified live:__ migration `0009` applied on startup; a `documents`-mode
turn against a real uploaded PDF produced a grounded answer (1,227 prompt
tokens = context injected) and a follow-up asking for a specific fact
returned `[C1]` → extracted → persisted → mapped to
`Aryan_FullStack_React_Java.pdf`. Meta-questions ("what are the docs about")
correctly cite nothing — the citation contract is opt-in per claim.

### C3. Frontend — `app/chat/` route + composer mode — ✅ COMPLETE

__Shipped:__ `lib/types/chat.ts` + `lib/api/chat.ts` (mirror the backend
schemas exactly); `components/chat/ChatThread.tsx` (user/assistant bubbles;
`[C#]` markers parsed into clickable chips that expand to a source detail
panel with document name, page, excerpt, and a download link reusing the
existing document URL); `components/chat/ChatComposer.tsx` (textarea +
"Answer from uploaded documents" toggle, enabled only when a ready document
exists, errors surfaced inline); `/chat` (conversation index) and
`/chat/[id]` (thread page: refresh-on-send, 404 view, new-conversation);
home composer gains the __"Research deeply | Quick answer"__ mode toggle —
quick answers create a conversation, send synchronously, and route to the
thread with zero deep-research jobs; `AppShell` sidebar gains the Chat nav
entry + a light-poll "Conversations" list. Non-streaming by design (per
plan); SSE is deferred C3 polish.

__Tests:__ `__tests__/api/chat.test.ts` (8), `ChatThread.test.tsx` (7,
including the marker→chip splitting and unknown-marker disable), `ChatPage`
(5: render, send+refresh, toggle, 404, new conversation), `HomePage` (4:
mode switch, quick flow creates+sends+navigates without research jobs,
error path). Suite: __10 files / 59 tests__, tsc clean, ESLint clean.

__Verified live:__ `/chat` serves (a stale Docker cache layer initially
served 404 — fixed with `--no-cache` rebuild); grounded answers with working
citation chips rendered from the persisted snapshots.

__Phase exit criteria:__ conversation survives restarts ✅ (C1); quick
answers in seconds with zero deep-research jobs ✅ (C1 + quick flow verified);
document-context answers carry working citations ✅ (C2 live); cost
accounting shows chat usage separately ✅ (per-message tokens vs `job_usage`).

### C4. Production polish — UI cleanup, SSE streaming, report export — ✅ COMPLETE

__UI cleanup:__ removed the `Job {id} · Workflow {type}` line from the report
header, the `Quick answers · no deep-research pipeline` caption from the chat
header (title only now), and the sidebar `Async, citation-grounded research.`
+ `API docs ↗` footer (replaced with a single quiet line). Chat layout rework:
centered 800px column, full-height scrollable thread pane, "You"/"Assistant"
labels + timestamps under every bubble, right-aligned user rows, improved
empty state, and auto-scroll to the newest message (including during
streaming).

__SSE streaming:__ chat replies now stream token-by-token.
`LLMProvider` gained an optional streaming capability
(`supports_streaming`/`generate_stream` with a non-streaming one-shot fallback
in the base class, so every provider works); `OpenAIProvider` implements it
via `stream=True` + `stream_options: include_usage` with the same circuit
breaker/metrics (no mid-stream retries — partial streams can't be replayed).
`POST /api/conversations/{id}/messages/stream` emits `start` (user message
id, committed before streaming) → `delta` frames → `done` (full persisted
message incl. citations; citations are extracted from the *complete* text
after the stream, so grounding works identically) or `error` (AppError
mapped, user turn retained, no half-written assistant row). The old sync
endpoint remains for API consumers. Frontend: `streamMessage` fetch-reader
with an SSE frame parser + `AbortController` cancellation, optimistic user
bubble, live "Assistant · typing" bubble, and canonical refresh on `done`.

__Report export:__ `GET /api/research/{id}/report.md` downloads the completed
report as detailed Markdown — title, generated date, query, summary, every
section with `Sources: [n]` citation chips, conclusion, and the full source
list with each evidence item (claim, excerpt, locator) and resolved document
names. `python -m` free: stdlib only (PDF/DOCX intentionally deferred —
revisit `reportlab`/`python-docx` if asked). Report page gains a
"Download report (.md)" button.

__Tests:__ +6 unit (`test_research_export.py`: builder detail, citation
numbering, garbage-report handling; `test_chat_stream.py`: event sequence,
fallback, mid-stream error, grounded streaming) +3 integration (SSE frame
format via `client.stream`; export happy path on a completed job; export
409 on pending jobs) + frontend (SSE frame parser across chunk boundaries,
streaming lifecycle, delete confirm/dismiss). Totals: __217 backend unit,
51 backend integration, 64 frontend tests__ — all green, ruff/tsc/ESLint
clean, eval gate unchanged.

__Verified live:__ SSE stream emits real token deltas (`event: delta
data: {"text": "RAG"}` …); export of the completed lithium-mining job
returned a 143-line Markdown file with correct attachment headers and
per-source evidence; chat + report pages serve cleanly.

---

## Why this shape and not another

- __3 phases, not 6:__ observability+reliability are one unit (verify fixes with metrics); guardrails+evals are one unit (guardrails are verified *by* evals); chat is cleanly separable user value.
- __Every phase has an independently demoable exit__ — you can stop after any phase and be strictly better.
- __Every library choice has a stated reversal path__ (OTel → any backend; in-house guards → NeMo/Guardrails AI; DeepEval → promptfoo; non-streaming → SSE) so no decision is a dead end.
- __Nothing requires touching the research architecture__ — all new code lives in new modules (`observability/`, `guardrails/`, `evals/`, `chat/`) with thin integration points, per your modularity requirement.
---

## Phase C5 — Production deployment (complete ✅)

Follow [`DEPLOYING.md`](DEPLOYING.md) to run the same containers on Railway
with durable, cloud-native document storage.

__S3-compatible object storage:__ the existing `ObjectStore` protocol gains a
real second backend (`app/infrastructure/storage/s3.py`, `aiobotocore`) that
works with Supabase Storage, Vercel Blob, Cloudflare R2, AWS S3, MinIO…
Logical buckets (`documents`) are namespaced as key prefixes inside the one
configured provider bucket, so the domain/service contract is unchanged.
Activated by setting `OBJECT_STORAGE_ENDPOINT` + `OBJECT_STORAGE_BUCKET` (+
access/secret key); unset keeps the local-filesystem backend so local dev and
the Docker stack are untouched. Missing credentials while an endpoint is set
fail fast at startup (`NotConfiguredError`) instead of surfacing mid-flight.

__Why now:__ local-filesystem storage is fine on a single host, but a PaaS
redeploys containers onto fresh disks — uploaded PDFs would silently vanish
every deploy. S3-compatible storage is the durable, shared (api + worker)
answer, and it was always the abstraction's design intent.

__Settings added:__ `object_storage_access_key`, `object_storage_secret_key`,
`object_storage_region` (default `us-east-1`), `object_storage_force_path_style`
(default true — required by Supabase/R2/Vercel Blob). Documented in
`backend/.env.example`.

__Tests:__ +8 unit (`test_object_storage_s3.py`): put/get/exists/delete
round-trip through an injected fake S3 client, logical-bucket→key namespacing,
missing-object→`NotFoundError`, invalid-key rejection (parity with the local
backend's traversal rules), non-missing client errors propagating, and factory
selection (local fallback / S3 / fail-fast without credentials). Plus a live
MinIO end-to-end check (real S3 server): full protocol round-trip + 404 mapping
all passed. Totals: __225 backend unit, 51 backend integration, 64 frontend
tests__ — all green, ruff/tsc/ESLint clean.

__Deploy guide:__ step-by-step PaaS walkthrough (push to GitHub → Supabase/R2
bucket → Railway Postgres-pgvector + Redis + api/worker/frontend services with
exact variable tables → verification incl. the redeploy-durability test →
custom domain/HTTPS), plus a production checklist and the recommended items
still outstanding (auth, rate limiting, completion notifications, Sentry,
backups).
