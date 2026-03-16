# Local Development & Multi-Worktree Guide

## Overview

Latexy has two local dev modes:

| Mode | Infra | App layer | Best for |
|------|-------|-----------|----------|
| **Hybrid** (`dev.sh`) | Docker | Local processes | Day-to-day dev — fast reload, live logs in terminal |
| **Full Docker** (`worktree-up.sh`) | Docker | Docker | Multi-worktree / CI-like parity |

Both modes share the same Docker infra containers (Postgres, Redis, MinIO). Only the app layer
(backend, worker, beat, frontend) differs. Multiple separate clones (e.g. `~/dev/Latexy` and
`~/dev/Latexy2`) can run simultaneously — ports are auto-detected.

---

## Port slots

Both scripts use the same slot system to avoid conflicts. A slot is auto-detected based on
which ports are free. You can also pin a slot explicitly.

| Slot | Backend | Frontend | Flower | Docker project |
|------|---------|----------|--------|----------------|
| 1 (default) | 8030 | 5180 | 5555 | `latexy` |
| 2 | 8031 | 5181 | 5556 | `latexy-w2` |
| 3 | 8032 | 5182 | 5557 | `latexy-w3` |
| 4 | 8033 | 5183 | 5558 | `latexy-w4` |

If slot 1 is already in use (by another clone or worktree), slot 2 is picked automatically.

---

## Hybrid mode (`dev.sh`)

Runs Postgres, Redis, and MinIO in Docker. Backend (uvicorn), Celery worker, Celery beat, and
frontend (Next.js) run as **local processes** with logs streamed to your terminal.

### Commands

```bash
./scripts/dev.sh              # start infra (if not running) + app on first free slot
./scripts/dev.sh infra        # start only Docker infra (idempotent — safe to call twice)
./scripts/dev.sh app          # start only app processes (infra must already be up)
./scripts/dev.sh status       # show what is running and on which ports
./scripts/dev.sh stop         # stop app processes + Docker infra
./scripts/dev.sh stop app     # stop app processes only (keep infra running)
./scripts/dev.sh stop infra   # stop Docker infra only
```

### What runs where

| Process | How | Port |
|---------|-----|------|
| PostgreSQL | Docker (`latexy-postgres`) | 5434 (host) → 5432 (container) |
| Redis | Docker (`latexy-redis`) | 6379 |
| MinIO | Docker (`latexy-minio`) | 9000 (API), 9091 (console) |
| FastAPI (uvicorn) | Local, `--reload` | 8030 (slot 1) or 8031+ |
| Celery worker | Local, 2 concurrency | — |
| Celery beat | Local | — |
| Next.js | Local, `pnpm dev` | 5180 (slot 1) or 5181+ |

All app process logs are prefixed (`[backend]`, `[worker]`, `[beat]`, `[frontend]`) and
interleaved in your terminal. Press **Ctrl+C** to stop all app processes; Docker infra keeps
running.

### Multi-clone / multi-worktree

```bash
# Clone 1 (~/dev/Latexy) — picks slot 1 automatically
cd ~/dev/Latexy
./scripts/dev.sh app
# → backend :8030, frontend :5180

# Clone 2 (~/dev/Latexy2) — detects 8030/5180 taken, picks slot 2
cd ~/dev/Latexy2
./scripts/dev.sh app
# → backend :8031, frontend :5181
```

Infra is shared. Starting infra from either directory is idempotent — the second `dev.sh infra`
call is a no-op if `latexy-postgres` is already running.

### Stopping

```bash
./scripts/dev.sh stop app     # stops just this directory's app processes (reads .dev-pids)
./scripts/dev.sh stop infra   # stops shared infra — affects ALL clones, use with care
```

### Prerequisites

- Docker + Docker Compose
- Python 3.12/3.13 with `pip install -r backend/requirements.txt` (inside `.venv`)
- Node.js 20+ with `pnpm install` in `frontend/`
- `.venv` or `venv` inside `backend/` (scripts auto-detect whichever exists)

---

## Full Docker mode (`worktree-up.sh`)

Everything runs in Docker containers. Slot is auto-detected (no need to specify `w2` manually).

### Commands

```bash
# Start
./scripts/worktree-up.sh          # start — auto-detect free slot
./scripts/worktree-up.sh w2       # start — force slot 2
./scripts/worktree-up.sh w3       # start — force slot 3

# Stop
./scripts/worktree-up.sh stop         # stop this directory's slot (reads .dev-slot)
./scripts/worktree-up.sh stop w2      # stop slot 2 explicitly
./scripts/worktree-up.sh stop all     # stop all app slots (infra stays running)
./scripts/worktree-up.sh stop infra   # stop shared infra (postgres, redis, minio)

# Logs
./scripts/worktree-up.sh logs         # tail this directory's slot logs
./scripts/worktree-up.sh logs w2      # tail slot 2 logs

# Status
./scripts/worktree-up.sh status       # show all running slots

# Or use docker directly
docker logs -f latexy-backend-2       # follow backend logs for slot 2
docker compose -p latexy-w2 logs -f   # follow all logs for slot 2
```

### How it works

