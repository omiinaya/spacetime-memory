#!/bin/bash
# Benchmark runner with file-based output
set -e
cd $HOME/spacetime-memory

# Kill any stale benchmark processes
pkill -f "locomo_benchmark.py" 2>/dev/null || true
sleep 1

# Export environment
export SPACETIMEDB_DB=c20076381c624767a61e93ef07b3a8f2a2f012f11d5312a479dbcecc72066e5c
export OTEL_ENABLED=false
export PYTHONUNBUFFERED=1
# API keys come from the environment (never commit them):
#   LLM_RERANK_API_KEY — primary key for the LLM reranker
#   OPENROUTER_KEY_2 / OPENROUTER_KEY_3 — fallback keys (optional)
export LLM_RERANK_API_KEY="${LLM_RERANK_API_KEY:-}"
export LLM_RERANK_ENDPOINT="${LLM_RERANK_ENDPOINT:-https://openrouter.ai/api/v1}"
export LLM_RERANK_MODEL="${LLM_RERANK_MODEL:-deepseek/deepseek-chat}"
export OPENROUTER_KEY_2="${OPENROUTER_KEY_2:-}"
export OPENROUTER_KEY_3="${OPENROUTER_KEY_3:-}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTFILE="benchmark_locomo_${TIMESTAMP}.log"
echo "Benchmark starting at $(date)" > "$OUTFILE"
echo "Logging to: $OUTFILE"

# Run with full output to both file and stderr
.venv/bin/python3 -u scripts/locomo_benchmark.py --conv 1 --quick >> "$OUTFILE" 2>&1
EXIT=$?
echo "Exit code: $EXIT" >> "$OUTFILE"
echo "Benchmark finished at $(date)" >> "$OUTFILE"
echo "Done. Exit code: $EXIT"
head -100 "$OUTFILE" 2>/dev/null
