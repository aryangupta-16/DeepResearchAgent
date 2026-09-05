# Deploying to the cloud (Railway + S3-compatible blob storage)

Production-ready deployment guide. The stack: FastAPI **api**, a background
**worker**, a Next.js **frontend**, PostgreSQL (**pgvector**), and Redis.
`docker/docker-compose.yml` runs all of it locally; this guide deploys the same
containers to a PaaS where persistent disks aren't shared between services.

## The one thing to understand: where uploaded documents live

Uploaded files (PDFs) go through an object-store abstraction in the backend.
Two backends exist:

| Backend | When used | Durability |
|---|---|---|
| Local filesystem | `OBJECT_STORAGE_ENDPOINT` empty (local dev, single-host Docker) | ephemeral — wiped on every container redeploy |
| **S3-compatible** | `OBJECT_STORAGE_ENDPOINT` + `OBJECT_STORAGE_BUCKET` set | durable, survives redeploys, shared between api and worker |

Any S3-compatible provider works: **Supabase Storage, Vercel Blob, Cloudflare
R2, AWS S3, MinIO…**. For a brand-new deploy we recommend **Supabase** because
it can also host the PostgreSQL+pgvector database — one console for both, and
the free tier is generous.

---

## Step 0 — Push the code to GitHub

```bash
cd deep-research-agent
git init && git add .
git check-ignore backend/.env storage/   # both must print their path (secrets stay local)
git commit -m "Deep research agent"
# create a PRIVATE repo on github.com, then:
git remote add origin git@github.com:<you>/deep-research-agent.git
git push -u origin main
```

## Step 1 — Create the blob-storage bucket (documents)

### Option A — Supabase Storage (recommended)
1. Create a project at supabase.com.
2. **Storage → New bucket** → name it `documents` (public access: **off**).
3. **Storage → S3 access keys → Create** → copy the **endpoint**
   (`https://<project-ref>.supabase.co/storage/v1/s3`), **access key** and
   **secret key** (shown once).
4. Optional: also use Supabase as the database — **Database → Connection** →
   copy the **Session pooler** URL (`postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres`).
   pgvector is enabled by default on Supabase Postgres.

### Option B — Vercel Blob / Cloudflare R2 (or any S3)
1. Create a bucket (Vercel Blob store or R2 bucket).
2. From the provider dashboard copy: the **S3-compatible endpoint**
   (R2: `https://<account-id>.r2.cloudflarestorage.com`), **bucket name**,
   **access key id**, **secret access key**, and the **region** to use.

> The bucket must exist **before** the first upload — the app expects it and
> fails cleanly if it's missing (a one-time `create_bucket` in your console).

## Step 2 — Create the Railway project

