#!/bin/bash
# ============================================================================
# docker-entrypoint.sh — start all Spacetime Memory services inside the container
# ============================================================================
set -euo pipefail
# Note: health check loops use || true to avoid premature exit from set -e

# Directory for SpacetimeDB data
DATA_DIR="${SPACETIMEDB_DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"

# --------------------------------------------------------------------------
# 1  Start SpacetimeDB standalone in the background
# --------------------------------------------------------------------------
echo "==> Starting SpacetimeDB standalone (data-dir: $DATA_DIR) ..."
mkdir -p "$DATA_DIR"
spacetimedb-standalone start \
    --listen-addr 0.0.0.0:3001 \
    --data-dir "$DATA_DIR" \
    --jwt-priv-key-path /app/data/id_ecdsa_pkcs8.pem \
    --jwt-pub-key-path /app/data/id_ecdsa.pub \
    &
SPACETIME_PID=$!

# Wait until the server is listening on port 3001
echo "==> Waiting for SpacetimeDB to become ready ..."
for i in $(seq 1 30); do
    if timeout 1 bash -c 'echo > /dev/tcp/localhost/3001' 2>/dev/null; then
        echo "==> SpacetimeDB is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: SpacetimeDB failed to start within 30 seconds."
        exit 1
    fi
    sleep 1
done || true  # set -e guard: loop may exit non-zero if no break

# --------------------------------------------------------------------------
# 2  Publish the module (unless the database already exists)
# --------------------------------------------------------------------------
#   We use the database name from the environment, defaulting to
#   "spacetime-memory".  The module wasm is at /app/module/spacetime_memory.wasm
MODULE_NAME="${SPACETIMEDB_DB:-spacetime-memory}"

# Check if the database already exists (POST required for SpacetimeDB v2.4)
if ! curl -sf -X POST "http://localhost:3001/v1/database/$MODULE_NAME" > /dev/null 2>&1; then
    echo "==> Publishing module '$MODULE_NAME' ..."
    spacetimedb-cli publish \
        -b /app/module/spacetime_memory.wasm \
        "$MODULE_NAME" \
        --yes --anonymous \
        2>&1 || echo "==> [WARN] Module publish exited non-zero (may already exist)."
else
    echo "==> Database '$MODULE_NAME' already published — skipping publish."
fi

# --------------------------------------------------------------------------
# 3  Start the ONNX embedder sidecar in the background
# --------------------------------------------------------------------------
echo "==> Starting embedder (model: ${EMBEDDER_MODEL_PATH:-/app/model/all-MiniLM-L6-v2.onnx}) ..."
export MODEL_PATH="${EMBEDDER_MODEL_PATH:-/app/model/all-MiniLM-L6-v2.onnx}"
embedder &
EMBEDDER_PID=$!

# Wait for the embedder to become ready
echo "==> Waiting for embedder ..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:9090/health > /dev/null 2>&1; then
        echo "==> Embedder is ready."
        break
    fi
    if [ "$i" -eq 15 ]; then
        echo "ERROR: Embedder failed to start within 15 seconds."
        exit 1
    fi
    sleep 1
done || true  # set -e guard

# --------------------------------------------------------------------------
# 4  Start the Tantivy BM25 sidecar in the background
# --------------------------------------------------------------------------
echo "==> Starting Tantivy BM25 sidecar ..."
export REINDEX_SCRIPT="/app/scripts/reindex-tantivy.py"
export SPACETIMEDB_URL="http://localhost:3001"
export SPACETIMEDB_DB="$MODULE_NAME"
tantivy-sidecar --warmup &
TANTIVY_PID=$!

# Wait for Tantivy to become ready
echo "==> Waiting for Tantivy ..."
for i in $(seq 1 10); do
    if curl -sf http://localhost:9091/health > /dev/null 2>&1; then
        echo "==> Tantivy BM25 is ready."
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "ERROR: Tantivy sidecar failed to start within 10 seconds."
        exit 1
    fi
    sleep 1
done || true  # set -e guard

# --------------------------------------------------------------------------
# 5  Start a trivial static HTTP server for the frontend
# --------------------------------------------------------------------------
if [ -f /app/frontend/index.html ]; then
    echo "==> Starting frontend on http://0.0.0.0:5173 ..."
    cd /app/frontend
    python3 -m http.server 5173 &
    FRONTEND_PID=$!
else
    echo "==> [WARN] No frontend build found at /app/frontend — skipping."
    FRONTEND_PID=
fi

# --------------------------------------------------------------------------
# 6  Startup complete — print banner
# --------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Spacetime Memory is RUNNING                    ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  SpacetimeDB  ➜  http://localhost:3001                  ║"
echo "║  Embedder     ➜  http://localhost:9090                  ║"
echo "║  Tantivy BM25 ➜  http://localhost:9091                  ║"
echo "║  Frontend     ➜  http://localhost:5173                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# --------------------------------------------------------------------------
# 7  Trap signals and shut down gracefully
# --------------------------------------------------------------------------
cleanup() {
    echo ""
    echo "==> Shutting down all services ..."
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo "    frontend stopped."
    [ -n "$TANTIVY_PID" ] && kill "$TANTIVY_PID" 2>/dev/null && echo "    Tantivy BM25 stopped."
    kill "$EMBEDDER_PID" 2>/dev/null && echo "    embedder stopped."
    kill "$SPACETIME_PID" 2>/dev/null && echo "    SpacetimeDB stopped."
    wait
    echo "==> Goodbye."
}
trap cleanup EXIT INT TERM

# Block until any child exits (keeps container alive)
wait