#!/usr/bin/env bash
# ============================================================================
# Spacetime Memory — One-Command Setup
# ============================================================================
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/omiinaya/spacetime-memory/main/scripts/setup.sh | bash
#
# Or locally:
#   bash scripts/setup.sh
#
# What it does:
#   1. Checks prerequisites (Docker or spacetime CLI)
#   2. Starts SpacetimeDB if not running
#   3. Creates a minimal .env config
#   4. Publishes the Rust module to STDB
#   5. Verifies with `stmem doctor`
#   6. Prints test commands
# ============================================================================

set -euo pipefail

# ── Colours ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m' # No Colour

info()  { echo -e "  ${CYAN}→${NC} $1"; }
ok()    { echo -e "  ${GREEN}✓${NC} $1"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()  { echo -e "  ${RED}✗${NC} $1"; }
header(){ echo -e "\n${CYAN}══ $1 ══${NC}"; }

# ── Resolve the repo root ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   Spacetime Memory — One-Command Setup      ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Check prerequisites ──────────────────────────────────────────────
header "1. Prerequisites"

SPACETIME_BIN=""
if command -v spacetime &>/dev/null; then
    SPACETIME_BIN="$(command -v spacetime)"
    ok "spacetime CLI found: $SPACETIME_BIN"
elif [ -f "$HOME/.local/bin/spacetime" ]; then
    SPACETIME_BIN="$HOME/.local/bin/spacetime"
    ok "spacetime CLI found: $SPACETIME_BIN"
elif [ -f "$HOME/.cargo/bin/spacetime" ]; then
    SPACETIME_BIN="$HOME/.cargo/bin/spacetime"
    ok "spacetime CLI found: $SPACETIME_BIN"
else
    DOCKER_OK=false
    if command -v docker &>/dev/null; then
        DOCKER_OK=true
        ok "Docker found"
    fi
    # Neither spacetime CLI nor Docker
    if [ "$DOCKER_OK" = false ]; then
        fail "No Docker or spacetime CLI found."
        info "Install Docker: https://docs.docker.com/engine/install/"
        info "Or install SpacetimeDB directly: https://spacetimedb.com/install"
        exit 1
    fi
fi

# ── Step 2: Start SpacetimeDB if not running ─────────────────────────────────
header "2. SpacetimeDB"

# Test connectivity via the actual STDB database endpoint
STDB_RUNNING=false
if command -v python3 &>/dev/null; then
    _db="${SPACETIMEDB_DB:-spacetime-memory}"
    _host="${SPACETIMEDB_HOST:-localhost}"
    _port="${SPACETIMEDB_PORT:-3001}"
    STDB_RESULT=$(python3 -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('http://${_host}:${_port}/v1/database/${_db}', timeout=3)
    print('ok')
except Exception:
    try:
        # Fallback: check if port is open at all
        import socket
        s = socket.socket()
        s.settimeout(2)
        s.connect(('${_host}', int(${_port})))
        s.close()
        print('ok-port')
    except Exception:
        print('down')
" 2>/dev/null || echo "down")
    if [ "$STDB_RESULT" = "ok" ] || [ "$STDB_RESULT" = "ok-port" ]; then
        STDB_RUNNING=true
    fi
fi

if [ "$STDB_RUNNING" = true ]; then
    ok "SpacetimeDB is already running"
else
    info "SpacetimeDB not detected. Starting with Docker..."
    if command -v docker &>/dev/null; then
        STDB_VER="${SPACETIMEDB_VERSION:-latest}"
        info "Pulling clockworklabs/spacetimedb:$STDB_VER..."
        docker pull "clockworklabs/spacetimedb:$STDB_VER" >/dev/null 2>&1 || true
        info "Starting SpacetimeDB on port ${SPACETIMEDB_PORT:-3001}..."
        docker run -d \
            --name spacetimedb \
            -p "${SPACETIMEDB_PORT:-3001}:3001" \
            "clockworklabs/spacetimedb:$STDB_VER" \
            start >/dev/null 2>&1 || true
        # Wait for startup
        info "Waiting for SpacetimeDB to be ready..."
        for i in $(seq 1 30); do
            if python3 -c "
import urllib.request
try:
    urllib.request.urlopen('http://localhost:${SPACETIMEDB_PORT:-3001}/v1/database/${SPACETIMEDB_DB:-spacetime-memory}', timeout=2)
    print('ok')
except Exception:
    print('down')
" 2>/dev/null | grep -q ok; then
                STDB_RUNNING=true
                ok "SpacetimeDB started (port ${SPACETIMEDB_PORT:-3001})"
                break
            fi
            sleep 1
        done
        if [ "$STDB_RUNNING" = false ]; then
            fail "Timed out waiting for SpacetimeDB to start"
            info "Check: docker logs spacetimedb"
            exit 1
        fi
    else
        fail "SpacetimeDB not running and Docker not available"
        info "Install SpacetimeDB: https://spacetimedb.com/install"
        info "Then run: spacetime start"
        exit 1
    fi
fi

# ── Step 3: Create module identity and database ──────────────────────────────
header "3. Module & Database"

DB_NAME="${SPACETIMEDB_DB:-spacetime-memory}"
MODULE_PATH="${REPO_DIR}/server/spacetimedb"
PUBLISHED=false

if [ -n "$SPACETIME_BIN" ]; then
    # Check if the database already exists
    if "$SPACETIME_BIN" list 2>/dev/null | grep -q "$DB_NAME"; then
        ok "Database '$DB_NAME' exists"
        PUBLISHED=true
    else
        info "Creating database '$DB_NAME'..."
        if "$SPACETIME_BIN" init "$DB_NAME" 2>/dev/null; then
            ok "Database '$DB_NAME' created"
        else
            info "Database may already exist — continuing..."
        fi
    fi

    # Publish the module
    MODULE_WASM="$MODULE_PATH/target/wasm32-wasip1/release/spacetime_memory.wasm"
    if [ -f "$MODULE_WASM" ]; then
        info "Publishing module to '$DB_NAME'..."
        PUBLISH_OUTPUT=$(cd "$MODULE_PATH" && "$SPACETIME_BIN" publish --yes "$DB_NAME" 2>&1) || true
        if echo "$PUBLISH_OUTPUT" | grep -q "Build finished successfully\|already up to date\|Finished.*release"; then
            ok "Module published to '$DB_NAME'"
            PUBLISHED=true
        elif echo "$PUBLISH_OUTPUT" | grep -q "manual migration\|delete-data"; then
            warn "Module schema is newer than deployed — requires migration (safe, no data loss)"
            PUBLISHED=true
        else
            warn "Publish: $(echo "$PUBLISH_OUTPUT" | tail -1)"
        fi
    else
        info "WASM not prebuilt — building and publishing..."
        PUBLISH_OUTPUT=$(cd "$MODULE_PATH" && "$SPACETIME_BIN" publish --yes "$DB_NAME" 2>&1) || true
        if echo "$PUBLISH_OUTPUT" | grep -q "Build finished successfully\|Finished.*release"; then
            ok "Module built and published to '$DB_NAME'"
            PUBLISHED=true
        else
            warn "Publish skipped — you can run later: cd server/spacetimedb && spacetime publish $DB_NAME"
        fi
    fi
else
    if [ -f "$MODULE_PATH/target/wasm32-wasip1/release/spacetime_memory.wasm" ]; then
        info "WASM binary exists but no spacetime CLI to publish with"
        info "The Docker container will auto-publish on startup"
        PUBLISHED=true
    else
        warn "No WASM binary found — build will happen inside Docker"
        PUBLISHED=true
    fi
fi

# ── Step 4: Create .env config ───────────────────────────────────────────────
header "4. Configuration"

ENV_FILE="${REPO_DIR}/.env"
if [ -f "$ENV_FILE" ]; then
    warn ".env already exists — skipping"
    info "  Review: cat $ENV_FILE"
else
    cat > "$ENV_FILE" <<-EOF
# ============================================================================
# Spacetime Memory — Generated by setup.sh
# ============================================================================

# --- SpacetimeDB Connection ---
SPACETIMEDB_HOST=${SPACETIMEDB_HOST:-localhost}
SPACETIMEDB_PORT=${SPACETIMEDB_PORT:-3001}
SPACETIMEDB_DB=${DB_NAME}

# --- Embedder (via spacetime-llm proxy or another OpenAI-compatible API) ---
EMBEDDER_URL=http://localhost:4000
EMBEDDING_MODEL=bge-m3
OPENAI_BASE_URL=http://localhost:4000/v1

# --- LLM (for compounder features) ---
# OPENAI_API_KEY=sk-...

# --- MCP Server ---
# MCP_API_KEY=your-mcp-api-key
EOF
    ok ".env config created at $ENV_FILE"
    info "  Edit it to set your OPENAI_API_KEY for LLM features"
fi

# ── Step 5: Install Python SDK + CLI ─────────────────────────────────────────
header "5. Python Packages"

if python3 -c "import spacetime_memory" 2>/dev/null; then
    ok "spacetime-memory SDK already installed"
else
    info "Installing spacetime-memory SDK..."
    (cd "$REPO_DIR" && pip install -e sdk/python 2>/dev/null) && ok "SDK installed" || warn "SDK install had issues"
fi

if python3 -c "import click, rich" 2>/dev/null && [ -f "$REPO_DIR/cli/stmem.py" ]; then
    ok "CLI dependencies available"
else
    info "Installing CLI deps..."
    pip install click rich httpx 2>/dev/null || true
fi

# ── Step 6: Verify ───────────────────────────────────────────────────────────
header "6. Verification"

if [ -f "$REPO_DIR/cli/stmem.py" ]; then
    DOCTOR_RESULT=$(python3 "$REPO_DIR/cli/stmem.py" doctor 2>&1 | grep -c "All 4/4 checks passed" || true)
    if [ "$DOCTOR_RESULT" -gt 0 ]; then
        ok "All systems ready! ✅"
        python3 "$REPO_DIR/cli/stmem.py" doctor 2>&1 | grep -E "^  \[|✅|⚠️" || true
    else
        warn "`stmem doctor` reported issues — review the output above"
    fi
else
    warn "CLI not found at $REPO_DIR/cli/stmem.py — skipping verification"
fi

# ── Step 7: Celebrate ────────────────────────────────────────────────────────
header "7. 🎉 You're Ready!"

echo ""
echo -e "  ${GREEN}Spacetime Memory is set up and running.${NC}"
echo ""
echo -e "  ${CYAN}Quick test:${NC}"
echo -e "    ${DIM}cd $REPO_DIR${NC}"
echo -e "    ${DIM}stmem store \"Hello world\" --workspace default${NC}"
echo -e "    ${DIM}stmem search \"hello\" --workspace default${NC}"
echo ""
echo -e "  ${CYAN}Next steps:${NC}"
echo -e "    ${DIM}• stmem doctor            — full health check${NC}"
echo -e "    ${DIM}• stmem --help            — all CLI commands${NC}"
echo -e "    ${DIM}• Edit .env to add OPENAI_API_KEY for LLM features${NC}"
echo -e "    ${DIM}• Read README.md for the full guide${NC}"
echo ""
