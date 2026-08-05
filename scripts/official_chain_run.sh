#!/bin/bash
# SEQUENTIAL OFFICIAL-HARNESS CHAIN for Spacetime-Memory.
# Runs after the Mem0 LoCoMo full (stmem-full-zen-dated) finishes.
# Order: Zep LoCoMo -> Mem0 LongMemEval -> Mem0 BEAM.
# All LLM via our OpenCode Zen chain (:4004 -> :4002, x-api-key: public).
# No OpenRouter (cardinal rule #2). Gateway-immune via no_agent cron.
set -e

MASTER=/tmp/official_chain.out
LOGFILE=/tmp/official_chain.log
echo "Chain start $(date)" > "$LOGFILE"

# Wait for Mem0 LoCoMo full run (full5) to finish first
echo "Waiting for Mem0 LoCoMo official run..." >> "$LOGFILE"
while ps aux | grep -E "stmem-full5-zen|benchmarks.locomo.run" | grep -v grep > /dev/null 2>&1; do
    sleep 120
done
echo "Mem0 LoCoMo done at $(date)" >> "$LOGFILE"

# Gate: wait for the postprocess daemon to finish repair + write the verdict
# file. Both this chain and the postprocess wake when the benchmark exits; if
# we started Zep while the postprocess is still repairing contaminated
# questions (which also uses STDB + the LLM chain), we'd run two STDB/LLM
# workloads concurrently — violating the sequential benchmark rule. So wait
# for /tmp/mem0bench_full5.out to appear AND be stable (>90s old, no growth).
VERDICT=/tmp/mem0bench_full5.out
echo "Waiting for postprocess verdict ($VERDICT)..." >> "$LOGFILE"
wait_verdict() {
    for i in $(seq 1 120); do
        if [ -f "$VERDICT" ]; then
            # stable = mtime at least 90s in the past
            age=$(( $(date +%s) - $(stat -c %Y "$VERDICT") ))
            if [ "$age" -ge 90 ]; then
                return 0
            fi
        fi
        sleep 90
    done
    return 1
}
if wait_verdict; then
    echo "Postprocess verdict present and stable at $(date)" >> "$LOGFILE"
else
    echo "WARNING: postprocess verdict never appeared after 3h; continuing anyway" >> "$LOGFILE"
fi
sleep 30

# ── 1. ZEP OFFICIAL LOCOMO ──────────────────────────────────────────────
echo "=== ZEP OFFICIAL LOCOMO ($(date)) ===" >> "$LOGFILE"
cd /home/hindsight/zep/benchmarks/locomo
PREFIX="stmem-chain-$(date +%Y%m%d%H%M%S)"
# IMPORTANT: do NOT delete the identity token — the Zep shim persists its
# peer identity to /tmp/zep_harness_identity.token and reuses it across
# ingest/eval processes. Deleting it forces a NEW anonymous peer, which has
# no owner access to workspaces created by the previous run's peer → every
# graph.add fails with "Access denied ... private workspace". Keeping the
# token makes the same peer own all workspaces for the whole chain.
# A timestamped prefix also guarantees a FRESH workspace per chain run —
# stale private workspaces from earlier runs (owned by lost peers) never
# collide with the current run.
timeout 10800 env \
    OTEL_ENABLED=false \
    OPENAI_API_KEY=dummy-key OPENAI_BASE_URL=http://localhost:4004/v1 \
    ZEP_API_KEY=dummy STDB_DB=spacetime-memory-v2 \
    EMBEDDER_URL=http://localhost:9093/v1 STDB_TIMEOUT=300 \
    /home/hindsight/spacetime-memory/.venv/bin/python -m benchmark \
        --ingest --config benchmark_config_stmem.yaml --prefix "$PREFIX" \
    >> "$LOGFILE" 2>&1
echo "Zep ingest done $(date)" >> "$LOGFILE"
timeout 10800 env \
    OTEL_ENABLED=false \
    OPENAI_API_KEY=dummy-key OPENAI_BASE_URL=http://localhost:4004/v1 \
    ZEP_API_KEY=dummy STDB_DB=spacetime-memory-v2 \
    EMBEDDER_URL=http://localhost:9093/v1 STDB_TIMEOUT=300 \
    /home/hindsight/spacetime-memory/.venv/bin/python -m benchmark \
        --eval --config benchmark_config_stmem.yaml --prefix "$PREFIX" --num-runs 1 \
    >> "$LOGFILE" 2>&1
