#!/usr/bin/env python3
"""Scrape embedder sidecar state and push to STDB.

Gets RSS from /proc/<pid>/status, health info from the embedder's /health
endpoint, and uptime from ps lstart. Constructs Prometheus-formatted text
and calls the ``push_embedder_metrics`` reducer on the spacetime-memory module.

NOTE: The push_embedder_metrics reducer exists in the Rust source but requires
the WASM module to be published to STDB. Until that's done (see ROADMAP 1.1),
the STDB push will fail with 404 -- the script still produces valid output
so it can be used standalone or piped.

Usage:
    python3 scripts/push_embedder_metrics.py

Env:
    SPACETIMEDB_HOST    (default: localhost)
    SPACETIMEDB_PORT    (default: 3001)
    SPACETIMEDB_DB      (default: auto-detect)
    SPACETIMEDB_TOKEN   (default: read from ~/.config/spacetime/cli.toml)
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import time

import httpx

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")

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

_headers = {"Content-Type": "application/json"}
if TOKEN:
    _headers["Authorization"] = f"Bearer {TOKEN}"

_http = httpx.Client(timeout=30)

CALL_URL = f"http://{HOST}:{PORT}/v1/database/{DB}/call"


# ── Helpers ─────────────────────────────────────────────────────────


def _find_embedder_pid() -> int | None:
    """Find the PID of the running embedder process."""
    try:
        r = subprocess.run(
            ["pgrep", "-f", "target/release/embedder"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in r.stdout.strip().splitlines():
            pid = int(pid_str.strip())
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", errors="replace")
            if "target/release/embedder" in cmdline and "rustc" not in cmdline:
                return pid
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _read_rss_bytes(pid: int) -> int:
    """Read RSS from /proc/<pid>/status in bytes."""
    for line in open(f"/proc/{pid}/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def _read_uptime_seconds(pid: int) -> int:
    """Read process uptime in seconds using ps lstart."""
    try:
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True, text=True, timeout=5,
        )
        lstart = r.stdout.strip()
        if lstart:
            start = datetime.datetime.strptime(lstart, "%a %b %d %H:%M:%S %Y")
            now = datetime.datetime.now()
            return int((now - start).total_seconds())
    except (OSError, json.JSONDecodeError):
        pass
    return 0


def _parse_health() -> dict:
    """Fetch and parse the embedder /health endpoint."""
    try:
        resp = _http.get("http://localhost:9090/health", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        print("  Embedder not reachable at http://localhost:9090/health.", file=sys.stderr)
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  Health fetch failed: {exc}", file=sys.stderr)
        return {}


# ── Push ────────────────────────────────────────────────────────────


def push_metrics(raw_text: str) -> bool:
    """Push embedder metrics to STDB reducer."""
    pid = _find_embedder_pid()
    if not pid:
        print("  Embedder process not found.", file=sys.stderr)
        return False

    rss_bytes = _read_rss_bytes(pid)
    uptime_seconds = _read_uptime_seconds(pid)
    health = _parse_health()
    if not health:
        return False

    embedding_count = health.get("embedding_count", 0)
    model_name = health.get("model", "unknown")
    dimension = health.get("dimension", 0)

    args = [rss_bytes, embedding_count, uptime_seconds, dimension, model_name, raw_text]

    try:
        resp = _http.post(
            f"{CALL_URL}/push_embedder_metrics",
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
            f"  Connection refused -- STDB at {HOST}:{PORT}",
            file=sys.stderr,
        )
        return False
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  Unexpected error: {exc}", file=sys.stderr)
        return False


def run() -> int:
    """Fetch state from embedder and push to STDB."""
    pid = _find_embedder_pid()
    if not pid:
        print("  Embedder process not found.", file=sys.stderr)
        return 0  # Not an error -- embedder may be restarting

    rss_bytes = _read_rss_bytes(pid)
    uptime_seconds = _read_uptime_seconds(pid)
    health = _parse_health()
    if not health:
        return 1

    embedding_count = health.get("embedding_count", 0)
    model_name = health.get("model", "unknown")
    dimension = health.get("dimension", 0)

    raw = (
        "# HELP embedder_rss_bytes Resident set size\n"
        "# TYPE embedder_rss_bytes gauge\n"
        f"embedder_rss_bytes {rss_bytes}\n"
        "# HELP embedder_embedding_count Total embeddings\n"
        "# TYPE embedder_embedding_count counter\n"
        f"embedder_embedding_count {embedding_count}\n"
        "# HELP embedder_uptime_seconds Uptime\n"
        "# TYPE embedder_uptime_seconds gauge\n"
        f"embedder_uptime_seconds {uptime_seconds}\n"
        "# HELP embedder_dimension Embedding dimension\n"
        "# TYPE embedder_dimension gauge\n"
        f"embedder_dimension {dimension}\n"
        "# HELP embedder_model_info Model info\n"
        "# TYPE embedder_model_info gauge\n"
        f'embedder_model_info{{model="{model_name}"}} 1\n'
    )

    rss_mb = rss_bytes / (1024 * 1024)
    print(
        f"[{time.strftime('%H:%M:%S')}] Embedder metrics: "
        f"rss={rss_mb:.1f}MB "
        f"embeddings={embedding_count} "
        f"uptime={uptime_seconds}s "
        f"model={model_name}"
    )

    # Push to STDB
    ok = push_metrics(raw)
    if ok:
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(run())
