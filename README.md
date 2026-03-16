# Latexy
<img width="1382" height="744" alt="image" src="https://github.com/user-attachments/assets/21b1f42d-158d-4174-97b2-59d22d8285c9" />



AI-powered LaTeX resume builder. Paste your `.tex` source, describe the role, and get an ATS-optimized resume compiled to PDF — in seconds.

- **50+ resume templates** — professional LaTeX templates across 12 industries, with PDF thumbnails and live preview
- **ATS scoring** — rule-based analysis with section detection, keyword coverage, and formatting checks
- **LLM optimization** — GPT-4o / GPT-4o-mini rewrites your resume content for the target JD
- **Semantic matching** — pgvector cosine similarity ranks your resumes against any job description
- **Deep analysis** — section-by-section LLM breakdown with strength/improvement per section
- **Real-time streaming** — WebSocket events stream LaTeX logs and LLM tokens live to the editor
- **Multi-format import** — upload PDF, Word, Markdown, or LaTeX files and convert to editable `.tex`
- **BYOK** — bring your own OpenAI / Anthropic / Gemini / OpenRouter key
- **Subscription tiers** — Free · Basic · Pro · BYOK

---

## Quick Start

```bash
# 1. Copy env template and fill in secrets
cp .env.example .env        # edit DATABASE_URL, BETTER_AUTH_SECRET, OPENAI_API_KEY, etc.

# 2. Build and start everything
make run

# 3. Seed templates (first time only)
docker exec latexy-backend python -m app.scripts.seed_templates

# 4. Compile template thumbnails & PDFs (first time, or after adding new templates)
docker exec latexy-backend python -m app.scripts.compile_templates
```

That starts the full dev stack:

| Service | URL |
|---------|-----|
| Next.js frontend | http://localhost:5180 |
| FastAPI backend + WebSocket | http://localhost:8030 |
| PostgreSQL (external access) | localhost:5434 |
| Flower (Celery monitor) | http://localhost:5555 |
| MinIO Console | http://localhost:9091 |

DB migrations run automatically on backend startup.

> **Prerequisites:** Docker + Docker Compose. Nothing else needed on the host.

---

## Architecture

```
Browser
  │  REST (api-client.ts)          → FastAPI  :8030
  │  WebSocket (/ws/jobs)          → FastAPI  :8030
  └─ Better Auth (Next.js)         → Next.js  :5180

FastAPI
  ├─ Publishes job state to Redis Pub/Sub  latexy:events:{job_id}
  ├─ Replays history from Redis Streams    latexy:stream:{job_id}
  ├─ Serves template thumbnails/PDFs from MinIO (S3)
  └─ Enqueues tasks → Celery (Redis broker)

Celery Workers (queues)
  ├─ latex     — pdflatex compilation
  ├─ llm       — OpenAI streaming tokens
  ├─ combined  — LLM optimise then compile (orchestrator)
  ├─ ats       — ATS scoring + embedding
  ├─ cleanup   — temp file & expired job removal
  └─ email     — notification tasks

Storage
  ├─ PostgreSQL 16 (pgvector) — users, resumes, templates, sessions, subscriptions
  ├─ Redis 7                  — job state, Pub/Sub events, Streams replay, Celery broker
  └─ MinIO                    — template PDFs, thumbnails (S3-compatible)
```

