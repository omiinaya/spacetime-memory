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

# Bypass HTTP proxy for localhost STDB connections.
# The system has http_proxy set to isp.decodo.com:10001 which
# returns 403 Forbidden for reducer calls.
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,127.0.0.1,.local")

# Allow running from project root or cron (hermes/scripts)
for prefix in (".", "..", os.path.expanduser("~/spacetime-memory")):
    sdk_path = os.path.join(prefix, "sdk/python")
    if os.path.isdir(sdk_path):
        sys.path.insert(0, sdk_path)
        break

from spacetime_memory import Client

# ── Config ──────────────────────────────────────────────────────────
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB",
                     "c20082e7643347e8d36302b550bb98c7343f9ea2a268f3bee58ee58d3c3dcbf1")

_client: Client | None = None


_TOKEN_FILE = os.getenv("CRON_IDENTITY_TOKEN_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cron_identity_token"))


def _c() -> Client:
    global _client
    if _client is None:
        _client = Client(host=HOST, port=PORT, database=DB)

        # Reuse identity token across runs to avoid per-tick account creation
        if os.path.exists(_TOKEN_FILE):
            try:
                with open(_TOKEN_FILE) as f:
                    _client._identity_token = f.read().strip()
                    _client._identity_established = True
            except (KeyError, IndexError):
                pass

        if not getattr(_client, "_identity_established", False):
            # First run: register and save token
            import uuid as _uuid
            user = f"cron_{_uuid.uuid4().hex[:8]}"
            try:
                _client._call("register", [user, "Cron", "cronpass123"])
            except RuntimeError:
                pass
            try:
                my_id = _client._whoami()
                _client._call("set_initial_admin", [my_id])
            except RuntimeError:
                pass
            # Persist identity token for next run
            if getattr(_client, "_identity_token", None):
                try:
                    with open(_TOKEN_FILE, "w") as f:
                        f.write(_client._identity_token)
                except (KeyError, IndexError):
                    pass
    return _client


# ── Operations ──────────────────────────────────────────────────────

def decay_weak(workspace_id: str) -> bool:
    try:
        _c()._call("decay_weak_memories", [workspace_id, 0.2])
        return True
    except RuntimeError:
        return False


def reinforce_recent(workspace_id: str) -> int:
    cutoff = int(time.time() * 1000) - 24 * 3_600_000
    rows = _c()._query("memory", filter_dict={
        "workspace_id": workspace_id,
        "is_active": "true",
    }, columns=["id", "updated_at"])
    count = 0
    for row in rows:
        if row.get("updated_at", 0) > cutoff:
            try:
                _c()._call("reinforce_memory", [row["id"]])
                count += 1
            except RuntimeError:
                pass
    return count


def backfill_embeddings(workspace_id: str) -> int:
    """Embed memories that have no search_index entry yet.

    Queries for active memories missing from search_index, calls the
    embedder sidecar, and populates the index.  Rate-limited to 50 per
    tick to avoid overwhelming the embedder.
    """
    MAX_PER_TICK = 50
    try:
        all_mems = _c()._query("memory", workspace_id=workspace_id)
    except RuntimeError:
        return 0

    # Find memories without index entries
    indexed = set()
    try:
        idx_rows = _c()._query("search_index", workspace_id=workspace_id)
        indexed = {r.get("entity_id", "") for r in idx_rows if r.get("entity_type") == "memory"}
    except RuntimeError:
        pass

    need_embedding = [
        m for m in all_mems
        if m.get("id", "") not in indexed and m.get("is_active", True)
    ][:MAX_PER_TICK]

    if not need_embedding:
        return 0

    import json
    contents = [m.get("content", "") for m in need_embedding]
    mem_ids = [m["id"] for m in need_embedding]

    try:
        emb_result = _c()._embed_batch(contents)
    except (OSError, json.JSONDecodeError):
        emb_result = []
        for content in contents:
            emb_result.append(_c()._embed(content))

    count = 0
    for i, mem_id in enumerate(mem_ids):
        emb = emb_result[i] if i < len(emb_result) else None
        if not emb:
            continue
        try:
            _c()._call("index_entity", [
                workspace_id, "memory", mem_id,
                need_embedding[i].get("content", ""),
                json.dumps(emb),
            ])
            count += 1
        except RuntimeError:
            pass

    return count


def run_consolidation(_ws: str) -> bool:
    try:
        _c()._call("manual_maintenance", [])
        return True
    except RuntimeError:
        return False


def update_god_nodes(workspace_id: str) -> bool:
    try:
        _c()._call("compute_god_nodes", [workspace_id, 50])
        return True
    except RuntimeError:
        return False


def detect_communities(workspace_id: str) -> bool:
    try:
        _c()._call("detect_communities", [workspace_id])
        return True
    except RuntimeError:
        return False


def expire_stale() -> bool:
    """Expire all memories past their expires_at timestamp."""
    try:
        result = _c().expire_memories()
        return bool(result.get("ok", result.get("deactivated", 0) > 0))
    except RuntimeError:
        return False


def run_all(workspace_id: str | None = None) -> dict[str, Any]:
    if workspace_id:
        ws_list = [{"id": workspace_id}]
    else:
        ws_list = _c()._query("workspace", columns=["id"])

    results: dict[str, Any] = {
        "workspaces": len(ws_list),
        "decayed": 0, "reinforced": 0,
        "consolidated": 0, "god_nodes": 0, "communities": 0,
        "replication_cleaned": 0, "embeddings_backfilled": 0,
        "expired": 0,
    }

    # Expire stale memories globally before per-workspace operations
    if expire_stale():
        results["expired"] = 1

    for ws in ws_list:
        wid = ws["id"]
        print(f"  Workspace {wid[:16]}...")

        if decay_weak(wid):
            results["decayed"] += 1

        results["reinforced"] += reinforce_recent(wid)

        if run_consolidation(wid):
            results["consolidated"] += 1

        if update_god_nodes(wid):
            results["god_nodes"] += 1

        if detect_communities(wid):
            results["communities"] += 1

        try:
            _c()._call("cleanup_replication_log", [wid])
            results["replication_cleaned"] += 1
        except RuntimeError:
            pass

        bf_count = backfill_embeddings(wid)
        results["embeddings_backfilled"] += bf_count
        if bf_count > 0:
            print(f"    Embeddings backfilled: {bf_count}")

    return results


if __name__ == "__main__":
    ws_arg = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"[{time.strftime('%H:%M:%S')}] Consolidation cron starting...")
    results = run_all(ws_arg)
    print(f"  Done: {results['workspaces']} workspaces, "
          f"{results['decayed']} decay ticks, {results['reinforced']} reinforced, "
          f"{results['consolidated']} consolidations, "
          f"{results['god_nodes']} god-node updates, "
          f"{results['communities']} community detections, "
          f"{results['replication_cleaned']} replication log cleanups, "
          f"{results['embeddings_backfilled']} embeddings backfilled, "
          f"{'expired' if results['expired'] else 'no expired'} memories")
