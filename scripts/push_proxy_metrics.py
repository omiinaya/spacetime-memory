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

# Read token from env, cli.toml, or default path
TOKEN = os.environ.get("SPACETIMEDB_TOKEN")
if not TOKEN:
    # Try CLI config (spacetimedb_token from cli.toml)
    _cli_toml = os.path.expanduser("~/.config/spacetime/cli.toml")
    if os.path.isfile(_cli_toml):
        try:
            import tomllib
            with open(_cli_toml, "rb") as _f:
                _cfg = tomllib.load(_f)
            TOKEN = _cfg.get("spacetimedb_token", "")
        except (ImportError, Exception):
            pass
if not TOKEN:
    _token_path = os.path.expanduser("~/.config/spacetime/identity_token")
    if not os.path.isfile(_token_path):
        _token_path = os.path.expanduser("~/.spacetime/token")
    if os.path.isfile(_token_path):
        TOKEN = open(_token_path).read().strip()

_headers = {"Content-Type": "application/json"}
if TOKEN:
    _headers["Authorization"] = f"Bearer {TOKEN}"

# We need _http for auto-detect and for the reducer calls
_http = httpx.Client(timeout=30)

# Auto-detect DB identity if using default name "spacetime-memory"
# The local server has a *different* database registered under that name;
# our module (owned by the CLI identity) has no name.  Look it up.
_DB_AUTO_DETECTED = False
if DB in ("spacetime-memory", "") and TOKEN:
    try:
        # Decode identity from JWT
        import base64
        _payload_b64 = TOKEN.split(".")[1]
        _padding = 4 - len(_payload_b64) % 4
        if _padding != 4:
            _payload_b64 += "=" * _padding
        _payload = json.loads(base64.urlsafe_b64decode(_payload_b64))
        _owner_hex = _payload.get("hex_identity", "")
        if _owner_hex:
            # Query the server for databases owned by this identity
            _resp = httpx.get(
                f"http://{HOST}:{PORT}/v1/identity/{_owner_hex}/databases",
                timeout=5,
            )
            if _resp.status_code == 200:
                _data = _resp.json()
                _db_ids = _data.get("identities", []) if isinstance(_data, dict) else _data
                for _db_id in _db_ids:
                    if not _db_id or not _db_id.startswith("c200"):
                        continue
                    # Describe it (cheap) and check for the reducer
                    _desc_resp = httpx.get(
                        f"http://{HOST}:{PORT}/v1/database/{_db_id}/describe",
                        timeout=5,
                    )
                    if _desc_resp.status_code == 200:
                        _desc = _desc_resp.json()
                        for _r in _desc.get("reducers", []):
                            if _r.get("name") == "push_proxy_metrics":
                                DB = _db_id
                                _DB_AUTO_DETECTED = True
                                break
                    if _DB_AUTO_DETECTED:
                        break
    except (OSError, json.JSONDecodeError):
        pass

CALL_URL = f"http://{HOST}:{PORT}/v1/database/{DB}/call"


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


