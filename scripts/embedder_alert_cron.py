#!/usr/bin/env python3
"""Embedder alert watchdog — push alert to STDB when embedder is degraded.

Checks the embedder /health endpoint and pushes a ``push_embedder_alert``
reducer call to SpacetimeDB if the embedder is unreachable or returning
errors. Designed to be run as a cron job (every 5-15 minutes) as a
fallback for when the SDK is not actively running.

Usage:
    python3 scripts/embedder_alert_cron.py

Env:
    EMBEDDER_URL        (default: http://127.0.0.1:4000)
    STMEM_EMBEDDER_ALERT_THRESHOLD  (default: 3 — consecutive failures)
    SPACETIMEDB_HOST    (default: localhost)
    SPACETIMEDB_PORT    (default: 3001)
    SPACETIMEDB_DB      (default: auto-detect)
    SPACETIMEDB_TOKEN   (default: read from ~/.config/spacetime/cli.toml)
    STMEM_ALERT_STATE_FILE  (default: /tmp/embedder_alert_state.json)

Exit codes:
    0 — healthy or alert pushed successfully
    1 — error (connection, state, etc.)
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx

EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://127.0.0.1:4000")
THRESHOLD = int(os.environ.get("STMEM_EMBEDDER_ALERT_THRESHOLD", "3"))
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
STATE_FILE = os.environ.get("STMEM_ALERT_STATE_FILE", "/tmp/embedder_alert_state.json")

# Read token from env, cli.toml, or default path
TOKEN = os.environ.get("SPACETIMEDB_TOKEN")
if not TOKEN:
    _cli_toml = os.path.expanduser("~/.config/spacetime/cli.toml")
    if os.path.isfile(_cli_toml):
        try:
            import tomllib
            with open(_cli_toml, "rb") as _f:
                _cfg = tomllib.load(_f)
            TOKEN = _cfg.get("spacetimedb_token", "")
        except (ImportError, Exception):
            pass

_headers: dict[str, str] = {"Content-Type": "application/json"}
if TOKEN:
    _headers["Authorization"] = f"Bearer {TOKEN}"

_http = httpx.Client(timeout=30)

CALL_URL = f"http://{HOST}:{PORT}/v1/database/{DB}/call"


# ── State persistence ────────────────────────────────────────────────


def _load_state() -> dict:
    """Load alert state from STATE_FILE (consecutive failures, alert flags)."""
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "consecutive_failures": 0,
        "total_calls": 0,
        "total_errors": 0,
        "alerted": False,
        "degraded": False,
        "last_update_ts": 0.0,
    }


def _save_state(state: dict) -> None:
    """Persist alert state to STATE_FILE."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except OSError as exc:
        print(f"  Warning: could not write state file: {exc}", file=sys.stderr)


# ── Checks ────────────────────────────────────────────────────────────


def _check_health() -> dict:
    """Fetch the embedder /health endpoint.

    Returns a dict with at least ``{"reachable": bool}``. On success
    includes all fields from the embedder's health JSON.
    """
    try:
        resp = _http.get(f"{EMBEDDER_URL}/health", timeout=10)
        if resp.status_code == 200:
            status = resp.json()
            status["reachable"] = True
            return status
        return {"reachable": True, "status": "error", "code": resp.status_code}
    except httpx.ConnectError:
        return {"reachable": False, "status": "unreachable"}
    except httpx.TimeoutException:
        return {"reachable": False, "status": "timeout"}
    except Exception as exc:
        return {"reachable": False, "status": "error", "message": str(exc)}


# ── Alert push ────────────────────────────────────────────────────────


def _push_alert(
    severity: int,
    message: str,
    consecutive: int,
    calls: int,
    errors: int,
    degraded: bool,
    recovery: bool,
    reachable: bool,
) -> bool:
    """Call the ``push_embedder_alert`` STDB reducer.

    Returns True if the call succeeded (HTTP 2xx).
    """
    error_rate_pct = 0.0
    if calls > 0:
        error_rate_pct = round(errors / calls * 100, 2)

    args = [
        severity,
        message,
        consecutive,
        calls,
        errors,
        error_rate_pct,
        degraded,
        recovery,
        reachable,
        EMBEDDER_URL,
    ]

    try:
        resp = _http.post(
            f"{CALL_URL}/push_embedder_alert",
            content=json.dumps(args),
            headers=_headers,
        )
        if resp.status_code >= 400:
            print(
                f"  Error ({resp.status_code}): {resp.text[:200]}",
                file=sys.stderr,
            )
            return False
        return True
    except httpx.ConnectError:
        print(
            f"  Connection refused — STDB at {HOST}:{PORT}",
            file=sys.stderr,
        )
        return False
    except Exception as exc:
        print(f"  Unexpected error: {exc}", file=sys.stderr)
        return False


# ── Main logic ────────────────────────────────────────────────────────


def run() -> int:
    """Check embedder health and push alert if degraded.

    State machine:
    - First crossing of threshold → push CRITICAL alert, set alerted=True
    - Subsequent failures → no duplicate alert (dedup)
    - Recovery → push RECOVERY alert, reset state
    """
    state = _load_state()
    state["total_calls"] += 1

    health = _check_health()
    reachable = health.get("reachable", False)

    if reachable:
        # Embedder is reachable — if we were degraded, push recovery
        if state.get("degraded"):
            state["degraded"] = False
            state["alerted"] = False
            state["consecutive_failures"] = 0
            ok = _push_alert(
                severity=0,  # RECOVERY
                message=f"Embedder has recovered — /health is responsive at {EMBEDDER_URL}",
                consecutive=0,
                calls=state["total_calls"],
                errors=state["total_errors"],
                degraded=False,
                recovery=True,
                reachable=True,
            )
            if ok:
                print(
                    f"[{time.strftime('%H:%M:%S')}] "
                    f"Embedder recovered (total_calls={state['total_calls']})"
                )
            state["total_errors"] = 0
            _save_state(state)
            return 0

        # Healthy — reset counters
        if state.get("consecutive_failures", 0) > 0:
            state["consecutive_failures"] = 0
            state["alerted"] = False
        _save_state(state)
        return 0

    # Embedder is NOT reachable
    state["total_errors"] += 1
    state["consecutive_failures"] += 1

    if state["consecutive_failures"] >= THRESHOLD and not state.get("alerted"):
        # First crossing of threshold — push alert
        state["alerted"] = True
        state["degraded"] = True
        ok = _push_alert(
            severity=2,  # CRITICAL
            message=(
                f"Embedder has failed {state['consecutive_failures']} consecutive health checks "
                f"(threshold={THRESHOLD}) at {EMBEDDER_URL} — "
                f"all SDK operations relying on embeddings will silently degrade."
            ),
            consecutive=state["consecutive_failures"],
            calls=state["total_calls"],
            errors=state["total_errors"],
            degraded=True,
            recovery=False,
            reachable=False,
        )
        if ok:
            print(
                f"[{time.strftime('%H:%M:%S')}] "
                f"CRITICAL: Embedder unreachable after {state['consecutive_failures']} checks "
                f"(total_calls={state['total_calls']})"
            )
        _save_state(state)
        return 0 if ok else 1

    if state.get("alerted"):
        # Already alerted — just log and continue
        _save_state(state)

    state["last_update_ts"] = time.time()
    _save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(run())
