#!/bin/bash
# Called from cron to run daily backup
# Example crontab entry (runs daily at 2 AM):
#   0 2 * * * $HOME/spacetime-memory/scripts/backup-cron.sh <workspace_id>

set -euo pipefail

WORKSPACE_ID="${1:?Usage: $0 <workspace_id>}"
PROJECT_DIR="$HOME/spacetime-memory"
BACKUP_DIR="${PROJECT_DIR}/data/backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT_FILE="${BACKUP_DIR}/backup-${TIMESTAMP}.json"

mkdir -p "${BACKUP_DIR}"

echo "[backup-cron] Starting daily backup for workspace ${WORKSPACE_ID}"

# Activate the Python venv and run export
cd "${PROJECT_DIR}"
source sdk/python/venv/bin/activate
python scripts/backup.py export "${WORKSPACE_ID}" --output "${OUTPUT_FILE}"

echo "[backup-cron] Backup written to ${OUTPUT_FILE}"

# Keep only the last 7 backups
echo "[backup-cron] Cleaning backups older than 7 days..."
find "${BACKUP_DIR}" -name 'backup-*.json' -mtime +7 -delete

echo "[backup-cron] Done."
