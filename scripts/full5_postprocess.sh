#!/bin/bash
# full5_postprocess.sh — repair + verdict extraction for a Mem0 LoCoMo full
# resume run.
#
# INTERNAL OPERATOR TOOLING (benchmark ops). Waits for the benchmark process
# to exit, repairs any contamination-damaged questions, extracts the official
# metrics, and writes the verdict file so the existing verdict watcher can
# deliver them.
#
# All environment-specific values are configurable via env vars (see below);
# no private paths or IPs are hardcoded.
set -u

# ── Configuration (env-overridable) ─────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STMEM_PY="${STMEM_PY:-$REPO_ROOT/.venv/bin/python}"
STDB_HOST="${STDB_HOST:-127.0.0.1}"
STDB_PORT="${STDB_PORT:-3001}"
STDB_DB="${STDB_DB:-spacetime-memory-v2}"
LLM_MODEL="${LLM_MODEL:-deepseek-v4-flash-free}"
BENCH_OUT="${BENCH_OUT:-/tmp/mem0bench/full5}"
PROJECT_NAME="${PROJECT_NAME:-stmem-full5-zen}"
RUN_ID="${RUN_ID:-a2e9b6fd}"
DATASET="${DATASET:-$REPO_ROOT/data/locomo10.json}"

RESULT="${RESULT:-/tmp/mem0bench_full5.out}"
LOGFILE="${LOGFILE:-/tmp/mem0bench_full5_postprocess.log}"
RESULT_DIR="${BENCH_OUT}/predicted_${PROJECT_NAME}"

log() { echo "$(date '+%H:%M:%S') $*" >> "$LOGFILE"; }

log "postprocessor started, waiting for benchmark exit..."

# Wait for the benchmark process to fully exit (same pattern the chain uses).
while ps aux | grep -E "${PROJECT_NAME}|benchmarks.locomo.run" | grep -v grep > /dev/null 2>&1; do
    sleep 60
done
log "benchmark exited; starting repair+extraction"

# Give STDB a moment to settle, then check for contamination.
sleep 30

if [ ! -d "$RESULT_DIR" ]; then
    log "FATAL: result dir missing: $RESULT_DIR"
    exit 1
fi

CONTAM_COUNT=$(grep -l '"total_results": 0' "$RESULT_DIR"/conv*_q*.json 2>/dev/null | wc -l)
log "contaminated questions found: $CONTAM_COUNT"

if [ "$CONTAM_COUNT" -gt 0 ]; then
    log "running repair script..."
    "$STMEM_PY" \
        "$REPO_ROOT/scripts/repair_locomo_contamination.py" \
        --results-dir "$RESULT_DIR" \
        --dataset "$DATASET" \
        --project-name "$PROJECT_NAME" \
        --db "$STDB_DB" --stmem-host "$STDB_HOST" --stmem-port "$STDB_PORT" \
        --run-id "$RUN_ID" \
        --answerer-model "$LLM_MODEL" --judge-model "$LLM_MODEL" \
        --cutoff 10 20 50 200 \
        >> "$LOGFILE" 2>&1
    log "repair finished"
else
    log "no contamination, skipping repair"
fi

# Extract the official metrics from the newest results file (repaired or not).
# Prefer the REPAIRED reassembled file: repair_locomo_contamination.py writes
# locomo_results_*.json into the per-run subdir (predicted_<project>/),
# and that file carries the repair_note + re-scored questions. The parent-dir
# file is the raw harness output with contamination still scored 0. Pick the
# NEWEST across BOTH locations (the repaired one is always newer).
NEW=$(ls -t "$BENCH_OUT"/locomo_results_*.json \
           "$BENCH_OUT"/predicted_${PROJECT_NAME}/locomo_results_*.json \
        2>/dev/null | head -1)
log "newest results file: ${NEW:-NONE}"

if [ -z "$NEW" ]; then
    log "FATAL: no locomo_results_*.json found; verdict cannot be extracted"
    exit 1
fi

"$STMEM_PY" - "$NEW" > "$RESULT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("FULL OFFICIAL MEM0 LoCoMo RUN (date-anchored + per-project identity, OpenCode Zen deepseek)")
md = d.get("metadata", {})
print("answerer_model:", md.get("answerer_model"))
print("total_questions:", md.get("total_questions"))
if md.get("repair_note"):
    print("repair_note:", md.get("repair_note"))
for cutoff, m in d.get("metrics_by_cutoff", {}).items():
    o = m.get("overall", {})
    print(f"{cutoff}: {o.get('accuracy',0):.2f}% ({o.get('correct')}/{o.get('total')})")
print("MEM0_PUBLISHED=91.56")
PY

log "verdict written to $RESULT"
cat "$RESULT" >> "$LOGFILE"
