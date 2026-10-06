#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${LATEXY_ENV_FILE:-$PROJECT_ROOT/.env.production}"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.prod.yml"
CERT_FILE="$PROJECT_ROOT/nginx/ssl/latexy.crt"
KEY_FILE="$PROJECT_ROOT/nginx/ssl/latexy.key"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Missing $ENV_FILE" >&2
  echo "Copy .env.production.example to .env.production and replace every placeholder." >&2
  exit 1
fi

for tls_file in "$CERT_FILE" "$KEY_FILE"; do
  if [[ ! -f "$tls_file" ]]; then
    echo "ERROR: Missing TLS file $tls_file" >&2
    echo "Install a certificate and private key before exposing the stack." >&2
    exit 1
  fi
done

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

# Make the exact checkout visible to the frontend identity endpoint in the
# self-hosted image. This is a build fallback; Vercel uses its own commit env.
BUILD_VERSION="$(git -C "$PROJECT_ROOT" rev-parse --verify HEAD)"
export BUILD_VERSION

echo "==> Validating production configuration"
"${compose[@]}" config --quiet

echo "==> Building the exact application images used for migration and startup"
"${compose[@]}" build frontend backend celery-worker celery-beat flower

echo "==> Starting stateful dependencies"
"${compose[@]}" up -d --wait postgres redis minio tempo

# minio-init is intentionally one-shot, so do not include it in --wait. Run it
# only after MinIO is healthy and fail before migrations if bucket creation fails.
"${compose[@]}" run --rm --no-deps minio-init

echo "==> Applying database migrations"
"${compose[@]}" run --rm --no-deps backend alembic upgrade head

echo "==> Starting Latexy from the already-built images"
"${compose[@]}" up -d --no-build --remove-orphans

echo "Latexy is starting. Verify with:"
echo "  curl -fsS http://localhost/health"
echo "  curl -fkSs https://localhost/health"
echo "  docker compose --env-file '$ENV_FILE' -f '$COMPOSE_FILE' ps"
