#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# worktree-up.sh — Start/stop Docker app-layer for a specific worktree / clone
#
# Shared infra (postgres, redis, minio) runs once under the "latexy" Compose
# project — regardless of which directory starts it.
# Per-slot app containers (backend, worker, beat, frontend, flower) run under
# their own Compose project so they can be stopped independently.
#
# Slot is auto-detected by default (first free port pair). You can also pin a
# slot explicitly.
#
# Usage:
#   ./scripts/worktree-up.sh          # start — auto-detect free slot
#   ./scripts/worktree-up.sh w2       # start — force slot 2
#   ./scripts/worktree-up.sh stop     # stop this directory's slot
#   ./scripts/worktree-up.sh stop w2  # stop slot 2 explicitly
#   ./scripts/worktree-up.sh stop all # stop ALL slots + shared infra
#   ./scripts/worktree-up.sh logs     # tail this directory's slot logs
#   ./scripts/worktree-up.sh logs w2  # tail slot 2 logs
#   ./scripts/worktree-up.sh status   # show all running slots
#
# Slot → Port mapping:
#   Slot 1  backend 8030  frontend 5180  flower 5555  project: latexy
#   Slot 2  backend 8031  frontend 5181  flower 5556  project: latexy-w2
#   Slot 3  backend 8032  frontend 5182  flower 5557  project: latexy-w3
#   Slot 4  backend 8033  frontend 5183  flower 5558  project: latexy-w4
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Per-directory file to remember which slot was auto-assigned
SLOT_FILE="$PROJECT_ROOT/.dev-slot"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Slot helpers ──────────────────────────────────────────────────────────────

slot_ports() {
  local slot="$1"
  BACKEND_PORT=$((8029 + slot))
  FRONTEND_PORT=$((5179 + slot))
  FLOWER_PORT=$((5554 + slot))
  if [[ "$slot" -eq 1 ]]; then
    PROJECT_NAME="latexy"
  else
    PROJECT_NAME="latexy-w${slot}"
  fi
}

# Find the first slot where both backend and frontend ports are free
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

# Read slot from per-directory .dev-slot file, or auto-detect
resolve_slot_for_dir() {
  if [[ -f "$SLOT_FILE" ]]; then
    cat "$SLOT_FILE"
  else
    detect_free_slot
  fi
}

