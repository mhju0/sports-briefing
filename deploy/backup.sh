#!/usr/bin/env bash
# Online SQLite backup with integrity check and count-based retention.
# Usage: backup.sh [database] [backup_dir]
set -euo pipefail

db="${1:-${SPORTS_BRIEFING_DATABASE:?SPORTS_BRIEFING_DATABASE is not set}}"
dest="${2:-$(dirname "$db")/backups}"
keep="${SPORTS_BRIEFING_BACKUP_KEEP:-14}"

if [[ ! -f "$db" ]]; then
  # Public mode writes nothing, so a missing database is expected until ingestion is enabled.
  echo "no database at $db; nothing to back up"
  exit 0
fi

umask 027
mkdir -p "$dest"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
partial="$dest/.sports_briefing-$stamp.partial"
final="$dest/sports_briefing-$stamp.sqlite3"
trap 'rm -f "$partial"' EXIT

# SQLite's online backup API gives a consistent copy even while the app is reading or writing.
sqlite3 "$db" ".backup '$partial'"
check="$(sqlite3 "$partial" 'PRAGMA integrity_check;')"
if [[ "$check" != "ok" ]]; then
  echo "backup integrity check failed: $check" >&2
  exit 1
fi
mv "$partial" "$final"
echo "backup written: $final"

# Timestamped names sort chronologically; keep the newest $keep.
find "$dest" -maxdepth 1 -name 'sports_briefing-*.sqlite3' | sort -r | tail -n +"$((keep + 1))" |
  while IFS= read -r old; do
    rm -f -- "$old"
    echo "removed old backup: $old"
  done
