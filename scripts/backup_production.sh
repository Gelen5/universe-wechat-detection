#!/bin/sh
set -eu

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
pg_dump --format=custom --no-owner --dbname="$POSTGRES_DB" --username="$POSTGRES_USER" \
  > "$BACKUP_DIR/universe-$STAMP.dump"
find "$BACKUP_DIR" -type f -name 'universe-*.dump' -mtime "+${BACKUP_RETENTION_DAYS:-14}" -delete
echo "$BACKUP_DIR/universe-$STAMP.dump"
