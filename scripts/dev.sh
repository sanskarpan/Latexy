#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# dev.sh — Start/stop Latexy in local dev mode
#
# Infra (postgres, redis, minio) runs in Docker.
# App layer (backend, worker, beat, frontend) runs locally with live logs.
#
# Usage:
#   ./scripts/dev.sh            # start everything
#   ./scripts/dev.sh infra      # start only Docker infra
#   ./scripts/dev.sh app        # start only app processes (infra must be up)
#   ./scripts/dev.sh stop       # stop app processes + Docker infra
#   ./scripts/dev.sh stop app   # stop only app processes (keep infra)
#   ./scripts/dev.sh stop infra # stop only Docker infra
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="${1:-all}"
SUB="${2:-all}"

# PID file for tracking background app processes
PID_FILE="$PROJECT_ROOT/.dev-pids"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
  echo ""
  echo -e "${YELLOW}→ Shutting down app processes...${NC}"
  kill $(jobs -p) 2>/dev/null || true
  wait 2>/dev/null || true
  rm -f "$PID_FILE"
  echo -e "${GREEN}✓ All app processes stopped. Docker infra still running.${NC}"
  echo "  Stop infra with: ./scripts/dev.sh stop infra"
}

stop_app() {
  if [[ -f "$PID_FILE" ]]; then
    echo -e "${YELLOW}→ Stopping app processes...${NC}"
    while read -r pid; do
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "  Stopped PID $pid"
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  # Also kill any lingering processes by name
  pkill -f "uvicorn app.main:app.*--port 8030" 2>/dev/null || true
  pkill -f "celery -A app.core.celery_app worker" 2>/dev/null || true
  pkill -f "celery -A app.core.celery_app beat" 2>/dev/null || true
  # Kill the next.js dev server on port 5180
  lsof -ti:5180 2>/dev/null | xargs kill 2>/dev/null || true
  echo -e "${GREEN}✓ App processes stopped.${NC}"
}

stop_infra() {
  echo -e "${YELLOW}→ Stopping Docker infra...${NC}"
  cd "$PROJECT_ROOT"
  docker compose -p latexy down 2>&1 | grep -v "obsolete" || true
  echo -e "${GREEN}✓ Docker infra stopped.${NC}"
}

start_infra() {
  echo -e "${CYAN}→ Starting Docker infra (postgres, redis, minio)...${NC}"
  cd "$PROJECT_ROOT"
  docker compose -p latexy up -d postgres redis minio minio-init 2>&1 | grep -v "obsolete"

  echo -e "${CYAN}→ Waiting for infra health...${NC}"
  local retries=0
  until docker exec latexy-postgres pg_isready -U latexy -d latexy >/dev/null 2>&1; do
    retries=$((retries + 1))
    if [[ $retries -ge 30 ]]; then
      echo -e "${RED}✗ Postgres not ready after 30s${NC}" && exit 1
    fi
    sleep 1
  done
  echo -e "${GREEN}  ✓ Postgres ready${NC}"

  until docker exec latexy-redis redis-cli ping >/dev/null 2>&1; do
    sleep 1
  done
  echo -e "${GREEN}  ✓ Redis ready${NC}"

  echo -e "${GREEN}→ Infra is up.${NC}"
  echo "  Postgres: localhost:5434  (user: latexy / pass: latexy_password / db: latexy)"
  echo "  Redis:    localhost:6379"
  echo "  MinIO:    localhost:9000  (console: localhost:9091)"
}

start_app() {
  echo ""
  echo -e "${CYAN}→ Running migrations...${NC}"
  cd "$PROJECT_ROOT/backend"
  alembic upgrade head 2>&1 | tail -1
  echo -e "${GREEN}  ✓ Migrations done${NC}"

  echo ""
  echo -e "${CYAN}→ Starting app processes (Ctrl+C to stop all)...${NC}"
  echo ""

  trap cleanup EXIT INT TERM

  rm -f "$PID_FILE"

  # Backend (uvicorn with reload)
  cd "$PROJECT_ROOT/backend"
  echo -e "${GREEN}  [backend]${NC}  uvicorn on :8030"
  DATABASE_URL="postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy" \
  REDIS_URL="redis://localhost:6379/0" \
  REDIS_CACHE_URL="redis://localhost:6379/1" \
  CELERY_BROKER_URL="redis://localhost:6379/0" \
  CELERY_RESULT_BACKEND="redis://localhost:6379/0" \
  MINIO_ENDPOINT="http://localhost:9000" \
  BETTER_AUTH_URL="http://localhost:5180" \
  uvicorn app.main:app --host 0.0.0.0 --port 8030 --reload --reload-dir app 2>&1 | sed "s/^/[backend]  /" &
  echo $! >> "$PID_FILE"

  # Celery worker
  echo -e "${GREEN}  [worker]${NC}   celery worker"
  DATABASE_URL="postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy" \
  REDIS_URL="redis://localhost:6379/0" \
  REDIS_CACHE_URL="redis://localhost:6379/1" \
  CELERY_BROKER_URL="redis://localhost:6379/0" \
  CELERY_RESULT_BACKEND="redis://localhost:6379/0" \
  MINIO_ENDPOINT="http://localhost:9000" \
  celery -A app.core.celery_app worker --loglevel=info --concurrency=2 \
    --queues=latex,llm,combined,ats,cleanup,email 2>&1 | sed "s/^/[worker]   /" &
  echo $! >> "$PID_FILE"

  # Celery beat
  echo -e "${GREEN}  [beat]${NC}     celery beat"
  DATABASE_URL="postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy" \
  REDIS_URL="redis://localhost:6379/0" \
  CELERY_BROKER_URL="redis://localhost:6379/0" \
  CELERY_RESULT_BACKEND="redis://localhost:6379/0" \
  celery -A app.core.celery_app beat --loglevel=info 2>&1 | sed "s/^/[beat]     /" &
  echo $! >> "$PID_FILE"

  # Frontend
  cd "$PROJECT_ROOT/frontend"
  echo -e "${GREEN}  [frontend]${NC} next.js on :5180"
  pnpm dev 2>&1 | sed "s/^/[frontend] /" &
  echo $! >> "$PID_FILE"

  echo ""
  echo -e "${GREEN}┌─────────────────────────────────────────┐${NC}"
  echo -e "${GREEN}│  Backend:  http://localhost:8030         │${NC}"
  echo -e "${GREEN}│  Frontend: http://localhost:5180         │${NC}"
  echo -e "${GREEN}│  All logs streamed below. Ctrl+C to stop│${NC}"
  echo -e "${GREEN}└─────────────────────────────────────────┘${NC}"
  echo ""

  wait
}

case "$MODE" in
  stop)
    case "$SUB" in
      app)   stop_app ;;
      infra) stop_infra ;;
      all)   stop_app; stop_infra ;;
      *)     echo "Usage: $0 stop [all|app|infra]"; exit 1 ;;
    esac
    ;;
  infra)
    start_infra
    ;;
  app)
    start_app
    ;;
  all)
    start_infra
    start_app
    ;;
  *)
    echo "Usage: $0 [all|infra|app|stop]"
    echo ""
    echo "  (no arg)    Start everything (infra + app)"
    echo "  infra       Start only Docker infra"
    echo "  app         Start only app processes"
    echo "  stop        Stop everything"
    echo "  stop app    Stop only app processes"
    echo "  stop infra  Stop only Docker infra"
    exit 1
    ;;
esac
