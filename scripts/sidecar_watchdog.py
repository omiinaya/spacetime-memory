#!/usr/bin/env python3
"""Sidecar Health Watchdog — periodic check for embedder & Tantivy sidecars.

Usage:
    python3 scripts/sidecar_watchdog.py               # Default: localhost
    python3 scripts/sidecar_watchdog.py --json         # Machine-readable output
    python3 scripts/sidecar_watchdog.py --verbose      # Include success info

Designed for cron / systemd-timer use. Exit code:
    0 = both sidecars healthy
    1 = one or more sidecars unreachable

Logs warnings to stderr (captured by systemd journal when run by a timer).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
import urllib.error
import json


EMBEDDER_URL = os.environ.get("EMBEDDER_HEALTH_URL", "http://localhost:9090/health")
TANTIVY_URL = os.environ.get("TANTIVY_HEALTH_URL", "http://localhost:9091/health")
TIMEOUT = float(os.environ.get("WATCHDOG_TIMEOUT", "5"))


def check_health(url: str, name: str, timeout: float = TIMEOUT) -> dict:
    """Check a sidecar's /health endpoint. Returns status dict."""
    result = {
        "name": name,
        "url": url,
        "reachable": False,
        "status": "error",
        "latency_ms": 0,
        "detail": "",
    }
    start = time.monotonic()
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        result["latency_ms"] = elapsed_ms

        if resp.status == 200:
            body = resp.read().decode()
            try:
                data = json.loads(body)
                result["status"] = data.get("status", "unknown")
                result["reachable"] = True
                result["detail"] = body[:200]
            except json.JSONDecodeError:
                result["status"] = "ok"
                result["reachable"] = True
                result["detail"] = body[:200]
        else:
            result["status"] = f"http_{resp.status}"
            result["detail"] = f"HTTP {resp.status}: {resp.read().decode()[:200]}"
    except urllib.error.URLError as e:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        result["latency_ms"] = elapsed_ms
        result["detail"] = str(e.reason)
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        result["latency_ms"] = elapsed_ms
        result["detail"] = str(e)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sidecar Health Watchdog for Spacetime Memory"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable text",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include success info in output (default: only failures)",
    )
    parser.add_argument(
        "--embedder-url",
        default=EMBEDDER_URL,
        help=f"Embedder health URL (default: {EMBEDDER_URL})",
    )
    parser.add_argument(
        "--tantivy-url",
        default=TANTIVY_URL,
        help=f"Tantivy health URL (default: {TANTIVY_URL})",
    )
    args = parser.parse_args()

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    embedder_result = check_health(args.embedder_url, "embedder")
    tantivy_result = check_health(args.tantivy_url, "tantivy")

    all_ok = embedder_result["reachable"] and tantivy_result["reachable"]

    if args.json:
        output = {
            "timestamp": timestamp,
            "status": "ok" if all_ok else "degraded",
            "embedder": embedder_result,
            "tantivy": tantivy_result,
        }
        print(json.dumps(output, indent=2))
        return 0 if all_ok else 1

    # Human-readable output
    exit_code = 0

    for result in [embedder_result, tantivy_result]:
        name = result["name"]
        lat = result["latency_ms"]
        if result["reachable"]:
            if args.verbose:
                detail_short = result["detail"][:80] if result["detail"] else ""
                print(f"[{timestamp}] ✅ {name} reachable ({lat}ms) {detail_short}")
        else:
            print(
                f"[{timestamp}] ❌ {name} DOWN ({lat}ms) — {result['detail']}",
                file=sys.stderr,
            )
            exit_code = 1

    if args.verbose and all_ok:
        print(f"[{timestamp}] ✅ All sidecars healthy")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
