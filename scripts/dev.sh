#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# dev.sh — Start/stop Latexy in local dev mode
#
# Infra (postgres, redis, minio) runs in Docker — shared across all worktrees.
# App layer (backend, worker, beat, frontend) runs locally with live logs.
#
# Multiple worktrees / clones are supported: port slots are auto-detected.
# If 8030/5180 are taken, slot 2 (8031/5181) is used automatically, etc.
#
# Usage:
#   ./scripts/dev.sh            # start infra (if not running) + app processes
#   ./scripts/dev.sh infra      # start only Docker infra (idempotent)
#   ./scripts/dev.sh app        # start only app processes (infra must be up)
#   ./scripts/dev.sh stop       # stop app processes + Docker infra
#   ./scripts/dev.sh stop app   # stop only app processes (keep infra)
#   ./scripts/dev.sh stop infra # stop only Docker infra
#   ./scripts/dev.sh status     # show what is running and on which ports
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="${1:-all}"
SUB="${2:-all}"

# PID file — first line is SLOT=N, remaining lines are process PIDs
PID_FILE="$PROJECT_ROOT/.dev-pids"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────

is_infra_running() {
  docker ps --format "{{.Names}}" 2>/dev/null | grep -q "^latexy-postgres$"
}

# Find first slot where BOTH backend port and frontend port are free.
# Slot 1 → backend 8030, frontend 5180
# Slot 2 → backend 8031, frontend 5181  ...etc
detect_free_slot() {
  for slot in 1 2 3 4; do
    local bp=$((8029 + slot))
    local fp=$((5179 + slot))
    if ! lsof -ti:"$bp" >/dev/null 2>&1 && ! lsof -ti:"$fp" >/dev/null 2>&1; then
      echo "$slot"
      return 0
    fi
  done
  echo ""
}

resolve_venv_bin() {
  local venv="${PROJECT_ROOT}/backend/.venv/bin"
  [[ ! -d "$venv" ]] && venv="${PROJECT_ROOT}/backend/venv/bin"
  echo "$venv"
}

cleanup() {
  echo ""
  echo -e "${YELLOW}→ Shutting down app processes...${NC}"
  kill $(jobs -p) 2>/dev/null || true
  wait 2>/dev/null || true
  rm -f "$PID_FILE"
  echo -e "${GREEN}✓ App processes stopped. Docker infra still running.${NC}"
  echo "  Stop infra with: ./scripts/dev.sh stop infra"
}

# ── stop ─────────────────────────────────────────────────────────────────────

stop_app() {
  # Read slot from PID file so we know which ports to free
  local slot=1
  if [[ -f "$PID_FILE" ]]; then
    local saved
    saved=$(grep "^SLOT=" "$PID_FILE" 2>/dev/null | cut -d= -f2 || true)
    [[ -n "$saved" ]] && slot="$saved"
    echo -e "${YELLOW}→ Stopping app processes (slot ${slot})...${NC}"
    while IFS= read -r line; do
      [[ "$line" =~ ^SLOT= ]] && continue
      if [[ -n "$line" ]] && kill -0 "$line" 2>/dev/null; then
        kill "$line" 2>/dev/null || true
        echo "  Stopped PID $line"
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  else
    echo -e "${YELLOW}→ No PID file found. Killing by port...${NC}"
  fi

  local bp=$((8029 + slot))
  local fp=$((5179 + slot))
  lsof -ti:"$bp" 2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti:"$fp" 2>/dev/null | xargs kill 2>/dev/null || true
  echo -e "${GREEN}✓ App processes stopped.${NC}"
}

stop_infra() {
  echo -e "${YELLOW}→ Stopping shared Docker infra...${NC}"
  cd "$PROJECT_ROOT"
  docker compose -p latexy down 2>&1 | grep -v "obsolete" || true
  echo -e "${GREEN}✓ Docker infra stopped.${NC}"
}

# ── infra ─────────────────────────────────────────────────────────────────────

