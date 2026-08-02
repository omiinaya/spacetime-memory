#!/usr/bin/env bash
set -euo pipefail
cd $HOME/spacetime-memory
source .venv/bin/activate
export PYTHONPATH="scripts/benchmarks:$PYTHONPATH"
export PYTHONUNBUFFERED=1
exec python3 scripts/benchmarks/run_beam.py --stdb --limit "$@"
