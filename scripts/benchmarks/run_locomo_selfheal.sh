#!/usr/bin/env bash
# Self-healing LoCoMo runner — restarts run_locomo.py --resume on any crash
# (transient STDB 500s, proxy hiccups) until all questions are judged.
# Checkpoint/resume means each restart skips already-completed questions.
set -o pipefail
cd $HOME/spacetime-memory
source .venv/bin/activate
export PYTHONPATH="scripts/benchmarks:${PYTHONPATH:-}"
export PYTHONUNBUFFERED=1
export STDB_URL="http://127.0.0.1:3001"
export SPACETIMEDB_DB="spacetime-memory-v2"

WORKSPACE="2cb2b1b817ab46df83e605578266519d"
MAX_RESTARTS=50
attempt=0

while [ $attempt -lt $MAX_RESTARTS ]; do
  attempt=$((attempt+1))
  echo "[$(date)] Attempt $attempt — resuming LoCoMo (workspace $WORKSPACE)..."
  python3 -u scripts/benchmarks/run_locomo.py --stdb \
    --workspace-id "$WORKSPACE" --resume --skip-ingest 2>&1 | tee -a /tmp/locomo_selfheal.log
  exit_code=${PIPESTATUS[0]}
  echo "[$(date)] Attempt $attempt exited with code $exit_code"

  # Count completed questions in checkpoint
  done=$(python3 -c "
import json
try:
    cp = json.load(open('benchmarks/results/locomo/locomo_checkpoint_${WORKSPACE}.json'))
    print(len(cp.get('results', [])))
except Exception:
    print('0')
" 2>/dev/null)
  echo "[$(date)] Checkpoint: $done questions judged"

  if [ "$exit_code" -eq 0 ]; then
    echo "[$(date)] Run completed cleanly — ALL DONE ($done questions)."
    exit 0
  fi

  # If no progress since last attempt (stuck), bail after a few tries
  if [ $attempt -ge $MAX_RESTARTS ]; then
    echo "[$(date)] Max restarts reached ($MAX_RESTARTS). Final checkpoint: $done."
    exit 1
  fi

  echo "[$(date)] Restarting in 20s..."
  sleep 20
done
