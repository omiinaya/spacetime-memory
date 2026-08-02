#!/usr/bin/env python3
"""
Health watchdog — checks embedder and Tantivy sidecar /health endpoints
and pushes alerts to SpacetimeDB via the push_embedder_alert and
push_tantivy_alert reducers.

Designed to be run as a cron job every 30 seconds.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

# --- Config from environment with defaults ---
HOST = os.getenv("STDB_HOST", "http://localhost")
PORT = os.getenv("STDB_PORT", "8080")
API_KEY = os.getenv("API_KEY", "")

EMBEDDER_URL = os.getenv("EMBEDDER_URL", "http://localhost:4000")
TANTIVY_URL = os.getenv("TANTIVY_URL", "http://localhost:4001")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

CONSECUTIVE_FAILURE_THRESHOLD = int(os.getenv("HEALTH_FAILURE_THRESHOLD", "3"))

# Simple in-memory state for consecutive failure tracking
# In production, use the database or a proper state store
_state = {
    "embedder_consecutive": 0,
    "tantivy_consecutive": 0,
}

def send_discord_alert(component: str, severity: str, message: str) -> bool:
    """Send an alert to Discord webhook if configured.

    Args:
        component: "Embedder" or "Tantivy" or similar.
        severity: "CRITICAL", "RECOVERY", or "WARNING".
        message: Human-readable alert message.
    Returns:
        True if sent successfully (or no webhook configured), False on error.
    """
    if not DISCORD_WEBHOOK_URL:
        return True  # No webhook configured — silently skip
    colors = {"CRITICAL": 15548997, "WARNING": 16776960, "RECOVERY": 5763719}
    payload = json.dumps({
        "embeds": [{
            "title": f"{component} — {severity}",
            "description": message,
            "color": colors.get(severity, 10197915),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  Discord alert failed: {e}", file=sys.stderr)
        return False


def call_reducer(reducer_name: str, args: dict) -> bool:
    """Call a SpacetimeDB reducer via HTTP API."""
    url = f"{HOST}:{PORT}/v1/database/spacetime-memory/reducers/{reducer_name}"
    headers = {
        "Content-Type": "application/json",
    }
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    payload = json.dumps(args).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True
            print(f"  Reducer call failed: HTTP {resp.status} {resp.read().decode()[:200]}", file=sys.stderr)
            return False
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.reason}", file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        print(f"  Connection error: {e.reason}", file=sys.stderr)
        return False
    except OSError as e:
        print(f"  OS error: {e}", file=sys.stderr)
        return False


def check_embedder():
    """Check embedder /health and push alert if needed."""
    url = f"{EMBEDDER_URL}/health"
    reachable = False
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status == 200:
                reachable = True
                data = json.loads(resp.read().decode())
                if data.get("status") == "ok":
                    degraded = False
                    consecutive = 0
                else:
                    degraded = True
                    consecutive = 1
            else:
                reachable = True
                degraded = True
                consecutive = 1
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        reachable = False
        degraded = True
        consecutive = 1

    if not reachable or degraded:
        _state["embedder_consecutive"] += consecutive
    else:
        # Check if we need to send recovery
        if _state["embedder_consecutive"] >= CONSECUTIVE_FAILURE_THRESHOLD:
            recovery_msg = f"Embedder has recovered after {_state['embedder_consecutive']} consecutive failures."
            # Push recovery alert
            success = call_reducer("push_embedder_alert", {
                "severity": 0,  # RECOVERY
                "message": recovery_msg,
                "consecutive_failures": 0,
                "total_calls": 0,
                "total_errors": 0,
                "error_rate_pct": 0.0,
                "degraded": False,
                "recovery": True,
                "reachable": True,
                "embedder_url": EMBEDDER_URL,
            })
            if success:
                print(f"[{time.strftime('%H:%M:%S')}] Embedder: pushed recovery alert")
                send_discord_alert("Embedder", "RECOVERY", recovery_msg)
        _state["embedder_consecutive"] = 0
        return

    # If consecutive failures exceed threshold, push critical alert
    if _state["embedder_consecutive"] >= CONSECUTIVE_FAILURE_THRESHOLD:
        severity = 2  # CRITICAL
        message = f"Embedder down: {_state['embedder_consecutive']} consecutive failures"
        if not reachable:
            message = f"Embedder unreachable at {EMBEDDER_URL}"
        success = call_reducer("push_embedder_alert", {
            "severity": severity,
            "message": message,
            "consecutive_failures": _state["embedder_consecutive"],
            "total_calls": 0,
            "total_errors": _state["embedder_consecutive"],
            "error_rate_pct": 100.0,
            "degraded": True,
            "recovery": False,
            "reachable": reachable,
            "embedder_url": EMBEDDER_URL,
        })
        if success:
            print(f"[{time.strftime('%H:%M:%S')}] Embedder: pushed CRITICAL alert ({_state['embedder_consecutive']} consecutive)")
            send_discord_alert("Embedder", "CRITICAL", message)
    elif _state["embedder_consecutive"] >= CONSECUTIVE_FAILURE_THRESHOLD - 1:
        # Warning level
        success = call_reducer("push_embedder_alert", {
            "severity": 1,  # WARNING
            "message": f"Embedder Warning: {_state['embedder_consecutive']} consecutive failures",
            "consecutive_failures": _state["embedder_consecutive"],
            "total_calls": 0,
            "total_errors": _state["embedder_consecutive"],
            "error_rate_pct": 100.0,
            "degraded": True,
            "recovery": False,
            "reachable": reachable,
            "embedder_url": EMBEDDER_URL,
        })
        if success:
            print(f"[{time.strftime('%H:%M:%S')}] Embedder: pushed WARNING alert")


def check_tantivy():
    """Check Tantivy sidecar /health and push alert if needed."""
    url = f"{TANTIVY_URL}/health"
    reachable = False
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status == 200:
                reachable = True
                degraded = False
                consecutive = 0
            else:
                reachable = True
                degraded = True
                consecutive = 1
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        reachable = False
        degraded = True
        consecutive = 1

    if not reachable or degraded:
        _state["tantivy_consecutive"] += consecutive
    else:
        if _state["tantivy_consecutive"] >= CONSECUTIVE_FAILURE_THRESHOLD:
            recovery_msg = f"Tantivy sidecar has recovered after {_state['tantivy_consecutive']} consecutive failures."
            success = call_reducer("push_tantivy_alert", {
                "severity": 0,  # RECOVERY
                "message": recovery_msg,
                "consecutive_failures": 0,
                "total_checks": 0,
                "total_failures": 0,
                "error_rate_pct": 0.0,
                "degraded": False,
                "recovery": True,
                "reachable": True,
                "tantivy_url": TANTIVY_URL,
            })
            if success:
                print(f"[{time.strftime('%H:%M:%S')}] Tantivy: pushed recovery alert")
                send_discord_alert("Tantivy", "RECOVERY", recovery_msg)
        _state["tantivy_consecutive"] = 0
        return

    if _state["tantivy_consecutive"] >= CONSECUTIVE_FAILURE_THRESHOLD:
        severity = 2  # CRITICAL
        message = f"Tantivy sidecar down: {_state['tantivy_consecutive']} consecutive failures"
        if not reachable:
            message = f"Tantivy sidecar unreachable at {TANTIVY_URL}"
        success = call_reducer("push_tantivy_alert", {
            "severity": severity,
            "message": message,
            "consecutive_failures": _state["tantivy_consecutive"],
            "total_checks": 0,
            "total_failures": _state["tantivy_consecutive"],
            "error_rate_pct": 100.0,
            "degraded": True,
            "recovery": False,
            "reachable": reachable,
            "tantivy_url": TANTIVY_URL,
        })
        if success:
            print(f"[{time.strftime('%H:%M:%S')}] Tantivy: pushed CRITICAL alert ({_state['tantivy_consecutive']} consecutive)")
            send_discord_alert("Tantivy", "CRITICAL", message)
    elif _state["tantivy_consecutive"] >= CONSECUTIVE_FAILURE_THRESHOLD - 1:
        success = call_reducer("push_tantivy_alert", {
            "severity": 1,  # WARNING
            "message": f"Tantivy Warning: {_state['tantivy_consecutive']} consecutive failures",
            "consecutive_failures": _state["tantivy_consecutive"],
            "total_checks": 0,
            "total_failures": _state["tantivy_consecutive"],
            "error_rate_pct": 100.0,
            "degraded": True,
            "recovery": False,
            "reachable": reachable,
            "tantivy_url": TANTIVY_URL,
        })
        if success:
            print(f"[{time.strftime('%H:%M:%S')}] Tantivy: pushed WARNING alert")


def main():
    check_embedder()
    check_tantivy()


if __name__ == "__main__":
    main()
