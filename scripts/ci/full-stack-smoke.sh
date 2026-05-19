#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

BACKEND_PORT="${BACKEND_PORT:-8030}"
FRONTEND_PORT="${FRONTEND_PORT:-5180}"

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export REDIS_CACHE_URL="${REDIS_CACHE_URL:-redis://localhost:6379/1}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$REDIS_URL}"
export BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET:-sK6fP1vR9mL0dQ4xN8cT2yH7aB5uE3wJ6rZ9pC4nV1k=}"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-6f8d0f1ac54098cdd3c71f4f26bd9250d37bbf3efd1e8fc70dffc39d4ed7836a}"
export API_KEY_ENCRYPTION_KEY="${API_KEY_ENCRYPTION_KEY:-R2OlT4klI7izaWpn19Qv4qGjXvHpW446ZLxMtU8IjUo=}"
export BETTER_AUTH_URL="${BETTER_AUTH_URL:-http://localhost:${FRONTEND_PORT}}"
export FRONTEND_URL="${FRONTEND_URL:-http://localhost:${FRONTEND_PORT}}"
export NEXT_PUBLIC_APP_URL="${NEXT_PUBLIC_APP_URL:-http://localhost:${FRONTEND_PORT}}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:${BACKEND_PORT}}"
export NEXT_PUBLIC_WS_URL="${NEXT_PUBLIC_WS_URL:-ws://localhost:${BACKEND_PORT}}"
export CORS_ORIGINS="${CORS_ORIGINS:-[\"http://localhost:${FRONTEND_PORT}\",\"http://127.0.0.1:${FRONTEND_PORT}\"]}"
export ENVIRONMENT="${ENVIRONMENT:-staging}"
export BILLING_MODE="${BILLING_MODE:-disabled}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
export NEXT_TELEMETRY_DISABLED=1

backend_pid=""
backend_alembic=()
backend_uvicorn=()

if [[ -x "$BACKEND_DIR/.venv/bin/alembic" && -x "$BACKEND_DIR/.venv/bin/uvicorn" ]]; then
  backend_alembic=("$BACKEND_DIR/.venv/bin/alembic")
  backend_uvicorn=("$BACKEND_DIR/.venv/bin/uvicorn")
else
  backend_alembic=(uv run alembic)
  backend_uvicorn=(uv run uvicorn)
fi

cleanup() {
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT

echo "==> Running backend migrations"
(
  cd "$BACKEND_DIR"
  "${backend_alembic[@]}" upgrade head
)

echo "==> Starting backend on :${BACKEND_PORT}"
(
  cd "$BACKEND_DIR"
  "${backend_uvicorn[@]}" app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) &
backend_pid=$!

echo "==> Waiting for backend readiness"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null

echo "==> Running Playwright full-stack smoke"
(
  cd "$FRONTEND_DIR"
  PLAYWRIGHT_REQUIRE_BACKEND=1 \
  PLAYWRIGHT_PORT="$FRONTEND_PORT" \
  pnpm exec playwright test e2e/full-stack-smoke.spec.ts --project=chromium --workers=1
)
