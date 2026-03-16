#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# worktree-up.sh — Start/stop Docker services for a specific worktree slot
#
# Usage:
#   ./scripts/worktree-up.sh w2        # start slot 2 — backend 8031, frontend 5181
#   ./scripts/worktree-up.sh w3        # start slot 3 — backend 8032, frontend 5182
#   ./scripts/worktree-up.sh w4        # start slot 4 — backend 8033, frontend 5183
#   ./scripts/worktree-up.sh stop w2   # stop slot 2
#   ./scripts/worktree-up.sh stop w3   # stop slot 3
#   ./scripts/worktree-up.sh stop      # stop slot 1 (default)
#   ./scripts/worktree-up.sh stop all  # stop ALL slots + shared infra
#
# Without arguments (or from main worktree) slot 1 is used (default ports).
#
# Shared infra (postgres, redis, minio) runs once — only app-layer containers
# (backend, worker, beat, frontend, flower) are duplicated per slot.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

parse_slot() {
  local arg="${1:-}"
  if [[ -z "$arg" ]]; then
    echo 1
  elif [[ "$arg" =~ ^w([2-9])$ ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo ""
  fi
}

slot_info() {
  local slot="$1"
  BACKEND_PORT=$((8029 + slot))
  FRONTEND_PORT=$((5179 + slot))
  FLOWER_PORT=$((5554 + slot))
  PROJECT_NAME="latexy-w${slot}"
  if [[ "$slot" -eq 1 ]]; then
    PROJECT_NAME="latexy"
  fi
}

print_banner() {
  local slot="$1"
  slot_info "$slot"
  echo "┌─────────────────────────────────────────┐"
  echo "│  Latexy worktree — slot ${slot}               │"
  echo "├─────────────────────────────────────────┤"
  printf "│  Backend:  http://localhost:%-13s│\n" "${BACKEND_PORT}"
  printf "│  Frontend: http://localhost:%-13s│\n" "${FRONTEND_PORT}"
  printf "│  Flower:   http://localhost:%-13s│\n" "${FLOWER_PORT}"
  echo "│  Project:  ${PROJECT_NAME}$(printf '%*s' $((28 - ${#PROJECT_NAME})) '')│"
  echo "└─────────────────────────────────────────┘"
}

stop_slot() {
  local slot="$1"
  slot_info "$slot"
  echo -e "${YELLOW}→ Stopping slot ${slot} (${PROJECT_NAME})...${NC}"
  cd "$PROJECT_ROOT"
  SLOT=$slot \
  BACKEND_PORT=$BACKEND_PORT \
  FRONTEND_PORT=$FRONTEND_PORT \
  FLOWER_PORT=$FLOWER_PORT \
    docker compose -p "$PROJECT_NAME" down --remove-orphans 2>&1 | grep -v "obsolete" || true
  echo -e "${GREEN}✓ Slot ${slot} stopped.${NC}"
}

stop_all() {
  echo -e "${YELLOW}→ Stopping ALL slots + shared infra...${NC}"
  cd "$PROJECT_ROOT"
  for s in 1 2 3 4; do
    local pname="latexy-w${s}"
    [[ "$s" -eq 1 ]] && pname="latexy"
    docker compose -p "$pname" down --remove-orphans 2>&1 | grep -v "obsolete" || true
  done
  echo -e "${GREEN}✓ Everything stopped.${NC}"
}

start_slot() {
  local slot="$1"
  slot_info "$slot"
  print_banner "$slot"

  # ── Ensure shared infra is running ──────────────────────────────────────
  echo ""
  echo -e "${CYAN}→ Ensuring shared infra (postgres, redis, minio) is running...${NC}"
  cd "$PROJECT_ROOT"

  docker compose -p latexy up -d postgres redis minio minio-init 2>&1 | grep -v "obsolete" || true

  # Wait for infra health
  echo -e "${CYAN}→ Waiting for postgres & redis to be healthy...${NC}"
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

  # ── Start app-layer containers for this slot ────────────────────────────
  echo ""
  echo -e "${CYAN}→ Starting app containers for slot ${slot}...${NC}"

  SLOT=$slot \
  BACKEND_PORT=$BACKEND_PORT \
  FRONTEND_PORT=$FRONTEND_PORT \
  FLOWER_PORT=$FLOWER_PORT \
    docker compose -p "$PROJECT_NAME" up -d backend worker beat frontend flower

  echo ""
  echo -e "${GREEN}✓ Slot ${slot} is up. Happy hacking!${NC}"
  echo ""
  echo "  Logs:  docker compose -p ${PROJECT_NAME} logs -f backend worker frontend"
  echo "  Stop:  ./scripts/worktree-up.sh stop${slot:+ w${slot}}"
}

# ── Main ──────────────────────────────────────────────────────────────────────
ACTION="${1:-}"

if [[ "$ACTION" == "stop" ]]; then
  TARGET="${2:-}"
  if [[ "$TARGET" == "all" ]]; then
    stop_all
  else
    SLOT=$(parse_slot "$TARGET")
    if [[ -z "$SLOT" ]]; then
      echo "Usage: $0 stop [w2|w3|w4|all]"
      echo ""
      echo "  stop        Stop slot 1 (default)"
      echo "  stop w2     Stop slot 2"
      echo "  stop w3     Stop slot 3"
      echo "  stop all    Stop ALL slots + shared infra"
      exit 1
    fi
    stop_slot "$SLOT"
  fi
elif [[ "$ACTION" == "logs" ]]; then
  TARGET="${2:-}"
  SLOT=$(parse_slot "$TARGET")
  if [[ -z "$SLOT" ]]; then
    echo "Usage: $0 logs [w2|w3|w4]"
    exit 1
  fi
  slot_info "$SLOT"
  echo -e "${CYAN}→ Tailing logs for slot ${SLOT} (${PROJECT_NAME})...${NC}"
  cd "$PROJECT_ROOT"
  SLOT=$SLOT \
  BACKEND_PORT=$BACKEND_PORT \
  FRONTEND_PORT=$FRONTEND_PORT \
  FLOWER_PORT=$FLOWER_PORT \
    docker compose -p "$PROJECT_NAME" logs -f backend worker frontend
else
  SLOT=$(parse_slot "$ACTION")
  if [[ -z "$SLOT" ]]; then
    echo "Usage: $0 [w2|w3|w4|stop|logs]"
    echo ""
    echo "  (no arg)    Start slot 1 (default ports: backend 8030, frontend 5180)"
    echo "  w2          Start slot 2 (backend 8031, frontend 5181, flower 5556)"
    echo "  w3          Start slot 3 (backend 8032, frontend 5182, flower 5557)"
    echo "  w4          Start slot 4 (backend 8033, frontend 5183, flower 5558)"
    echo "  stop [w#]   Stop a slot (or 'stop all' for everything)"
    echo "  logs [w#]   Tail logs for a slot"
    exit 1
  fi
  start_slot "$SLOT"
fi