```
                    Shared (one instance — any dir can start it)
                    ┌──────────────────────┐
                    │  postgres  (5434)    │
                    │  redis     (6379)    │
                    │  minio     (9000)    │
                    └──────────┬───────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                     │
  ~/dev/Latexy            ~/dev/Latexy2        (any future clone)
  Slot 1 (latexy)         Slot 2 (latexy-w2)   Slot 3 (latexy-w3)
  ┌─────────────┐          ┌─────────────┐      ┌─────────────┐
  │ backend :8030│         │ backend :8031│     │ backend :8032│
  │ worker      │          │ worker      │     │ worker      │
  │ beat        │          │ beat        │     │ beat        │
  │ frontend :5180│        │ frontend :5181│    │ frontend :5182│
  │ flower  :5555│         │ flower  :5556│    │ flower  :5557│
  └─────────────┘          └─────────────┘     └─────────────┘
```

### Typical workflow

```bash
# Main clone — auto-detects slot 1
cd ~/dev/Latexy
./scripts/worktree-up.sh
# → backend :8030, frontend :5180

# Second clone — auto-detects slot 2 (8030 taken)
cd ~/dev/Latexy2
./scripts/worktree-up.sh
# → backend :8031, frontend :5181

# Done with second clone
cd ~/dev/Latexy2
./scripts/worktree-up.sh stop    # reads .dev-slot, stops slot 2 only
```

### Note on backend startup time

The backend container can take **3–7 minutes** on a cold start (first run, no `.pyc` cache)
because Python imports the full FastAPI app. The healthcheck is configured with
`start_period: 300s` to account for this. Subsequent starts are faster once `.pyc` files
are cached.

The frontend only waits for the backend **process** to start (`service_started`), not for
it to pass health checks, so the frontend comes up immediately.

---

## Docker Compose parameterization

The root `docker-compose.yml` uses environment variables for all per-slot values:

| Variable | Default | Description |
|----------|---------|-------------|
| `SLOT` | `1` | Slot number (used in container names and volume names) |
| `BACKEND_PORT` | `8030` | Host port for FastAPI |
| `FRONTEND_PORT` | `5180` | Host port for Next.js |
| `FLOWER_PORT` | `5555` | Host port for Flower |
| `DB_PORT` | `5434` | Host port for PostgreSQL |
| `MINIO_CONSOLE_PORT` | `9091` | Host port for MinIO console |

Container names follow the pattern `latexy-{service}-{SLOT}` (e.g., `latexy-backend-2`).
Volumes are also slot-specific (`backend_temp_2`, `celery_beat_data_2`).

---

## Dockerfiles

| File | Purpose | Base image | Notes |
|------|---------|------------|-------|
| `backend/Dockerfile` | **Dev** | `python:3.13-slim` | Includes texlive, tesseract. Source mounted as volume for hot-reload. |
| `backend/Dockerfile.prod` | **Production** | `python:3.11-slim` (multi-stage) | Builder stage for pip deps, production stage with texlive. Runs 4 uvicorn workers on port 8000. |
| `frontend/Dockerfile.dev` | **Dev** | `node:20-alpine` | pnpm, source mounted as volume. Accepts `PORT` env var. |
| `frontend/Dockerfile.prod` | **Production** | `node:18-alpine` (multi-stage) | Standalone Next.js build with `dumb-init`. Runs on port 3000. |

### Production stack

`docker-compose.prod.yml` uses the `.prod` Dockerfiles and adds:

- **nginx** reverse proxy (ports 80/443)
- **Replicas**: 2x frontend, 3x backend, 2x celery worker
- **Resource limits** per container
- **Prometheus + Grafana** for monitoring

```bash
make run-prod    # start production stack
```

---

## Troubleshooting

### Port already in use

```bash
lsof -ti:8030 | xargs kill   # kill whatever is on port 8030
./scripts/dev.sh status       # check which slots are in use
```

### Backend container unhealthy / takes too long to start

On a cold start (no `.pyc` cache), the backend can take 3–7 minutes to fully import.
This is normal. The healthcheck `start_period: 300s` is intentionally generous.

```bash
docker logs latexy-backend-1 --tail 20   # check what the backend is doing
```

If it's stuck for >10 minutes, check for import errors:

```bash
docker exec latexy-backend-1 python -c "import app.main"
```

### Alembic migration fails with "table already exists"

If a table was created before the migration was tracked:

```bash
docker exec latexy-postgres psql -U latexy -d latexy \
  -c "UPDATE alembic_version SET version_num = '1a059d00cd5e';"
```

### Multiple Alembic heads

If `alembic upgrade head` fails with "multiple heads":

```bash
cd backend
.venv/bin/alembic heads           # see the heads
.venv/bin/alembic merge head1 head2 -m "merge_branches"
.venv/bin/alembic upgrade head
```

### Containers keep restarting

```bash
docker logs latexy-backend-1 --tail 50    # check what's failing
docker stop latexy-backend-1 && docker rm latexy-backend-1
./scripts/worktree-up.sh                   # recreate
```

### Infra containers auto-start on Docker Desktop restart

Docker Desktop restores containers that were running when it shut down. If you only want
infra running (not the full app stack), stop the app containers after Docker Desktop starts:

```bash
docker stop latexy-backend-1 latexy-frontend-1 latexy-worker-1 latexy-beat-1 latexy-flower-1
docker rm latexy-backend-1 latexy-frontend-1 latexy-worker-1 latexy-beat-1 latexy-flower-1
# Then start app layer locally:
./scripts/dev.sh app
```
