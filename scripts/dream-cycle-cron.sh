#!/usr/bin/env bash
set -euo pipefail

# ── Dream Cycle Cron Wrapper ────────────────────────────────────────
# Runs the dream cycle enrichment pass with proxy-based LLM synthesis.
# Designed for no_agent cron execution.
# ────────────────────────────────────────────────────────────────────

export PATH="/home/user/.local/share/hermes-cli-tools-venv/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

cd /home/user/spacetime-memory

export OPENAI_REDACTED
export OPENAI_BASE_URL="http://localhost:4000/v1"
export LLM_MODEL="oc-deepseek-v4-flash"

# Output header
echo "🌙 Dream Cycle — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Run the dream cycle for the last 1 day
python3 scripts/dream_cycle.py --days 1 2>&1

# Capture exit code
rc=$?
echo ""
if [ $rc -eq 0 ]; then
    echo "✅ Dream cycle completed successfully"
else
    echo "❌ Dream cycle failed (exit code: $rc)"
fi

exit $rc
