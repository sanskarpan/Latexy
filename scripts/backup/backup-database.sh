#!/usr/bin/env bash
# backup-database.sh — PostgreSQL backup script for Latexy
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/backups/database}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/latexy_backup_$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

# Parse DATABASE_URL
DB_URL="${DATABASE_URL:-}"
if [ -z "$DB_URL" ]; then
  # Try loading from backend/.env
  ENV_FILE="$(dirname "$0")/../../backend/.env"
  [ -f "$ENV_FILE" ] && source "$ENV_FILE"
  DB_URL="${DATABASE_URL:-}"
fi
if [ -z "$DB_URL" ]; then
  echo "ERROR: DATABASE_URL not set" >&2
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting database backup..."
echo "  Output: $BACKUP_FILE"

# pg_dump and gzip in one pipe
pg_dump "$DB_URL" | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup complete — $SIZE"

# Cleanup old backups
find "$BACKUP_DIR" -name "latexy_backup_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaned up backups older than ${RETENTION_DAYS} days"
