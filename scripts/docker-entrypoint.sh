#!/bin/bash
# ============================================================================
# docker-entrypoint.sh — start all Spacetime Memory services inside the container
# ============================================================================
set -e

# Directory for SpacetimeDB data
DATA_DIR="${SPACETIMEDB_DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"

# --------------------------------------------------------------------------
# 1  Start SpacetimeDB in the background
# --------------------------------------------------------------------------
echo "==> Starting SpacetimeDB (data-dir: $DATA_DIR) ..."
spacetime start \
    --listen-addr 0.0.0.0:3001 \
    --data-dir "$DATA_DIR" \
    &
SPACETIME_PID=$!

# Wait until the health endpoint responds
echo "==> Waiting for SpacetimeDB to become ready ..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:3001/ > /dev/null 2>&1; then
        echo "==> SpacetimeDB is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: SpacetimeDB failed to start within 30 seconds."
        exit 1
    fi
    sleep 1
done

# --------------------------------------------------------------------------
# 2  Publish the module (unless the database already exists)
# --------------------------------------------------------------------------
#   We use the database name from the environment, defaulting to
#   "spacetime-memory".  The module wasm is at /app/module/spacetime_memory.wasm
MODULE_NAME="${SPACETIMEDB_DB:-spacetime-memory}"

# Check if the database already exists
if ! curl -sf "http://localhost:3001/v1/database/$MODULE_NAME" > /dev/null 2>&1; then
    echo "==> Publishing module '$MODULE_NAME' ..."
    spacetime publish \
        --bin-path /app/module/spacetime_memory.wasm \
        "$MODULE_NAME" \
        --yes \
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
done

# --------------------------------------------------------------------------
# 4  Start a trivial static HTTP server for the frontend
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
# 5  Startup complete — print banner
# --------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Spacetime Memory is RUNNING                    ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  SpacetimeDB  ➜  http://localhost:3001                  ║"
echo "║  Embedder     ➜  http://localhost:9090                  ║"
echo "║  Frontend     ➜  http://localhost:5173                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# --------------------------------------------------------------------------
# 6  Trap signals and shut down gracefully
# --------------------------------------------------------------------------
cleanup() {
    echo ""
    echo "==> Shutting down all services ..."
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo "    frontend stopped."
    kill "$EMBEDDER_PID" 2>/dev/null && echo "    embedder stopped."
    kill "$SPACETIME_PID" 2>/dev/null && echo "    SpacetimeDB stopped."
    wait
    echo "==> Goodbye."
}
trap cleanup EXIT INT TERM

# Block until any child exits (keeps container alive)
wait
