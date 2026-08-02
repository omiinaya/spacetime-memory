#!/usr/bin/env bash
# Sequential benchmark runner — runs BEAM → LoCoMo → LongMemEval → GraphSearch
set -euo pipefail
cd $HOME/spacetime-memory
source .venv/bin/activate
export PYTHONPATH="scripts/benchmarks:$PYTHONPATH"
export PYTHONUNBUFFERED=1
export STDB_URL="http://127.0.0.1:3001"
export SPACETIMEDB_DB="spacetime-memory-v2"

RESULTS_DIR="benchmarks/results"
mkdir -p "$RESULTS_DIR/beam" "$RESULTS_DIR/locomo" "$RESULTS_DIR/longmemeval" "$RESULTS_DIR/graph_search"

echo "[$(date)] Starting sequential benchmark run..."
echo "[$(date)] Pipeline: STDB, Judge: deepseek/deepseek-chat"
echo ""

# 1. BEAM (all 27 scenarios)
echo "[$(date)] === BEAM ==="
python3 -u scripts/benchmarks/run_beam.py --stdb --limit 27 2>&1 | tee "$RESULTS_DIR/beam/run_$(date +%s).log"
echo "[$(date)] BEAM complete"
echo ""

# 2. LoCoMo (all 10 conversations, 1540 questions)
echo "[$(date)] === LoCoMo ==="
python3 -u scripts/benchmarks/run_locomo.py --stdb --limit 1540 2>&1 | tee "$RESULTS_DIR/locomo/run_$(date +%s).log"
echo "[$(date)] LoCoMo complete"
echo ""

# 3. LongMemEval (all 500 questions)
echo "[$(date)] === LongMemEval ==="
python3 -u scripts/benchmarks/run_longmemeval.py --stdb --limit 500 2>&1 | tee "$RESULTS_DIR/longmemeval/run_$(date +%s).log"
echo "[$(date)] LongMemEval complete"
echo ""

# 4. Graph Search P@5/R@5 (GBrain-parity eval)
echo "[$(date)] === Graph Search ==="
python3 -u scripts/benchmarks/run_graph_search_bench.py 2>&1 | tee "$RESULTS_DIR/graph_search/run_$(date +%s).log"
echo "[$(date)] Graph Search complete"
echo ""

echo "[$(date)] All benchmarks complete!"
