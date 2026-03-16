# Local Development & Multi-Worktree Guide

## Overview

Latexy has two local dev modes:

| Mode | Infra | App layer | Best for |
|------|-------|-----------|----------|
| **Hybrid** (`dev.sh`) | Docker | Local processes | Day-to-day dev — fast reload, live logs in terminal |
| **Full Docker** (`worktree-up.sh`) | Docker | Docker | Multi-worktree / CI-like parity |

Both modes share the same Docker infra containers (Postgres, Redis, MinIO). Only the app layer (backend, worker, beat, frontend) differs.

---

## Hybrid mode (`dev.sh`)

Runs Postgres, Redis, and MinIO in Docker. Backend (uvicorn), Celery worker, Celery beat, and frontend (Next.js) run as local processes with logs streamed to your terminal.

### Commands

```bash
./scripts/dev.sh              # start infra + all app processes
./scripts/dev.sh infra        # start only Docker infra
./scripts/dev.sh app          # start only app processes (infra must already be up)
./scripts/dev.sh stop         # stop everything (app + infra)
./scripts/dev.sh stop app     # stop app processes only (keep infra running)
./scripts/dev.sh stop infra   # stop Docker infra only
```

### What runs where

| Process | How | Port |
|---------|-----|------|
| PostgreSQL | Docker (`latexy-postgres`) | 5434 (mapped from 5432) |
| Redis | Docker (`latexy-redis`) | 6379 |
| MinIO | Docker (`latexy-minio`) | 9000 (API), 9091 (console) |
| FastAPI (uvicorn) | Local, `--reload` | 8030 |
| Celery worker | Local, 2 concurrency | — |
| Celery beat | Local | — |
| Next.js | Local, `pnpm dev` | 5180 |

All app process logs are prefixed (`[backend]`, `[worker]`, `[beat]`, `[frontend]`) and interleaved in your terminal. Press **Ctrl+C** to stop all app processes; Docker infra keeps running.

### Prerequisites

- Docker + Docker Compose
- Python 3.13+ with `pip install -r backend/requirements.txt`
- Node.js 20+ with `pnpm install` in `frontend/`
- `alembic`, `uvicorn`, `celery` available on your PATH (installed via requirements.txt)

---

## Full Docker mode (`worktree-up.sh`)

Everything runs in Docker containers. Supports running multiple git worktrees simultaneously with separate ports.

### Slot system

Each worktree gets a **slot number** that determines its ports:

| Slot | Arg | Backend | Frontend | Flower | Compose project |
|------|-----|---------|----------|--------|-----------------|
| 1 | _(none)_ | 8030 | 5180 | 5555 | `latexy` |
| 2 | `w2` | 8031 | 5181 | 5556 | `latexy-w2` |
| 3 | `w3` | 8032 | 5182 | 5557 | `latexy-w3` |
| 4 | `w4` | 8033 | 5183 | 5558 | `latexy-w4` |

### Commands

```bash
# Start
./scripts/worktree-up.sh          # start slot 1 (default ports)
./scripts/worktree-up.sh w2       # start slot 2
./scripts/worktree-up.sh w3       # start slot 3

# Stop
./scripts/worktree-up.sh stop         # stop slot 1
./scripts/worktree-up.sh stop w2      # stop slot 2
./scripts/worktree-up.sh stop all     # stop ALL slots + shared infra

# Logs
./scripts/worktree-up.sh logs         # tail slot 1 logs
./scripts/worktree-up.sh logs w2      # tail slot 2 logs

# Or use docker directly
docker logs -f latexy-backend-2       # follow backend logs for slot 2
docker compose -p latexy-w2 logs -f   # follow all logs for slot 2
```

### How it works

```
                    Shared (one instance)
                    ┌──────────────────────┐
                    │  postgres  (5434)    │
                    │  redis     (6379)    │
                    │  minio     (9000)    │
                    └──────────┬───────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                     │
   Slot 1 (latexy)     Slot 2 (latexy-w2)    Slot 3 (latexy-w3)
   ┌─────────────┐     ┌─────────────┐       ┌─────────────┐
   │ backend  :8030│   │ backend  :8031│     │ backend  :8032│
   │ worker       │   │ worker       │     │ worker       │
   │ beat         │   │ beat         │     │ beat         │
   │ frontend :5180│   │ frontend :5181│     │ frontend :5182│
   │ flower   :5555│   │ flower   :5556│     │ flower   :5557│
   └─────────────┘     └─────────────┘       └─────────────┘
```

Shared infra is started automatically by the script (under the `latexy` Compose project). Per-slot app containers run under their own Compose project (`latexy-w2`, etc.) so they can be started/stopped independently.

### Typical workflow

```bash
# Main branch — slot 1
cd ~/dev/Latexy
./scripts/worktree-up.sh
# → backend on :8030, frontend on :5180

# Feature branch — slot 2
cd ~/dev/Latexy
git worktree add .claude/worktrees/feat-auth feat/auth
cd .claude/worktrees/feat-auth
../../../scripts/worktree-up.sh w2
# → backend on :8031, frontend on :5181

# Done with the feature
./scripts/worktree-up.sh stop w2
git worktree remove .claude/worktrees/feat-auth
```

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

Container names follow the pattern `latexy-{service}-{SLOT}` (e.g., `latexy-backend-2`). Volumes are also slot-specific (`backend_temp_2`, `celery_beat_data_2`).

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
```

### Alembic migration fails with "table already exists"

If a table was created before the migration was tracked:

```bash
# Stamp alembic to the current state without running the migration
docker exec latexy-postgres psql -U latexy -d latexy \
  -c "UPDATE alembic_version SET version_num = '0006_add_cover_letters';"
```

### Containers keep restarting

```bash
docker logs latexy-backend-1 --tail 50    # check what's failing
docker stop latexy-backend-1 && docker rm latexy-backend-1   # remove stuck container
./scripts/worktree-up.sh                   # recreate
```
