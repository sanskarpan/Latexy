#!/usr/bin/env bash
# Synthetic authentication/policy storage; actual registered HTTP router/gates.
# No model provider, deployment or live database is used by this fixture.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"
PORT=${D14_HTTP_FIXTURE_PORT:-18073}
PYTHON=${D14_TEST_PYTHON:-python}
LOG=$(mktemp /tmp/d14-http-fixture.XXXXXX.log)
D14_BROWSER_FIXTURE=1 "$PYTHON" -m uvicorn test.d14_browser_fixture:app \
  --app-dir backend --host 127.0.0.1 --port "$PORT" --no-proxy-headers > "$LOG" 2>&1 &
FIXTURE=$!
trap 'kill "$FIXTURE" 2>/dev/null || true; wait "$FIXTURE" 2>/dev/null || true' EXIT
READY=false
for _ in $(seq 1 100); do
  if curl --silent --fail "http://127.0.0.1:$PORT/__test/health" >/dev/null; then READY=true; break; fi
  if ! kill -0 "$FIXTURE" 2>/dev/null; then cat "$LOG"; exit 1; fi
  sleep .2
done
if [ "$READY" != true ]; then cat "$LOG"; exit 1; fi
D14_HTTP_BACKEND_URL="http://127.0.0.1:$PORT" pnpm --dir frontend exec playwright test \
  --config=playwright.d14-http.config.ts --workers=1 --retries=0