**Auth:** [Better Auth](https://better-auth.com) on the Next.js layer; FastAPI validates sessions via a direct `SELECT` on the `session` table.

**Embeddings:** `text-embedding-3-small` stored as `ARRAY(Float)` in PostgreSQL with a pgvector HNSW index. Computed on save, used for `/ats/semantic-match`.

---

## Pages

| Route | Description |
|-------|-------------|
| `/` | Landing page |
| `/login`, `/signup` | Authentication |
| `/templates` | Public template library — browse, preview, and use 50+ templates |
| `/dashboard` | Analytics KPI cards, activity chart, recent runs |
| `/workspace` | Resume list (grid/table), search, create/edit/optimize |
| `/workspace/new` | Create resume from template, blank, or file import |
| `/workspace/[id]/edit` | Monaco LaTeX editor with live compile |
| `/workspace/[id]/optimize` | LLM optimization with ATS scoring |
| `/try` | Resume Studio — try without signing up |
| `/billing` | Subscription management |
| `/byok` | BYOK API key management |

---

## Development

### Local dev — hybrid (recommended)

Infra (Postgres, Redis, MinIO) runs in Docker once — shared across all clones. App processes
run locally with live reload and logs in your terminal. **Port slot is auto-detected** — if
8030/5180 are taken by another clone, slot 2 (8031/5181) is picked automatically.

```bash
./scripts/dev.sh              # start infra (if not running) + app on first free slot
./scripts/dev.sh infra        # start shared Docker infra only (idempotent)
./scripts/dev.sh app          # start app processes only
./scripts/dev.sh status       # show what is running and on which ports
./scripts/dev.sh stop app     # stop this clone's app processes (infra stays up)
./scripts/dev.sh stop infra   # stop shared Docker infra
```

### Full Docker dev

Everything runs in Docker containers. Slot is **auto-detected** — no need to specify `w2` manually.

```bash
./scripts/worktree-up.sh          # start — auto-detects free slot
./scripts/worktree-up.sh w2       # start — force slot 2 (backend 8031, frontend 5181)
./scripts/worktree-up.sh stop     # stop this clone's slot (reads .dev-slot)
./scripts/worktree-up.sh stop all # stop all app slots (infra stays running)
./scripts/worktree-up.sh stop infra # stop shared infra (postgres, redis, minio)
./scripts/worktree-up.sh logs     # tail this clone's logs
./scripts/worktree-up.sh status   # show all running slots
```

See [docs/local-dev.md](docs/local-dev.md) for the full multi-clone guide.

### Makefile targets

```bash
make run              # full dev stack  (build + start everything)
make run-detach       # same, background
make run-stop         # stop whichever stack is running
make run-logs         # tail all logs

make infra            # infra only (Redis, Postgres, workers — no frontend)
make backend          # uvicorn --reload  :8030  (needs infra)
make frontend         # next dev          :5180  (needs infra)

make migrate          # alembic upgrade head
make test             # pytest + eslint/build
make lint             # ruff + eslint
```

### Scripts

```bash
# Seed resume templates into the database (idempotent — upserts on name+category)
docker exec latexy-backend python -m app.scripts.seed_templates

# Compile all templates to PDF + PNG thumbnails and upload to MinIO
# Idempotent — skips templates that already have both files in MinIO
# Run this after seeding templates, or after adding/updating any template
docker exec latexy-backend python -m app.scripts.compile_templates
```

### Running tests

```bash
make test-backend     # pytest backend/test/  (requires Postgres + Redis)
make test-frontend    # eslint + next build check
```

Tests require `DATABASE_URL` and `REDIS_URL` in the environment (the CI workflow supplies them via service containers).

---

## Environment variables

Copy `.env.example` and fill in values. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://user:pass@host:5432/latexy` |
| `BETTER_AUTH_SECRET` | Yes | 48+ char random secret |
| `JWT_SECRET_KEY` | Yes | 32+ char random secret |
| `REDIS_URL` | Yes | `redis://localhost:6379/0` |
| `OPENAI_API_KEY` | — | Enables LLM optimize + ATS deep analysis |
| `API_KEY_ENCRYPTION_KEY` | Yes | Fernet key for BYOK encryption |
| `MINIO_ENDPOINT` | — | Defaults to `http://minio:9000` in Docker |
| `MINIO_ACCESS_KEY` | — | Defaults to `minioadmin` |
| `MINIO_SECRET_KEY` | — | Defaults to `minioadmin_secret` |
| `MINIO_BUCKET` | — | Defaults to `latexy` |
| `RAZORPAY_KEY_ID` | — | Payments (India) |
| `RAZORPAY_KEY_SECRET` | — | Payments (India) |
| `RAZORPAY_WEBHOOK_SECRET` | — | Webhook signature validation |

Generate strong secrets:
```bash
openssl rand -base64 48   # BETTER_AUTH_SECRET
openssl rand -hex 32      # JWT_SECRET_KEY
```

---

## API overview

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs/submit` | Submit a job (`latex_compilation` · `llm_optimization` · `combined` · `ats_scoring`) |
| `GET` | `/jobs/{id}/state` | Current job state snapshot (REST polling fallback) |
| `GET` | `/jobs/{id}/result` | Final job result |
| `DELETE` | `/jobs/{id}` | Request cancellation |
| `WS` | `/ws/jobs` | WebSocket — subscribe to live events for any job |
| `GET` | `/templates/` | List all active templates (with thumbnail/pdf URLs) |
| `GET` | `/templates/{id}` | Template detail (includes LaTeX source) |
| `GET` | `/templates/{id}/thumbnail` | Pre-compiled PNG thumbnail |
| `GET` | `/templates/{id}/pdf` | Pre-compiled PDF |
| `POST` | `/templates/{id}/use` | Create a resume from a template (auth required) |
| `GET` | `/ats/score` | Rule-based ATS score for a resume |
| `POST` | `/ats/deep-analyze` | Queue LLM deep analysis (trial-gated for anon) |
| `POST` | `/ats/semantic-match` | Rank resumes by cosine similarity to a JD |
| `GET/POST` | `/resumes/` | Resume CRUD |
| `GET` | `/resumes/{id}/optimization-history` | Past optimization records |
| `POST` | `/byok/keys` | Add / validate a BYOK API key |
| `POST` | `/formats/upload` | Upload PDF/Word/Markdown for conversion to LaTeX |
| `GET` | `/export/{resumeId}/{format}` | Export resume in various formats |
| `GET` | `/health` | Health check |

WebSocket event types: `job.queued` · `job.started` · `job.progress` · `job.completed` · `job.failed` · `job.cancelled` · `log.line` · `llm.token` · `llm.complete` · `ats.complete` · `ats.deep_complete`

---

## Project structure

```
.
├── docker-compose.yml          # full dev stack (make run)
├── docker-compose.prod.yml     # production stack (nginx + prod images)
├── Makefile                    # all common tasks
├── .env.example                # env template
│
├── backend/
│   ├── app/
│   │   ├── api/                # FastAPI routers (jobs, templates, ATS, BYOK, resumes…)
│   │   ├── core/               # config, Redis, Celery, event bus
│   │   ├── data/templates/     # LaTeX .tex files organised by category
│   │   ├── database/           # SQLAlchemy models + connection
│   │   ├── middleware/         # auth validation
│   │   ├── models/             # Pydantic event/LLM schemas
│   │   ├── scripts/            # seed_templates, compile_templates
│   │   ├── services/           # ATS scoring, LLM, storage (MinIO), payments…
│   │   └── workers/            # Celery tasks (latex, llm, ats, orchestrator…)
│   ├── alembic/                # DB migrations
│   ├── test/                   # pytest suite (~530 tests)
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── app/                # Next.js pages (templates, workspace, dashboard…)
│   │   ├── components/         # React components (editor, PDF preview, template cards…)
│   │   ├── hooks/              # useJobStream, useATSScoring, useTrialStatus…
│   │   └── lib/                # api-client, ws-client, auth, event types
│   └── Dockerfile.dev / Dockerfile.prod
│
├── k8s/                        # Kubernetes manifests
├── nginx/                      # nginx.conf for production
├── monitoring/                 # Prometheus config + Grafana dashboards
└── scripts/                    # deploy, backup, health-check, log-aggregator
```

---

## Deployment

### Docker Compose (single server)

```bash
cp .env.example .env   # fill in production secrets
make run-prod          # nginx + prod images + Prometheus + Grafana
```

### Kubernetes

```bash
# 1. Edit k8s/namespace.yaml — replace placeholder base64 secrets
# 2. Edit k8s/backend/deployment.yaml — set your registry image
make k8s-deploy        # applies all manifests, waits for health, runs migrations
make k8s-status        # kubectl get pods/services/pvc -n latexy
```

### CI / CD

GitHub Actions runs on every push: lint → test → build. See `.github/workflows/ci.yml`.

Required repository secrets: `CI_DATABASE_URL`, `CI_JWT_SECRET_KEY`, `CI_BETTER_AUTH_SECRET`.

---

## Subscription plans

| Plan | Compilations | Optimizations | Deep analyses | Price |
|------|-------------|---------------|---------------|-------|
| Free (trial) | 3 lifetime | 3 lifetime | 2 lifetime | — |
| Basic | 50 / mo | 50 / mo | 10 / mo | ₹299 / mo |
| Pro | Unlimited | Unlimited | Unlimited | ₹599 / mo |
| BYOK | Unlimited | Unlimited | Unlimited | ₹199 / mo |

BYOK users supply their own LLM API key; platform key is not used.