def parse_latency_percentiles(text: str) -> dict:
    """Extract per-model latency percentiles from Prometheus text.
    
    Returns a dict:
    {
        "overall": {"p50": 0.5, "p95": 2.0, "p99": 5.0, "mean": 1.3, "samples": 100},
        "per_model": {
            "provider|model": {"p50": 1.2, "p95": 3.0, "p99": 5.5, "mean": 1.3, "samples": 50}
        }
    }
    """
    models: dict[str, dict[str, float]] = {}
    all_p50: list[tuple[float, int]] = []  # (p50, samples)
    all_p95: list[tuple[float, int]] = []
    all_p99: list[tuple[float, int]] = []
    all_mean: list[tuple[float, int]] = []
    total_samples = 0
    
    for line in text.splitlines():
        # model_latency_p50_seconds{model_key="provider|model",samples="N"} 1.234
        m = re.match(
            r'model_latency_p50_seconds\{model_key="([^"]+)",samples="(\d+)"\}\s+([\d.]+)',
            line
        )
        if m:
            key = m.group(1)
            samples = int(m.group(2))
            val = float(m.group(3))
            if key not in models:
                models[key] = {}
            models[key]["p50"] = val
            models[key]["samples"] = samples
            if val > 0:
                all_p50.append((val, samples))
                total_samples += samples
            continue
        
        m = re.match(
            r'model_latency_p95_seconds\{model_key="([^"]+)",samples="(\d+)"\}\s+([\d.]+)',
            line
        )
        if m:
            key = m.group(1)
            val = float(m.group(3))
            if key not in models:
                models[key] = {}
            models[key]["p95"] = val
            if val > 0:
                all_p95.append((val, int(m.group(2))))
            continue
        
        m = re.match(
            r'model_latency_p99_seconds\{model_key="([^"]+)",samples="(\d+)"\}\s+([\d.]+)',
            line
        )
        if m:
            key = m.group(1)
            val = float(m.group(3))
            if key not in models:
                models[key] = {}
            models[key]["p99"] = val
            if val > 0:
                all_p99.append((val, int(m.group(2))))
            continue
        
        m = re.match(
            r'model_latency_mean_seconds\{model_key="([^"]+)",samples="(\d+)"\}\s+([\d.]+)',
            line
        )
        if m:
            key = m.group(1)
            val = float(m.group(3))
            if key not in models:
                models[key] = {}
            models[key]["mean"] = val
            if val > 0:
                all_mean.append((val, int(m.group(2))))
            continue
    
    # Filter out models with no actual latency data (all zeros)
    per_model = {}
    for key, data in models.items():
        if any(v > 0 for v in data.values() if isinstance(v, (int, float))):
            per_model[key] = data
    
    # Compute weighted overall percentiles
    def weighted_avg(items: list) -> float:
        if not items:
            return 0.0
        total_w = sum(w for _, w in items)
        if total_w == 0:
            return 0.0
        return sum(v * w for v, w in items) / total_w
    
    overall_p50 = weighted_avg(all_p50)
    overall_p95 = weighted_avg(all_p95)
    overall_p99 = weighted_avg(all_p99)
    overall_mean = weighted_avg(all_mean)
    
    overall = {
        "p50": round(overall_p50, 4),
        "p95": round(overall_p95, 4),
        "p99": round(overall_p99, 4),
        "mean": round(overall_mean, 4),
        "samples": total_samples,
    }
    
    return {"overall": overall, "per_model": per_model}


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

    latency_percentiles = parse_latency_percentiles(raw_text)
    latency_percentiles_json = json.dumps(latency_percentiles)

    args = [
        requests,
        tokens,
        errors,
        duration_sum_micros,
        duration_count,
        per_model_json,
        latency_percentiles_json,
        raw_text,
    ]

    try:
        resp = _http.post(
            f"{CALL_URL}/push_proxy_metrics",
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
            f"  Connection refused — proxy at {PROXY_METRICS_URL} "
            f"or STDB at {HOST}:{PORT} is not running",
            file=sys.stderr,
        )
        return False
    except (OSError, json.JSONDecodeError):
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
    except (OSError, json.JSONDecodeError):
        print(f"  Failed to fetch metrics: {exc}", file=sys.stderr)
        return 1

    if not raw_text.strip():
        print("  Empty metrics response. Skipping.", file=sys.stderr)
        return 0

    # Push
    ok = push_metrics(raw_text)
    if ok:
        metrics = parse_prometheus(raw_text)
        latency = parse_latency_percentiles(raw_text)
        overall = latency.get("overall", {})
        p50_str = f" p50={overall.get('p50', 0):.3f}s" if overall.get('p50', 0) > 0 else ""
        p95_str = f" p95={overall.get('p95', 0):.3f}s" if overall.get('p95', 0) > 0 else ""
        print(
            f"[{time.strftime('%H:%M:%S')}] Metrics pushed: "
            f"requests={int(metrics.get('requests_total', 0))} "
            f"tokens={int(metrics.get('tokens_total', 0))} "
            f"errors={int(metrics.get('errors_total', 0))}"
            f"{p50_str}{p95_str}"
        )
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(run())