echo "Zep eval done $(date)" >> "$LOGFILE"
NEWEST=$(ls -t /home/hindsight/zep/benchmarks/locomo/experiments/run_*/results.json /home/hindsight/zep/benchmarks/locomo/experiments/experiment_*/experiment_summary.json 2>/dev/null | head -1)
echo "ZEP_RESULT_FILE=$NEWEST" >> "$MASTER"
if [ -n "$NEWEST" ]; then
    /home/hindsight/spacetime-memory/.venv/bin/python3 - "$NEWEST" >> "$MASTER" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
am = d.get("aggregated_metrics", {}) or {}
acc = am.get("accuracy", {})
# run_*/results.json uses metrics.accuracy (scalar), experiment_*/ uses
# aggregated_metrics.accuracy.mean — accept both.
if acc:
    v = acc.get("mean")
    print("ZEP OFFICIAL LOCOMO (Zep harness, our Zen chain adapter)")
    print(f"  accuracy.mean: {v*100:.2f}%  (median {acc.get('median', 0)*100:.2f}%)")
    m = d.get("config", {}).get("models", {})
    print(f"  config: {m.get('response_model')}")
else:
    m = d.get("metrics", {})
    v = m.get("accuracy")
    print("ZEP OFFICIAL LOCOMO (Zep harness, our Zen chain adapter)")
    print(f"  accuracy: {v*100 if v is not None else 0:.2f}%  ({m.get('correct_count',0)}/{m.get('total_count',0)})")
    print(f"  completeness_insufficient: {m.get('completeness_insufficient_rate', 0)*100:.1f}%")
    print(f"  config: deepseek-v4-flash-free")
print("ZEP_PUBLISHED_LOCOMO=69.6 (gpt-4o-mini)")
PY
fi

# ── 2. MEM0 OFFICIAL LONGMEMEVAL ────────────────────────────────────────
echo "=== MEM0 OFFICIAL LONGMEMEVAL ($(date)) ===" >> "$LOGFILE"
cd /home/hindsight/mem0/evaluation
timeout 172800 env \
    OTEL_ENABLED=false \
    LLM_BASE_URL=http://localhost:4004/v1 OPENAI_API_KEY=dummy-key \
    STDB_EMBEDDER_URL=http://localhost:9093/v1 \
    PYTHONUNBUFFERED=1 \
    /home/hindsight/spacetime-memory/.venv/bin/python -m benchmarks.longmemeval.run \
        --project-name stmem-chain-lme \
        --backend stmem \
        --stmem-db spacetime-memory-v2 \
        --stmem-host 192.168.1.10 --stmem-port 3001 \
        --answerer-model deepseek-v4-flash-free \
        --judge-model deepseek-v4-flash-free \
        --top-k 200 --max-workers 10 \
        --output-dir /tmp/mem0bench/lme-chain \
        --dataset-path /home/hindsight/spacetime-memory/data/longmemeval_s.json \
        --all-questions \
    >> "$LOGFILE" 2>&1
echo "LongMemEval done $(date)" >> "$LOGFILE"
LME=$(ls -t /tmp/mem0bench/lme-chain/longmemeval_results_*.json 2>/dev/null | head -1)
echo "LONGMEMEVAL_RESULT_FILE=$LME" >> "$MASTER"
if [ -n "$LME" ]; then
    /home/hindsight/spacetime-memory/.venv/bin/python3 - "$LME" >> "$MASTER" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("LONGMEMEVAL OFFICIAL (Mem0 harness, deepseek via our Zen chain)")
md = d.get("metadata", {})
print(f"  total_questions: {md.get('total_questions')}")
mbc = d.get("metrics_by_cutoff", {})
for cutoff, m in mbc.items():
    o = m.get("overall", {})
    print(f"  {cutoff}: {o.get('accuracy', 0):.2f}% ({o.get('correct')}/{o.get('total')})")