start_infra() {
  if is_infra_running; then
    echo -e "${GREEN}→ Shared infra already running (latexy-postgres, redis, minio). Skipping.${NC}"
    return 0
  fi

  echo -e "${CYAN}→ Starting shared Docker infra (postgres, redis, minio)...${NC}"
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

  until docker exec latexy-redis redis-cli ping >/dev/null 2>&1; do sleep 1; done
  echo -e "${GREEN}  ✓ Redis ready${NC}"

  echo -e "${GREEN}→ Shared infra is up.${NC}"
  echo "  Postgres: localhost:5434  Redis: localhost:6379  MinIO: localhost:9000"
}

# ── app ───────────────────────────────────────────────────────────────────────

start_app() {
  local VENV_BIN
  VENV_BIN=$(resolve_venv_bin)
  local ALEMBIC="${VENV_BIN}/alembic"
  local UVICORN="${VENV_BIN}/uvicorn"
  local CELERY="${VENV_BIN}/celery"

  # ── Port slot auto-detection ──────────────────────────────────────────────
  local SLOT
  SLOT=$(detect_free_slot)
  if [[ -z "$SLOT" ]]; then
    echo -e "${RED}✗ All port slots taken (checked 8030–8033 and 5180–5183).${NC}"
    echo "  Stop another instance first: ./scripts/dev.sh stop app"
    exit 1
  fi

  local BACKEND_PORT=$((8029 + SLOT))
  local FRONTEND_PORT=$((5179 + SLOT))

  echo ""
  echo -e "${CYAN}→ Slot ${SLOT} — backend :${BACKEND_PORT}  frontend :${FRONTEND_PORT}${NC}"

  # ── Shared env vars ───────────────────────────────────────────────────────
  local DB_URL="postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy"
  local REDIS="redis://localhost:6379/0"
  local REDIS_CACHE="redis://localhost:6379/1"
  local MINIO="http://localhost:9000"
  # Allow all dev frontend ports so CORS works for both dirs
  local CORS='["http://localhost:5180","http://localhost:5181","http://localhost:5182","http://localhost:5183","http://127.0.0.1:5180","http://127.0.0.1:5181"]'

  # ── Migrations ────────────────────────────────────────────────────────────
  echo ""
  echo -e "${CYAN}→ Running migrations...${NC}"
  cd "$PROJECT_ROOT/backend"
  DATABASE_URL="$DB_URL" "$ALEMBIC" upgrade head 2>&1 | tail -3
  echo -e "${GREEN}  ✓ Migrations done${NC}"

  echo ""
  echo -e "${CYAN}→ Starting app processes (Ctrl+C to stop all)...${NC}"
  echo ""

  trap cleanup EXIT INT TERM
  echo "SLOT=${SLOT}" > "$PID_FILE"

  # ── Backend ───────────────────────────────────────────────────────────────
  cd "$PROJECT_ROOT/backend"
  echo -e "${GREEN}  [backend]${NC}  uvicorn on :${BACKEND_PORT}"
  DATABASE_URL="$DB_URL" \
  REDIS_URL="$REDIS" \
  REDIS_CACHE_URL="$REDIS_CACHE" \
  CELERY_BROKER_URL="$REDIS" \
  CELERY_RESULT_BACKEND="$REDIS" \
  MINIO_ENDPOINT="$MINIO" \
  BETTER_AUTH_URL="http://localhost:${FRONTEND_PORT}" \
  FRONTEND_URL="http://localhost:${FRONTEND_PORT}" \
  CORS_ORIGINS="$CORS" \
  "$UVICORN" app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --reload-dir app \
    2>&1 | sed "s/^/[backend]  /" &
  echo $! >> "$PID_FILE"

  # ── Celery worker ─────────────────────────────────────────────────────────
  echo -e "${GREEN}  [worker]${NC}   celery worker"
  DATABASE_URL="$DB_URL" \
  REDIS_URL="$REDIS" \
  REDIS_CACHE_URL="$REDIS_CACHE" \
  CELERY_BROKER_URL="$REDIS" \
  CELERY_RESULT_BACKEND="$REDIS" \
  MINIO_ENDPOINT="$MINIO" \
  "$CELERY" -A app.core.celery_app worker --loglevel=info --concurrency=2 \
    --queues=latex,llm,combined,ats,cleanup,email \
    2>&1 | sed "s/^/[worker]   /" &
  echo $! >> "$PID_FILE"

  # ── Celery beat ───────────────────────────────────────────────────────────
  echo -e "${GREEN}  [beat]${NC}     celery beat"
  DATABASE_URL="$DB_URL" \
  REDIS_URL="$REDIS" \
  CELERY_BROKER_URL="$REDIS" \
  CELERY_RESULT_BACKEND="$REDIS" \
  "$CELERY" -A app.core.celery_app beat --loglevel=info \
    2>&1 | sed "s/^/[beat]     /" &
  echo $! >> "$PID_FILE"

  # ── Frontend ──────────────────────────────────────────────────────────────
  cd "$PROJECT_ROOT/frontend"
  echo -e "${GREEN}  [frontend]${NC} next.js on :${FRONTEND_PORT}"
  NEXT_PUBLIC_API_URL="http://localhost:${BACKEND_PORT}" \
  NEXT_PUBLIC_WS_URL="ws://localhost:${BACKEND_PORT}" \
  NEXT_PUBLIC_APP_URL="http://localhost:${FRONTEND_PORT}" \
  BETTER_AUTH_URL="http://localhost:${FRONTEND_PORT}" \
  PORT="${FRONTEND_PORT}" \
  pnpm dev 2>&1 | sed "s/^/[frontend] /" &
  echo $! >> "$PID_FILE"

  echo ""
  echo -e "${GREEN}┌─────────────────────────────────────────┐${NC}"
  printf "${GREEN}│  Backend:  http://localhost:%-13s│${NC}\n" "${BACKEND_PORT}"
  printf "${GREEN}│  Frontend: http://localhost:%-13s│${NC}\n" "${FRONTEND_PORT}"
  echo -e "${GREEN}│  All logs streamed below. Ctrl+C to stop│${NC}"
  echo -e "${GREEN}└─────────────────────────────────────────┘${NC}"
  echo ""

  wait
}

