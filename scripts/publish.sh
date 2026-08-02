#!/usr/bin/env bash
# ── Spacetime-Memory — STDB Module Publisher ──────────────────────────────
#
# A safe wrapper around `spacetime publish` that:
#   - Auto-detects the STDB server port from the running process
#   - Uses pre-built WASM (or builds if missing)
#   - NEVER deletes data (--delete-data=never) — this is a PRODUCTION database
#   - CRITICAL: Refuses to run with --delete-data flags unless FORCE_DELETE=yes is set
#
# Usage:
#   ./scripts/publish.sh                    # auto-detect, safe publish
#   ./scripts/publish.sh my-database        # publish to a different DB
#   STDB_HOST=127.0.0.1:3001 ./scripts/publish.sh  # custom host
#
# Environment variables:
#   STDB_HOST      STDB server address (default: auto-detect → localhost:3001)
#   DB_NAME        Target database name (default: spacetime-memory)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_DB="${DB_NAME:-spacetime-memory}"

# ── Safety guard ─────────────────────────────────────────────────────────
# NEVER allow delete-data in this script. Production data preservation is
# THE priority. If you really need to wipe, use FORCE_DELETE=yes AND
# manually run `spacetime publish --delete-data=always` — never via script.
if [[ -n "${DELETE_DATA:-}" ]]; then
  echo "❌ REFUSING: This script hardcodes --delete-data=never."
  echo "   The DELETE_DATA env var is blocked for safety."
  echo "   If you need to wipe the database, run the spacetime CLI directly:"
  echo "   spacetime publish --delete-data=on-conflict spacetime-memory"
  echo "   And only after confirming a backup exists."
  exit 1
fi

# ── Find the spacetime CLI ──────────────────────────────────────────────
SPACETIME_CLI=""
for cmd in spacetime spacetimedb-cli; do
  if command -v "$cmd" &>/dev/null; then
    SPACETIME_CLI="$cmd"
    break
  fi
done

if [[ -z "$SPACETIME_CLI" ]]; then
  echo "❌ spacetime CLI not found."
  exit 1
fi

# ── 1. Detect STDB host ─────────────────────────────────────────────────
detect_stdb_host() {
  if [[ -n "${STDB_HOST:-}" ]]; then
    echo "$STDB_HOST"
    return
  fi
  local STDB_PID
  STDB_PID="$(pgrep -xf '.*spacetimedb-standalone.*' 2>/dev/null | head -1 || true)"
  if [[ -n "$STDB_PID" ]] && [[ -f "/proc/$STDB_PID/cmdline" ]]; then
    local CMDLINE DETECTED_PORT
    CMDLINE="$(tr '\0' ' ' < "/proc/$STDB_PID/cmdline" 2>/dev/null || true)"
    DETECTED_PORT="$(echo "$CMDLINE" | grep -oP '--listen-addr\s+\S+:\K\d+' 2>/dev/null || true)"
    if [[ -n "$DETECTED_PORT" ]]; then
      echo "localhost:$DETECTED_PORT"
      return
    fi
  fi
  echo "localhost:3001"
}

STDB_HOST="$(detect_stdb_host)"
DB_NAME="${1:-$DEFAULT_DB}"

echo "🔍 Detected STDB server: http://$STDB_HOST"
echo "📦 Target database:      $DB_NAME"

# ── 2. Find or build WASM ───────────────────────────────────────────────
# Prefer the NEWEST of the two wasm artifacts. The .opt.wasm can be a
# leftover from an earlier `wasm-opt` pass and silently publish stale code
# if it's older than the plain release build.
WASM_OPT="${SCRIPT_DIR}/server/spacetimedb/target/wasm32-unknown-unknown/release/spacetime_memory.opt.wasm"
WASM_PLAIN="${SCRIPT_DIR}/server/spacetimedb/target/wasm32-unknown-unknown/release/spacetime_memory.wasm"
if [[ -f "$WASM_OPT" && -f "$WASM_PLAIN" ]]; then
  if [[ "$WASM_PLAIN" -nt "$WASM_OPT" ]]; then
    WASM_PATH="$WASM_PLAIN"
  else
    WASM_PATH="$WASM_OPT"
  fi
elif [[ -f "$WASM_PLAIN" ]]; then
  WASM_PATH="$WASM_PLAIN"
elif [[ -f "$WASM_OPT" ]]; then
  WASM_PATH="$WASM_OPT"
else
  WASM_PATH="$WASM_OPT"
fi

if [[ ! -f "$WASM_PATH" ]]; then
  echo "🔧 Building WASM module..."

  # Clean stale NFS .nfs* handles that can cause SIGKILL/SIGBUS during build
  # on NFS-backed filesystems (observed on Proxmox NFS exports)
  STALE_TARGET="${SCRIPT_DIR}/server/spacetimedb/target"
  if [[ -d "$STALE_TARGET" ]]; then
    find "$STALE_TARGET" -name '.nfs*' -delete 2>/dev/null || true
  fi

  # Build from within the project directory so .cargo/config.toml (with
  # codegen-units=1024, opt-level=0 for wasm32) is picked up. Building via
  # --manifest-path from the repo root may miss these settings.
  cd "${SCRIPT_DIR}/server/spacetimedb" && \
    cargo build --target wasm32-unknown-unknown --release -j "$(nproc)" 2>&1 | tail -5
  WASM_PATH="${SCRIPT_DIR}/server/spacetimedb/target/wasm32-unknown-unknown/release/spacetime_memory.wasm"
fi

if [[ ! -f "$WASM_PATH" ]]; then
  echo "❌ WASM not found at $WASM_PATH"
  exit 1
fi

WASM_SIZE="$(du -h "$WASM_PATH" | cut -f1)"
echo "📎 WASM binary:          $WASM_PATH ($WASM_SIZE)"

# ── 3. Publish (NEVER delete data) ───────────────────────────────────────
echo "🚀 Publishing (data preserved — --delete-data=never)..."
$SPACETIME_CLI publish \
  "--server=http://${STDB_HOST}" \
  --delete-data=never \
  --yes \
  -b "$WASM_PATH" \
  "$DB_NAME"

echo "✅ Published '$DB_NAME' to $STDB_HOST"
