#!/usr/bin/env python3
"""Reindex all STDB memories and KG nodes into the Tantivy BM25 sidecar.

Run this once after deploying the Tantivy sidecar to backfill all existing
content.  Safe to run multiple times — Tantivy upserts by entity_id.

Uses the batch endpoint (/index/batch) to index all items grouped by workspace.

Usage:
    python3 scripts/reindex-tantivy.py [--workspace WORKSPACE_ID] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

# Add SDK to path so we can import the client
SDK_PATH = Path(__file__).resolve().parent.parent / "sdk" / "python"
sys.path.insert(0, str(SDK_PATH))

from spacetime_memory import Client


def main():
    parser = argparse.ArgumentParser(description="Reindex STDB into Tantivy")
    parser.add_argument("--workspace", help="Limit to a specific workspace ID")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually index")
    parser.add_argument(
        "--tantivy-url",
        default=os.environ.get("TANTIVY_URL", "http://localhost:9091"),
    )
    args = parser.parse_args()

    client = Client()

    # Auth — register this identity
    import httpx as _httpx
    identity = ""
    try:
        resp = _httpx.get(
            f"http://{client.host}:{client.port}/v1/database/{client.database}",
            timeout=5,
        )
        identity = resp.headers.get("spacetime-identity", "")
        token = resp.headers.get("spacetime-identity-token", "")
        if token:
            client.token = token
    except (OSError, json.JSONDecodeError):
        pass

    try:
        client._call("register", ["reindexer", "reindex123", identity])
    except (OSError, json.JSONDecodeError):
        pass  # Already registered
    http = httpx.Client(timeout=10.0)

    # Check Tantivy health
    try:
        health = http.get(f"{args.tantivy_url}/health", timeout=3.0)
        health.raise_for_status()
        print(f"✓ Tantivy sidecar reachable: {health.json()}")
    except Exception as e:
        print(f"✗ Tantivy sidecar unreachable: {e}")
        sys.exit(1)

    # Fetch workspaces
    workspaces = client.list_workspaces()
    if args.workspace:
        workspaces = [w for w in workspaces if w["id"] == args.workspace]
        if not workspaces:
            print(f"✗ Workspace not found: {args.workspace}")
            sys.exit(1)

    print(f"\nReindexing {len(workspaces)} workspace(s)...\n")

    total_memories = 0
    total_nodes = 0
    errors = 0

    for ws in workspaces:
        ws_id = ws["id"]
        ws_name = ws.get("name", ws_id[:16])
        print(f"  Workspace: {ws_name} ({ws_id[:16]}...)")

        # ── Collect all items for this workspace ──
        batch_items = []

        # Memories
        try:
            memories = client._query("memory", workspace_id=ws_id)
            print(f"    Memories: {len(memories)}")
        except Exception as e:
            print(f"    ✗ Failed to query memories: {e}")
            continue

        for mem in memories:
            mem_id = mem.get("id", "")
            content = mem.get("content", "")
            if not content:
                continue
            batch_items.append({
                "workspace_id": ws_id,
                "entity_id": mem_id,
                "content": content,
                "entity_type": "memory",
            })

        # KG Nodes
        try:
            nodes = client._query("kg_node", workspace_id=ws_id)
            print(f"    KG Nodes: {len(nodes)}")
        except Exception as e:
            print(f"    ✗ Failed to query kg_node: {e}")
            continue

        for node in nodes:
            node_id = node.get("id", "")
            label = node.get("label", "")
            summary = node.get("summary", "")
            searchable = f"{label}: {summary}" if summary else label
            if not searchable.strip(": "):
                continue
            batch_items.append({
                "workspace_id": ws_id,
                "entity_id": node_id,
                "content": searchable,
                "entity_type": "node",
            })

        if args.dry_run:
            mem_count = sum(1 for i in batch_items if i["entity_type"] == "memory")
            node_count = sum(1 for i in batch_items if i["entity_type"] == "node")
            total_memories += mem_count
            total_nodes += node_count
            continue

        if not batch_items:
            continue

        # ── Send one batch request for this workspace ──
        try:
            resp = http.post(
                f"{args.tantivy_url}/index/batch",
                json={"items": batch_items},
                timeout=30.0,
            )
            if resp.status_code < 400:
                result = resp.json()
                count = result.get("count", len(batch_items))
                mem_count = sum(1 for i in batch_items if i["entity_type"] == "memory")
                node_count = sum(1 for i in batch_items if i["entity_type"] == "node")
                total_memories += mem_count
                total_nodes += node_count
                print(f"    ✓ Indexed {count} items ({mem_count} memories + {node_count} nodes)")
            else:
                errors += len(batch_items)
                print(f"    ✗ HTTP {resp.status_code} for workspace batch: {resp.text[:200]}")
        except Exception as e:
            errors += len(batch_items)
            print(f"    ✗ Failed to index workspace batch: {e}")

    print()
    if args.dry_run:
        print(f"  [DRY RUN] Would index {total_memories} memories + {total_nodes} nodes")
    else:
        print(f"  ✓ Indexed {total_memories} memories + {total_nodes} nodes")
        if errors:
            print(f"  ⚠ {errors} errors")
        # Verify
        health2 = http.get(f"{args.tantivy_url}/health", timeout=3.0).json()
        print(f"  Workspaces in Tantivy: {health2.get('workspace_count', '?')}")


if __name__ == "__main__":
    main()