print("MEM0_PUBLISHED_LONGMEMEVAL=94.4 / Mnemosyne 98.9 / Honcho 90.4 / Hindsight 91.4")
PY
fi

# ── 3. MEM0 OFFICIAL BEAM ───────────────────────────────────────────────
echo "=== MEM0 OFFICIAL BEAM ($(date)) ===" >> "$LOGFILE"
timeout 86400 env \
    OTEL_ENABLED=false \
    LLM_BASE_URL=http://localhost:4004/v1 OPENAI_API_KEY=dummy-key \
    STDB_EMBEDDER_URL=http://localhost:9093/v1 \
    PYTHONUNBUFFERED=1 \
    /home/hindsight/spacetime-memory/.venv/bin/python -m benchmarks.beam.run \
        --project-name stmem-chain-beam \
        --backend stmem \
        --stmem-db spacetime-memory-v2 \
        --stmem-host 192.168.1.10 --stmem-port 3001 \
        --answerer-model deepseek-v4-flash-free \
        --judge-model deepseek-v4-flash-free \
        --chat-sizes 100K \
        --dataset-cache-dir /home/hindsight/mem0/evaluation/datasets/beam \
        --output-dir /tmp/mem0bench/beam-chain \
    >> "$LOGFILE" 2>&1
echo "BEAM done $(date)" >> "$LOGFILE"
BEAM=$(ls -t /tmp/mem0bench/beam-chain/beam_results_*.json 2>/dev/null | head -1)
echo "BEAM_RESULT_FILE=$BEAM" >> "$MASTER"
if [ -n "$BEAM" ]; then
    /home/hindsight/spacetime-memory/.venv/bin/python3 - "$BEAM" >> "$MASTER" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("BEAM OFFICIAL (Mem0 harness, deepseek judge via our Zen chain)")
md = d.get("metadata", {})
print(f"  chat_sizes: {md.get('chat_sizes')}")
mbc = d.get("metrics_by_cutoff", {})
for cutoff, m in mbc.items():
    o = m.get("overall", {})
    print(f"  {cutoff}: {o.get('accuracy', 0):.2f}% ({o.get('correct')}/{o.get('total')})")
print("MEM0_PUBLISHED_BEAM=70.14 (1M) / Mnemosyne 65.2 (100K) / Hindsight 73.4 (100K) / Honcho 63.0 (100K)")
PY
fi

echo "CHAIN COMPLETE $(date)" >> "$MASTER"

# Deliver the full chain summary to the Discord thread via REST (bypasses the
# stuck cron ticker; daemonized so it survives the gateway timeout).
THREAD_ID="1512680047117467740"
# token lives in ~/.hermes/.env or ~/.hermes/config.yaml
TOKEN=$(grep -hoE "DISCORD_BOT_TOKEN=*[A-Za-z0-9_.\-]{20,}" ~/.hermes/.env 2>/dev/null | head -1 | sed -E 's/DISCORD_BOT_TOKEN=*//')
if [ -z "$TOKEN" ]; then
    TOKEN=$(grep -oE "DISCORD_BOT_TOKEN[:=] *[\"']?[A-Za-z0-9_.\-]{20,}" ~/.hermes/config.yaml 2>/dev/null | head -1 | sed -E 's/.*[:=] *[\"'\'']?//')
fi
if [ -n "$TOKEN" ]; then
    python3 - "$MASTER" "$THREAD_ID" "$TOKEN" <<'PY'
import json, sys, urllib.request
master, thread, token = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    body = open(master).read().strip()
except OSError:
    body = "chain master missing"
msg = "**Official Harness Chain Results**\n```\n" + body + "\n```"
data = json.dumps({"content": msg}).encode()
req = urllib.request.Request(
    f"https://discord.com/api/v10/channels/{thread}/messages",
    data=data, method="POST",
    headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
             "User-Agent": "DiscordBot (hermes-agent, 1.0)"},
)
with urllib.request.urlopen(req, timeout=20) as r:
    print(f"delivered chain results, status={r.status}")
PY
fi
cat "$MASTER"