# Parse "w2" → 2, "" → auto-detect, anything else → error
parse_slot_arg() {
  local arg="${1:-}"
  if [[ -z "$arg" ]]; then
    local detected
    detected=$(detect_free_slot)
    if [[ -z "$detected" ]]; then
      echo -e "${RED}✗ All port slots taken (checked 8030–8033). Stop another instance first.${NC}" >&2
      exit 1
    fi
    echo "$detected"
  elif [[ "$arg" =~ ^w([2-9])$ ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo -e "${RED}✗ Invalid slot '${arg}'. Use w2, w3, or w4.${NC}" >&2
    exit 1
  fi
}

# ── Banner ────────────────────────────────────────────────────────────────────

print_banner() {
  local slot="$1"
  slot_ports "$slot"
  echo "┌─────────────────────────────────────────┐"
  printf "│  Latexy — slot %-25s│\n" "${slot}  ($(basename "$PROJECT_ROOT"))"
  echo "├─────────────────────────────────────────┤"
  printf "│  Backend:  http://localhost:%-13s│\n" "${BACKEND_PORT}"
  printf "│  Frontend: http://localhost:%-13s│\n" "${FRONTEND_PORT}"
  printf "│  Flower:   http://localhost:%-13s│\n" "${FLOWER_PORT}"
  printf "│  Project:  %-29s│\n" "${PROJECT_NAME}"
  echo "└─────────────────────────────────────────┘"
}

# ── Infra ─────────────────────────────────────────────────────────────────────

is_infra_running() {
  docker ps --format "{{.Names}}" 2>/dev/null | grep -q "^latexy-postgres$"
}

ensure_infra() {
  if is_infra_running; then
    echo -e "${GREEN}→ Shared infra already running (latexy-postgres, redis, minio). Skipping.${NC}"
    return 0
  fi

  echo -e "${CYAN}→ Starting shared Docker infra (postgres, redis, minio)...${NC}"
  cd "$PROJECT_ROOT"
  docker compose -p latexy up -d postgres redis minio minio-init 2>&1 | grep -v "obsolete" || true

  echo -e "${CYAN}→ Waiting for postgres & redis...${NC}"
  local retries=0
  until docker exec latexy-postgres pg_isready -U latexy -d latexy >/dev/null 2>&1; do
    retries=$((retries + 1))
    [[ $retries -ge 30 ]] && echo -e "${RED}✗ Postgres not ready after 30s${NC}" && exit 1
    sleep 1
  done
  echo -e "${GREEN}  ✓ Postgres ready${NC}"

  until docker exec latexy-redis redis-cli ping >/dev/null 2>&1; do sleep 1; done
  echo -e "${GREEN}  ✓ Redis ready${NC}"

  echo -e "${GREEN}→ Shared infra is up.${NC}"
}

# ── Start / Stop ──────────────────────────────────────────────────────────────

start_slot() {
  local slot="$1"
  slot_ports "$slot"

  print_banner "$slot"
  ensure_infra

  echo ""
  echo -e "${CYAN}→ Starting app containers for slot ${slot} (${PROJECT_NAME})...${NC}"
  cd "$PROJECT_ROOT"

  SLOT=$slot \
  BACKEND_PORT=$BACKEND_PORT \
  FRONTEND_PORT=$FRONTEND_PORT \
  FLOWER_PORT=$FLOWER_PORT \
    docker compose -p "$PROJECT_NAME" up -d backend worker beat frontend flower

  # Save slot to per-directory file so stop/logs work without explicit arg
  echo "$slot" > "$SLOT_FILE"

  echo ""
  echo -e "${GREEN}✓ Slot ${slot} is up from $(basename "$PROJECT_ROOT").${NC}"
  echo ""
  echo "  Logs:  ./scripts/worktree-up.sh logs"
  echo "  Stop:  ./scripts/worktree-up.sh stop"
}

stop_slot() {
  local slot="$1"
  slot_ports "$slot"
  echo -e "${YELLOW}→ Stopping slot ${slot} (${PROJECT_NAME})...${NC}"
  cd "$PROJECT_ROOT"
  SLOT=$slot \
  BACKEND_PORT=$BACKEND_PORT \
  FRONTEND_PORT=$FRONTEND_PORT \
  FLOWER_PORT=$FLOWER_PORT \
    docker compose -p "$PROJECT_NAME" down --remove-orphans 2>&1 | grep -v "obsolete" || true
  rm -f "$SLOT_FILE"
  echo -e "${GREEN}✓ Slot ${slot} stopped.${NC}"
}

stop_all() {
  echo -e "${YELLOW}→ Stopping all app slots (keeping shared infra running)...${NC}"
  cd "$PROJECT_ROOT"
  for s in 1 2 3 4; do
    local pname="latexy-w${s}"
    [[ "$s" -eq 1 ]] && pname="latexy"
    # Stop only app-layer services — do NOT take down the whole project
    # (which would also stop postgres/redis/minio shared infra)
    SLOT=$s \
    BACKEND_PORT=$((8029 + s)) \
    FRONTEND_PORT=$((5179 + s)) \
    FLOWER_PORT=$((5554 + s)) \
      docker compose -p "$pname" stop backend worker beat frontend flower 2>/dev/null || true
    SLOT=$s \
    BACKEND_PORT=$((8029 + s)) \
    FRONTEND_PORT=$((5179 + s)) \
    FLOWER_PORT=$((5554 + s)) \
      docker compose -p "$pname" rm -f backend worker beat frontend flower 2>/dev/null || true
  done
  rm -f "$SLOT_FILE"
  echo -e "${GREEN}✓ All app slots stopped. Shared infra (postgres, redis, minio) still running.${NC}"
  echo "  Stop infra: docker compose -p latexy stop postgres redis minio"
}

stop_infra() {
  echo -e "${YELLOW}→ Stopping shared infra (postgres, redis, minio)...${NC}"
  cd "$PROJECT_ROOT"
  docker compose -p latexy stop postgres redis minio 2>/dev/null || true
  echo -e "${GREEN}✓ Shared infra stopped.${NC}"
}

tail_logs() {
  local slot="$1"
  slot_ports "$slot"
  echo -e "${CYAN}→ Tailing logs for slot ${slot} (${PROJECT_NAME})...${NC}"
  cd "$PROJECT_ROOT"
  SLOT=$slot \
  BACKEND_PORT=$BACKEND_PORT \
  FRONTEND_PORT=$FRONTEND_PORT \
  FLOWER_PORT=$FLOWER_PORT \
    docker compose -p "$PROJECT_NAME" logs -f backend worker frontend
}

show_status() {
  echo ""
  echo "Shared infra:"
  if is_infra_running; then
    echo -e "  ${GREEN}✓ running${NC}  (latexy-postgres, latexy-redis, latexy-minio)"
  else
    echo -e "  ${RED}✗ not running${NC}"
  fi
  echo ""
  echo "App slots:"
  for slot in 1 2 3 4; do
    slot_ports "$slot"
    local containers
    containers=$(docker ps --format "{{.Names}}" 2>/dev/null | grep "latexy.*-${slot}$" || true)
    if [[ -n "$containers" ]]; then
      printf "  ${GREEN}Slot %d${NC}  %-14s  backend :%-5s  frontend :%-5s  flower :%-4s\n" \
        "$slot" "$PROJECT_NAME" "$BACKEND_PORT" "$FRONTEND_PORT" "$FLOWER_PORT"
    fi
  done
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────

ACTION="${1:-}"

case "$ACTION" in
  stop)
    TARGET="${2:-}"
    if [[ "$TARGET" == "all" ]]; then
      stop_all
    elif [[ "$TARGET" == "infra" ]]; then
      stop_infra
    else
      # If explicit slot given use it, else read from .dev-slot file
      local_slot=""
      if [[ -n "$TARGET" && "$TARGET" =~ ^w([2-9])$ ]]; then
        local_slot="${BASH_REMATCH[1]}"
      elif [[ -f "$SLOT_FILE" ]]; then
        local_slot=$(cat "$SLOT_FILE")
      else
        echo -e "${YELLOW}No running slot found for this directory. Use 'stop w2' to stop a specific slot.${NC}"
        exit 0
      fi
      stop_slot "$local_slot"
    fi
    ;;

  logs)
    TARGET="${2:-}"
    local_slot=""
    if [[ -n "$TARGET" && "$TARGET" =~ ^w([2-9])$ ]]; then
      local_slot="${BASH_REMATCH[1]}"
    elif [[ -f "$SLOT_FILE" ]]; then
      local_slot=$(cat "$SLOT_FILE")
    else
      # fallback: auto-detect what's running
      local_slot=$(detect_free_slot)
      [[ -z "$local_slot" ]] && local_slot=1
      local_slot=$(( local_slot > 1 ? local_slot - 1 : 1 ))
    fi
    tail_logs "$local_slot"
    ;;

  status)
    show_status
    ;;

  w[2-9])
    slot="${ACTION#w}"
    start_slot "$slot"
    ;;

  "")
    # No arg — auto-detect
    slot=$(detect_free_slot)
    if [[ -z "$slot" ]]; then
      echo -e "${RED}✗ All port slots taken (8030–8033). Stop another instance first.${NC}"
      exit 1
    fi
    start_slot "$slot"
    ;;

  *)
    echo "Usage: $0 [w2|w3|w4|stop|logs|status]"
    echo ""
    echo "  (no arg)       Start — auto-detect first free port slot"
    echo "  w2 / w3 / w4   Start — force a specific slot"
    echo "  stop           Stop this directory's slot (reads .dev-slot)"
    echo "  stop w2        Stop slot 2 explicitly"
    echo "  stop all       Stop all app slots (infra stays running)"
    echo "  stop infra     Stop shared infra (postgres, redis, minio)"
    echo "  logs           Tail this directory's slot logs"
    echo "  logs w2        Tail slot 2 logs"
    echo "  status         Show all running slots"
    echo ""
    echo "  Slot 1  backend 8030  frontend 5180  flower 5555"
    echo "  Slot 2  backend 8031  frontend 5181  flower 5556"
    echo "  Slot 3  backend 8032  frontend 5182  flower 5557"
    exit 1
    ;;
esac
