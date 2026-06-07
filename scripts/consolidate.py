#!/usr/bin/env python3
"""Consolidation cron for spacetime-memory.

Runs scheduled consolidation/decay/reinforcement operations.
Call via cron or Hermes cronjob every 15-30 minutes.

Usage: python3 consolidate.py [--workspace WORKSPACE_ID]
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

# ── Config ──────────────────────────────────────────────────────────
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")

SQL_URL = f"http://{HOST}:{PORT}/v1/database/{DB}/sql"
CALL_URL = f"http://{HOST}:{PORT}/v1/database/{DB}/call"

_http = httpx.Client(timeout=60)


# ── Helpers ─────────────────────────────────────────────────────────

def _sql(query: str) -> list[dict[str, Any]]:
    resp = _http.post(SQL_URL, content=query, headers={"Content-Type": "text/plain"})
    if resp.status_code >= 400:
        print(f"  SQL error ({resp.status_code}): {resp.text[:120]}")
        return []
    return _parse_sql_response(resp.text)


def _call(reducer: str, args: list[Any]) -> bool:
    resp = _http.post(f"{CALL_URL}/{reducer}", content=json.dumps(args),
                      headers={"Content-Type": "application/json"})
    ok = resp.status_code < 400
    if not ok:
        print(f"  Reducer '{reducer}' error ({resp.status_code}): {resp.text[:120]}")
    return ok


def _parse_sql_response(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    try:
        tables = json.loads(raw)
        rows: list[dict[str, Any]] = []
        for table in tables:
            cols = [e["name"]["some"] for e in table["schema"]["elements"]]
            for row in table.get("rows", []):
                r: dict[str, Any] = {}
                for i, col in enumerate(cols):
                    r[_to_camel(col)] = row[i]
                rows.append(r)
        return rows
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"  Parse error: {e}")
        return []


def _to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _esc(s: str) -> str:
    return s.replace("'", "''")


# ── Operations ──────────────────────────────────────────────────────

def decay_weak(workspace_id: str) -> bool:
    """Deactivate memories below 0.2 strength, not recently updated.
    The reducer handles cutoff logic internally."""
    return _call("decay_weak_memories", [workspace_id, 0.2])


def reinforce_recent(workspace_id: str) -> int:
    """Bump strength on memories accessed in the last 24h."""
    cutoff = int(time.time() * 1000) - 24 * 3_600_000
    rows = _sql(
        "SELECT id FROM memory WHERE "
        f"workspace_id = '{_esc(workspace_id)}' AND "
        f"is_active = TRUE AND "
        f"updated_at > {cutoff}"
    )
    count = 0
    for row in rows:
        if _call("reinforce_memory", [row["id"]]):
            count += 1
    return count


def run_consolidation(workspace_id: str) -> bool:
    """Run maintenance: expire memories, decay weak, dedup."""
    return _call("manual_maintenance", [])


def update_god_nodes(workspace_id: str) -> bool:
    """Recalculate top-degree nodes in the knowledge graph.
    The reducer handles edge counting in-WASM."""
    return _call("compute_god_nodes", [workspace_id, 50])


def detect_communities(workspace_id: str) -> bool:
    """Run community detection (Leiden-style clustering) on KG nodes."""
    return _call("detect_communities", [workspace_id])


def run_all(workspace_id: str | None = None) -> dict[str, Any]:
    """Run all consolidation operations for one or all workspaces."""
    if workspace_id:
        ws_list = [{"id": workspace_id}]
    else:
        ws_list = _sql("SELECT id FROM workspace")

    results: dict[str, Any] = {
        "workspaces": len(ws_list),
        "decayed": 0, "reinforced": 0,
        "consolidated": 0, "god_nodes": 0, "communities": 0,
    }

    for ws in ws_list:
        wid = ws["id"]
        print(f"  Worskpace {wid[:16]}...")

        if decay_weak(wid):
            results["decayed"] += 1

        results["reinforced"] += reinforce_recent(wid)

        if run_consolidation(wid):
            results["consolidated"] += 1

        if update_god_nodes(wid):
            results["god_nodes"] += 1

        if detect_communities(wid):
            results["communities"] += 1

    return results


if __name__ == "__main__":
    ws_arg = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"[{time.strftime('%H:%M:%S')}] Consolidation cron starting...")
    results = run_all(ws_arg)
    print(f"  Done: {results['workspaces']} workspaces, "
          f"{results['decayed']} decay ticks, {results['reinforced']} reinforced, "
          f"{results['consolidated']} consolidations, "
          f"{results['god_nodes']} god-node updates, "
          f"{results['communities']} community detections")