# ── status ────────────────────────────────────────────────────────────────────

show_status() {
  echo ""
  echo "Shared infra:"
  if is_infra_running; then
    echo -e "  ${GREEN}✓ latexy-postgres${NC}  latexy-redis  latexy-minio"
  else
    echo -e "  ${RED}✗ not running${NC}  (start with: ./scripts/dev.sh infra)"
  fi

  echo ""
  echo "App processes (all slots):"
  for slot in 1 2 3 4; do
    local bp=$((8029 + slot))
    local fp=$((5179 + slot))
    local backend_pid frontend_pid
    backend_pid=$(lsof -ti:"$bp" 2>/dev/null || true)
    frontend_pid=$(lsof -ti:"$fp" 2>/dev/null || true)
    if [[ -n "$backend_pid" || -n "$frontend_pid" ]]; then
      printf "  ${GREEN}Slot %d${NC}  backend :%-5s  frontend :%-5s\n" "$slot" "$bp" "$fp"
    fi
  done
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────

case "$MODE" in
  stop)
    case "$SUB" in
      app)   stop_app ;;
      infra) stop_infra ;;
      *)     stop_app; stop_infra ;;
    esac
    ;;
  infra)   start_infra ;;
  app)     start_app ;;
  status)  show_status ;;
  all)     start_infra; start_app ;;
  *)
    echo "Usage: $0 [all|infra|app|status|stop [app|infra]]"
    echo ""
    echo "  (no arg)       Start infra (if needed) + app on first free port slot"
    echo "  infra          Start shared Docker infra only (idempotent)"
    echo "  app            Start app processes only (auto-detects free port slot)"
    echo "  status         Show what is running and on which ports"
    echo "  stop           Stop app processes + Docker infra"
    echo "  stop app       Stop app processes only (keep infra running)"
    echo "  stop infra     Stop Docker infra only"
    echo ""
    echo "  Port slots: slot 1 → backend 8030 / frontend 5180"
    echo "              slot 2 → backend 8031 / frontend 5181"
    echo "              slot 3 → backend 8032 / frontend 5182"
    exit 1
    ;;
esac
