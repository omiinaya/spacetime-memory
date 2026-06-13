#!/usr/bin/env python3
"""Scrape SpacetimeLLM proxy /metrics and push to STDB.

Parses Prometheus text format from the proxy's /metrics endpoint and
calls the ``push_proxy_metrics`` reducer on the spacetime-memory module.

Usage:
    python3 scripts/push_proxy_metrics.py

Env vars:
    PROXY_METRICS_URL — URL of the proxy /metrics endpoint
                        (default: http://localhost:4000/metrics)
    SPACETIMEDB_HOST  — STDB host (default: localhost)
    SPACETIMEDB_PORT  — STDB HTTP port (default: 3001)
    SPACETIMEDB_DB    — STDB database name (default: spacetime-memory)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

import httpx

# ── Config ──────────────────────────────────────────────────────────
PROXY_METRICS_URL = os.environ.get(
    "PROXY_METRICS_URL", "http://localhost:4000/metrics"
)
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")

CALL_URL = f"http://{HOST}:{PORT}/v1/database/{DB}/call"

_http = httpx.Client(timeout=30)


# ── Prometheus Parser ───────────────────────────────────────────────


def parse_prometheus(text: str) -> dict[str, float]:
    """Parse Prometheus text format into a dict of metric_name → value.

    Handles counters (suffixed with _total) and gauges.
    Skipped HELP/TYPE lines and histograms (complex structure).
    """
    metrics: dict[str, float] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Histogram buckets — skip for now (we store raw text)
        if "_bucket{" in line or "_sum{" in line or "_count{" in line:
            continue

        # Simple metric: name{labels} value
        match = re.match(r"^(\w+)\s*(\{.*?\})?\s+(-?[\d.eE]+)", line)
        if match:
            name = match.group(1)
            value = float(match.group(3))
            metrics[name] = value
            continue

        # Bare metric: name value
        match = re.match(r"^(\w+)\s+(-?[\d.eE]+)", line)
        if match:
            name = match.group(1)
            value = float(match.group(2))
            metrics[name] = value

    return metrics


def parse_per_model(text: str) -> dict[str, int]:
    """Extract per-model request counts from Prometheus text."""
    models: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(
            r'requests_per_model\{model_key="([^"]+)"\}\s+(\d+)', line
        )
        if match:
            models[match.group(1)] = int(match.group(2))
    return models


# ── Push ────────────────────────────────────────────────────────────


def push_metrics(raw_text: str) -> bool:
    """Parse Prometheus text and push to STDB reducer."""
    metrics = parse_prometheus(raw_text)
    per_model = parse_per_model(raw_text)

    requests = int(metrics.get("requests_total", 0))
    tokens = int(metrics.get("tokens_total", 0))
    errors = int(metrics.get("errors_total", 0))

    # Duration histogram — use _sum and _count if available
    duration_sum_secs = metrics.get("request_duration_seconds_sum", 0.0)
    duration_count = int(metrics.get("request_duration_seconds_count", 0))
    duration_sum_micros = int(duration_sum_secs * 1_000_000)

    per_model_json = json.dumps(per_model)

    args = [
        requests,
        tokens,
        errors,
        duration_sum_micros,
        duration_count,
        per_model_json,
        raw_text,
    ]

    try:
        resp = _http.post(
            f"{CALL_URL}/push_proxy_metrics",
            content=json.dumps(args),
            headers={"Content-Type": "application/json"},
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
            f"  Connection refused — proxy at {PROXY_METRICS_URL} "
            f"or STDB at {HOST}:{PORT} is not running",
            file=sys.stderr,
        )
        return False
    except Exception as exc:
        print(f"  Unexpected error: {exc}", file=sys.stderr)
        return False


def run() -> int:
    """Fetch /metrics from proxy and push to STDB."""
    # Fetch
    try:
        resp = httpx.get(PROXY_METRICS_URL, timeout=10)
        resp.raise_for_status()
        raw_text = resp.text
    except httpx.ConnectError:
        print(
            f"  Proxy not reachable at {PROXY_METRICS_URL}. Skipping.",
            file=sys.stderr,
        )
        return 0  # Not an error — proxy may not be running
    except Exception as exc:
        print(f"  Failed to fetch metrics: {exc}", file=sys.stderr)
        return 1

    if not raw_text.strip():
        print("  Empty metrics response. Skipping.", file=sys.stderr)
        return 0

    # Push
    ok = push_metrics(raw_text)
    if ok:
        metrics = parse_prometheus(raw_text)
        print(
            f"[{time.strftime('%H:%M:%S')}] Metrics pushed: "
            f"requests={int(metrics.get('requests_total', 0))} "
            f"tokens={int(metrics.get('tokens_total', 0))} "
            f"errors={int(metrics.get('errors_total', 0))}"
        )
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(run())
