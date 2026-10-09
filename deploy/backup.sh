#!/usr/bin/env bash
# Usage: backup.sh [database] [backup_dir]
set -euo pipefail
exec python3 "$(dirname "$0")/backup.py" "$@"
