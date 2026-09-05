# Deep Research Agent — Frontend

Next.js (App Router) + React + TypeScript frontend for the Deep Research Agent.

Users submit a research question, watch real-time async progress
(status / stage / task list), and then read a structured report with clickable
citation chips that open an evidence drawer (per-source, per-evidence claims).

## Prerequisites

- **Node.js 20+** (uses `import.meta.url`, Next.js 14, React 18)
- The **backend API** running (see `backend/README.md`)

## 1. Install

```bash
cd frontend
npm install
```

## 2. Configure

```bash
cp .env.example .env.local
```

`NEXT_PUBLIC_API_URL` must point at the backend `/api` base — e.g.
`http://localhost:8000/api`.

## 3. Run

```bash
npm run dev          # http://localhost:3000
```

Using the production build:

```bash
npm run build
npm run start
```

## Tests

```bash
npm run test         # Vitest + jsdom (34 tests)
```

The `@` import alias in `vitest.config.ts` is resolved relative to the config
file, so the suite is portable across machines.

## App pages

- `/` — submit a research question; redirects to the job detail page.
- `/research/[id]` — live progress, then the completed report + sources.

## 4. Try it end to end

With Postgres, Redis, the API, and the worker all running (see
`backend/README.md`), open http://localhost:3000, enter a question such as
"Compare hydrogen vs electric trucks for long-haul freight", and submit. Watch
the stage/progress advance and, when the report completes, click a citation
chip to open the evidence drawer.