1. Sign in at **railway.app** → **New Project**.
2. **Database services** (top-right "+"):
   - **PostgreSQL** — from the template marketplace choose the **`pgvector`**
     template (plain Postgres won't load embeddings).
     Railway automatically feeds `DATABASE_URL` to your services.
   - **Redis** — Railway automatically feeds `REDIS_URL`.

> If instead your database is **Supabase Postgres** (Step 1 Option A), skip the
> Railway Postgres and just set `DATABASE_URL` explicitly in Steps 3–4.

## Step 3 — API service

1. **New → Service → GitHub** → pick your repo.
2. **Variables** (Settings → Variables):

   | Variable | Value |
   |---|---|
   | `RAILWAY_DOCKERFILE_PATH` | `docker/Dockerfile.backend` |
   | `DATABASE_URL` | *(auto-provided by Railway Postgres, or your Supabase URL)* |
   | `REDIS_URL` | *(auto-provided by Railway Redis)* |
   | `ENVIRONMENT` | `production` |
   | `DEBUG` | `false` |
   | `CORS_ORIGINS` | `https://<your-frontend>.up.railway.app` *(set after Step 5, then redeploy)* |
   | `OPENAI_API_KEY` | *(your key)* |
   | `LLM_PROVIDER` | `openai` |
   | `LLM_MODEL` | `gpt-4o-mini` |
   | `SEARCH_PROVIDER` | `serper` (or `serpapi`) |
   | `SEARCH_API_KEY` | *(your key)* |
   | `EMBEDDING_PROVIDER` | `openai` |
   | `OBJECT_STORAGE_ENDPOINT` | your S3-compatible endpoint (Step 1) |
   | `OBJECT_STORAGE_BUCKET` | `documents` |
   | `OBJECT_STORAGE_ACCESS_KEY` | *(Step 1)* |
   | `OBJECT_STORAGE_SECRET_KEY` | *(Step 1)* |
   | `OBJECT_STORAGE_REGION` | `us-east-1` (R2: `auto`) |
   | `OBJECT_STORAGE_FORCE_PATH_STYLE` | `true` |

3. **Settings → Healthcheck path**: `/api/ready`
4. Deploy. Copy the public URL (`https://<your-api>.up.railway.app`). The first
   boot runs `alembic upgrade head` automatically (`RUN_MIGRATIONS_ON_STARTUP`
## Step 4 — Worker service

1. **New → Service → GitHub** → same repo.
2. **Variables**: same as Step 3 (api keys, search, object storage, `DATABASE_URL`,
   `REDIS_URL`), plus:

   | Variable | Value |
   |---|---|
   | `RAILWAY_DOCKERFILE_PATH` | `docker/Dockerfile.worker` |
   | `RUN_MIGRATIONS_ON_STARTUP` | `false` *(only the api runs migrations — avoids a boot-time race)* |

3. **Do NOT** give it a public domain — it runs in the background consuming the
   research/document queues. It just needs to stay up.

## Step 5 — Frontend service

1. **New → Service → GitHub** → same repo.
2. **Variables**:

   | Variable | Value |
   |---|---|
   | `RAILWAY_DOCKERFILE_PATH` | `docker/Dockerfile.frontend` |
   | `NEXT_PUBLIC_API_URL` | `https://<your-api>.up.railway.app/api` *(from Step 3)* |

   Railway injects this into the Docker build because the Dockerfile declares it
   as an `ARG` — the browser bundle is compiled against the real API URL.

3. **Settings → Healthcheck path**: `/`
4. Copy the frontend URL, set it as the API's `CORS_ORIGINS` (Step 3), and
   redeploy the API (Deployments → Redeploy).

## Step 6 — Verify it works end to end

```bash
curl -s https://<your-api>.up.railway.app/api/ready        # expect 200
```
1. Open the frontend URL — home page loads, both composers render.
2. **Upload a document** → watch the worker logs process it → confirm the file
   appears in the bucket (Supabase Storage UI / R2 dashboard). This is the S3
   path working: api wrote it, the worker read it.
3. Ask a **Quick answer** (chat streams). Run a **Research deeply** question.
4. Redeploy the api/worker once and confirm the uploaded document is still
   listable afterwards — the durability test that fails on local disk.

## Step 7 — Custom domain + HTTPS (optional but recommended)

Railway gives each service a TLS certificate automatically on
`*.up.railway.app`. For your own domain: open the frontend service →
**Settings → Custom domains** → add `app.yourdomain.com` → DNS **CNAME** →
`railway.app`. Then update the API's `CORS_ORIGINS` and rebuild the frontend
with the new `NEXT_PUBLIC_API_URL`.

---

## Production checklist (what the codebase already does)

- ✅ Migrations apply automatically at startup (idempotent)
- ✅ Queue durability: outbox + lease + reconciliation (no lost jobs across
  Redis blips or worker crashes)
- ✅ LLM circuit breaker + provider timeouts + per-job token budget + retries
- ✅ Upload guardrails (size caps, sanitized keys), storage keys can't escape
  their namespace
- ✅ Long-term memory + chat grounding behind runtime toggles
- ✅ Prometheus metrics on the worker (`:9091/metrics`)
- ✅ Secret hygiene: `.env`/`storage/` are gitignored; secrets live in the PaaS
  variable store

## Recommended before real users

1. **Auth** — `owner_id` columns already exist on jobs/memories/conversations;
   add a login and scope queries per user.
2. **Rate limiting** on `POST /api/research` and chat endpoints (Redis is
   already there).
3. **Job-notification** — email/webhook when a long research job completes.
4. **Monitoring** — Sentry (free tier) + the bundled Prometheus/Grafana on the
   worker port.
5. **Backups** — enable Railway/Supabase automatic Postgres backups; S3 buckets
   should have versioning on.
   defaults to true).