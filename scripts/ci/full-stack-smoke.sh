#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

BACKEND_PORT="${BACKEND_PORT:-8030}"
FRONTEND_PORT="${FRONTEND_PORT:-5180}"

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy_test}"
REDIS_PORT="${REDIS_PORT:-6380}"
export REDIS_URL="${REDIS_URL:-redis://localhost:${REDIS_PORT}/0}"
export REDIS_CACHE_URL="${REDIS_CACHE_URL:-redis://localhost:${REDIS_PORT}/1}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$REDIS_URL}"
# Validate isolation before migrations or generating per-run test-only keys.
node -e '
  const url = new URL(process.env.DATABASE_URL.replace("postgresql+asyncpg:", "postgresql:"));
  if (!["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) || !url.pathname.endsWith("_test")) {
    throw new Error("Full-stack smoke requires a loopback *_test database");
  }
'
# Never inherit persistent auth/encryption keys into this synthetic test process.
# Both freshly launched services receive these values; nothing prints or saves them.
export BETTER_AUTH_SECRET="$(node -e 'process.stdout.write(require("node:crypto").randomBytes(32).toString("hex"))')"
export JWT_SECRET_KEY="$(node -e 'process.stdout.write(require("node:crypto").randomBytes(32).toString("hex"))')"
export API_KEY_ENCRYPTION_KEY="$(node -e 'process.stdout.write(require("node:crypto").randomBytes(32).toString("base64").replace(/\+/g, "-").replace(/\//g, "_"))')"
export BETTER_AUTH_URL="${BETTER_AUTH_URL:-http://localhost:${FRONTEND_PORT}}"
export FRONTEND_URL="${FRONTEND_URL:-http://localhost:${FRONTEND_PORT}}"
export NEXT_PUBLIC_APP_URL="${NEXT_PUBLIC_APP_URL:-http://localhost:${FRONTEND_PORT}}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:${BACKEND_PORT}}"
export NEXT_PUBLIC_WS_URL="${NEXT_PUBLIC_WS_URL:-ws://localhost:${BACKEND_PORT}}"
export CORS_ORIGINS="${CORS_ORIGINS:-[\"http://localhost:${FRONTEND_PORT}\",\"http://127.0.0.1:${FRONTEND_PORT}\"]}"
# Production/staging intentionally reject credentialed loopback CORS. This
# launcher owns only isolated local services, so never inherit deployment mode.
export ENVIRONMENT="test"
# This is a local-service smoke, never a remote Modal workload. Environment
# variables take precedence over deployment settings in a developer's .env.
export DEPLOY_TARGET="local"
export BILLING_MODE="${BILLING_MODE:-disabled}"
export OPENAI_API_KEY=""
export RESEND_API_KEY=""
export NEXT_TELEMETRY_DISABLED=1

backend_pid=""
frontend_pid=""
started_backend=0
started_frontend=0
frontend_log="$(mktemp -t latexy-frontend-smoke.XXXXXX)"
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
  if [[ "$started_frontend" -eq 1 ]] && [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
    wait "$frontend_pid" 2>/dev/null || true
  fi
  if [[ "$started_backend" -eq 1 ]] && [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi
  rm -f "$frontend_log"
}

trap cleanup EXIT

if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "Refusing to reuse an existing backend; choose idle test ports." >&2
  exit 1
else
  echo "==> Running backend migrations"
  (
    cd "$BACKEND_DIR"
    "${backend_alembic[@]}" upgrade head
  )

  echo "==> Starting backend on :${BACKEND_PORT}"
  (
    cd "$BACKEND_DIR"
    "${backend_uvicorn[@]}" app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --ws-max-size 524288
  ) &
  backend_pid=$!
  started_backend=1

  echo "==> Waiting for backend readiness"
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
      break
    fi
    sleep 1
  done

  curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null
fi

if curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
  echo "Refusing to reuse an existing frontend; choose idle test ports." >&2
  exit 1
else
  echo "==> Starting frontend on :${FRONTEND_PORT}"
  (
    cd "$FRONTEND_DIR"
    pnpm dev --port "$FRONTEND_PORT"
  ) >"$frontend_log" 2>&1 &
  frontend_pid=$!
  started_frontend=1

  echo "==> Waiting for frontend readiness"
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null; then
      break
    fi
    sleep 1
  done

  if ! curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null; then
    cat "$frontend_log"
    exit 1
  fi
fi

echo "==> Running Playwright full-stack smoke"
if ! (
  cd "$FRONTEND_DIR"
  PLAYWRIGHT_REQUIRE_BACKEND=1 \
  PLAYWRIGHT_REUSE_EXISTING_SERVER=1 \
  PLAYWRIGHT_BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}" \
  PLAYWRIGHT_API_URL="http://127.0.0.1:${BACKEND_PORT}" \
  PLAYWRIGHT_PORT="$FRONTEND_PORT" \
  pnpm exec playwright test e2e/full-stack-smoke.spec.ts e2e/capability-fullstack.spec.ts --project=chromium --workers=1 --retries=0 --trace=on --reporter=line --output=test-results/full-stack
); then
  if [[ "$started_frontend" -eq 1 ]]; then
    cat "$frontend_log"
  fi
  exit 1
fi

if [[ "$started_frontend" -eq 1 ]]; then
  if grep -Eiq 'Error handling upgrade request|uncaughtException|unhandledRejection|TypeError:|ReferenceError:' "$frontend_log"; then
    echo "ERROR: frontend server emitted an unexpected exception during smoke" >&2
    cat "$frontend_log"
    exit 1
  fi
  echo "==> Frontend server log contains no unexpected exceptions"
fi
