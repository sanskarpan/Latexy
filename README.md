# Latexy

AI-powered LaTeX resume builder. Paste your `.tex` source, describe the role, and get an ATS-optimized resume compiled to PDF — in seconds.

- **ATS scoring** — rule-based analysis with section detection, keyword coverage, and formatting checks
- **LLM optimization** — GPT-4o / GPT-4o-mini rewrites your resume content for the target JD
- **Semantic matching** — pgvector cosine similarity ranks your resumes against any job description
- **Deep analysis** — section-by-section LLM breakdown with strength/improvement per section
- **Real-time streaming** — WebSocket events stream LaTeX logs and LLM tokens live to the editor
- **BYOK** — bring your own OpenAI / Anthropic / Gemini / OpenRouter key
- **Subscription tiers** — Free · Basic · Pro · BYOK

---

## Quick Start

```bash
# 1. Copy env template and fill in secrets
cp .env.example .env        # edit DATABASE_URL, BETTER_AUTH_SECRET, OPENAI_API_KEY, etc.

# 2. Build and start everything
make run
```

That single command builds all images and starts:

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
  └─ Enqueues tasks → Celery (Redis broker)

Celery Workers (queues)
  ├─ latex     — pdflatex in Docker texlive container
  ├─ llm       — OpenAI streaming tokens
  ├─ combined  — LLM optimise then compile (orchestrator)
  ├─ ats       — ATS scoring + embedding
  ├─ cleanup   — temp file & expired job removal
  └─ email     — notification tasks
```

**Auth:** [Better Auth](https://better-auth.com) on the Next.js layer; FastAPI validates sessions via a direct `SELECT` on the `session` table.

**Embeddings:** `text-embedding-3-small` stored as `ARRAY(Float)` in PostgreSQL with a pgvector HNSW index. Computed on save, used for `/ats/semantic-match`.

---

## Development

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

### Running tests

```bash
make test-backend     # pytest backend/test/  (requires Postgres + Redis)
make test-frontend    # eslint + next build check
```

Tests require `DATABASE_URL` and `REDIS_URL` in the environment (the CI workflow supplies them via service containers).

---

## Environment variables

Copy `backend/.env.example` and fill in values. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✓ | `postgresql+asyncpg://user:pass@host:5432/latexy` |
| `BETTER_AUTH_SECRET` | ✓ | 48+ char random secret |
| `JWT_SECRET_KEY` | ✓ | 32+ char random secret |
| `REDIS_URL` | ✓ | `redis://localhost:6379/0` |
| `OPENAI_API_KEY` | — | Enables LLM optimize + ATS deep analysis |
| `API_KEY_ENCRYPTION_KEY` | ✓ | Fernet key for BYOK encryption |
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
| `GET` | `/ats/score` | Rule-based ATS score for a resume |
| `POST` | `/ats/deep-analyze` | Queue LLM deep analysis (on-demand, trial-gated for anon) |
| `POST` | `/ats/semantic-match` | Rank resumes by cosine similarity to a JD |
| `GET/POST` | `/resumes/` | Resume CRUD |
| `GET` | `/resumes/{id}/optimization-history` | Past optimization records |
| `POST` | `/byok/keys` | Add / validate a BYOK API key |
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
│   │   ├── api/                # FastAPI routers
│   │   ├── core/               # config, Redis, Celery, event bus
│   │   ├── database/           # SQLAlchemy models + connection
│   │   ├── middleware/         # auth validation
│   │   ├── models/             # Pydantic event/LLM schemas
│   │   ├── services/           # ATS scoring, LLM, embedding, payments…
│   │   └── workers/            # Celery tasks (latex, llm, ats, orchestrator…)
│   ├── alembic/                # DB migrations
│   ├── test/                   # pytest suite (~530 tests)
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── app/                # Next.js pages
│   │   ├── components/         # React components (editor, PDF preview, ATS panels…)
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
