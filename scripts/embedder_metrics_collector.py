#!/usr/bin/env python3
"""
Embedder Metrics Collector — scrape /metrics and serve historical data.

Modes:
  collect   One-shot: scrape embedder /metrics, append to local JSON store.
            Intended as a no-agent cron script (every 5m).
  serve     HTTP server: serves current metrics + historical trend data
            on port 9190 so the frontend dashboard can fetch without STDB.

Store: ~/.hermes/profiles/cyber-elf/data/embedder_metrics.jsonl
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import httpx

# ── Config ──────────────────────────────────────────────────────────
EMBEDDER_METRICS_URL = os.environ.get(
    "EMBEDDER_METRICS_URL", "http://localhost:9090/metrics"
)
SERVE_PORT = int(os.environ.get("EMBEDDER_COLLECTOR_PORT", "9190"))

# Store path: use env var override, or default to project-root/data/
# Using an absolute path avoids split-brain when Path.home() differs
# between Hermes profile context and regular shell (the "doubled path" bug).
_OVERRIDE = os.environ.get("EMBEDDER_METRICS_STORE")
if _OVERRIDE:
    STORE_FILE = Path(_OVERRIDE)
else:
    _SCRIPT_DIR = Path(__file__).resolve().parent  # scripts/
    _PROJECT_ROOT = _SCRIPT_DIR.parent  # repo root
    STORE_FILE = _PROJECT_ROOT / "data" / "embedder_metrics.jsonl"
STORE_DIR = STORE_FILE.parent
STORE_DIR.mkdir(parents=True, exist_ok=True)
MAX_RECORDS = 5000  # keep at most this many records

_http = httpx.Client(timeout=10)

# ── Prometheus Parser ───────────────────────────────────────────────

def parse_embedder_metrics(text: str) -> dict[str, float | str]:
    result: dict[str, float | str] = {
        "rss_bytes": 0,
        "embedding_count": 0,
        "uptime_seconds": 0,
        "dimension": 0,
        "model_name": "",
    }
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r'embedder_model_info\{model="([^"]+)"\}\s+(?:\d+)', line)
        if match:
            result["model_name"] = match.group(1)
            continue
        for metric_name in (
            "embedder_rss_bytes",
            "embedder_embedding_count",
            "embedder_uptime_seconds",
            "embedder_dimension",
        ):
            if line.startswith(metric_name):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        value = float(parts[-1])
                        key = metric_name.replace("embedder_", "")
                        result[key] = value
                    except ValueError:
                        pass
                break
    return result


# ── Local Store ─────────────────────────────────────────────────────

def load_records() -> list[dict]:
    if not STORE_FILE.exists():
        return []
    records = []
    with open(STORE_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def append_record(record: dict) -> None:
    records = load_records()
    records.append(record)
    # Keep only last MAX_RECORDS
    if len(records) > MAX_RECORDS:
        records = records[-MAX_RECORDS:]
    with open(STORE_FILE, "w") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")


# ── Collect Mode ────────────────────────────────────────────────────

def collect() -> int:
    """Scrape embedder /metrics and append to local store."""
    try:
        resp = _http.get(EMBEDDER_METRICS_URL, timeout=10)
        resp.raise_for_status()
        raw_text = resp.text
    except httpx.ConnectError:
        print(
            f"Embedder not reachable at {EMBEDDER_METRICS_URL}. Skipping.",
            file=sys.stderr,
        )
        return 0
    except Exception as exc:
        print(f"Failed to fetch metrics: {exc}", file=sys.stderr)
        return 1

    if not raw_text.strip():
        print("Empty metrics response. Skipping.", file=sys.stderr)
        return 0

    metrics = parse_embedder_metrics(raw_text)
    record = {
        "timestamp": int(time.time() * 1000),  # ms
        "rss_bytes": int(metrics.get("rss_bytes", 0)),
        "embedding_count": int(metrics.get("embedding_count", 0)),
        "uptime_seconds": int(metrics.get("uptime_seconds", 0)),
        "dimension": int(metrics.get("dimension", 0)),
        "model_name": str(metrics.get("model_name", "")),
    }
    append_record(record)

    rss_mb = record["rss_bytes"] / (1024 * 1024)
    print(
        f"[{time.strftime('%H:%M:%S')}] Embedder metrics collected: "
        f"rss={rss_mb:.1f}MB "
        f"embeddings={record['embedding_count']} "
        f"uptime={record['uptime_seconds']}s "
        f"model={record['model_name']} "
        f"(total records: {len(load_records())})"
    )
    return 0


# ── Serve Mode ──────────────────────────────────────────────────────

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            records = load_records()
            self._json_response(200, {"status": "ok", "records": len(records)})
        elif self.path == "/records":
            records = load_records()
            self._json_response(200, records)
        elif self.path == "/latest":
            records = load_records()
            latest = records[-1] if records else {}
            self._json_response(200, latest)
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/collect":
            rc = collect()
            status = 200 if rc == 0 else 500
            records = load_records()
            msg = "ok" if rc == 0 else "collect failed"
            self._json_response(status, {"status": msg, "records": len(records)})
        else:
            self._json_response(404, {"error": "not found"})

    def _json_response(self, status: int, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[embedder-collector] {fmt % args}\n")


def serve() -> int:
    """Start HTTP server that serves stored metrics on port 9190."""
    server = HTTPServer(("0.0.0.0", SERVE_PORT), MetricsHandler)
    print(
        f"Embedder Metrics Collector serving on http://0.0.0.0:{SERVE_PORT}",
        file=sys.stderr,
    )
    print(
        f"  Store: {STORE_FILE}",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        server.shutdown()
    return 0


# ── Main ────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: embedder_metrics_collector.py [collect|serve]", file=sys.stderr)
        return 1

    mode = sys.argv[1]
    if mode == "collect":
        return collect()
    elif mode == "serve":
        return serve()
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        print("Usage: embedder_metrics_collector.py [collect|serve]", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
