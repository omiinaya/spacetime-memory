#!/usr/bin/env python3
"""GBrain-style retrieval eval harness.

Benchmarks search quality against GBrain's published metrics:
  - P@5: Precision at 5 (how many of top 5 results are relevant)
  - R@5: Recall at 5 (how many of all relevant results are in top 5)
  - MRR: Mean Reciprocal Rank

GBrain published: P@5=49.1%, R@5=97.9% (146K pages, 24K people, 5K companies).

Usage:
    python3 scripts/eval_harness.py [--workspace-id <id>] [--queries-file <path>]

The queries file should be JSONL with lines like:
    {"query": "What do we know about Alice Chen?", "relevant_ids": ["mem-1", "mem-3"]}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

for prefix in (".", "..", "/home/user/spacetime-memory"):
    sdk_path = os.path.join(prefix, "sdk/python")
    if os.path.isdir(sdk_path):
        sys.path.insert(0, sdk_path)
        break

from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get(
    "SPACETIMEDB_DB",
    "c20012b2679f860fd6caf3f6fc1274e8552ed2e8f99084eefad95516b61d1f72",
)

# GBrain-hardcoded benchmark queries (simulated — real eval needs labeled data)
DEFAULT_QUERIES = [
    {
        "query": "Acme AI leadership",
        "description": "Who leads Acme AI?",
    },
    {
        "query": "funding rounds",
        "description": "What funding has been raised?",
    },
    {
        "query": "Alice Chen background",
        "description": "What is Alice Chen's background?",
    },
    {
        "query": "product platform",
        "description": "What product are they building?",
    },
    {
        "query": "Stripe connection",
        "description": "Connection to Stripe?",
    },
]


def _c() -> Client:
    client = Client(host=HOST, port=PORT, database=DB)
    token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cron_identity_token")
    if os.path.exists(token_file):
        try:
            with open(token_file) as f:
                client._identity_token = f.read().strip()
                client._identity_established = True
        except Exception:
            pass
    return client


def run_hybrid_search(
    client: Client,
    workspace_id: str,
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Run hybrid search via the SDK client (handles embedding + strategy dispatch)."""
    try:
        results = client.search(workspace_id, query=query, limit=k, semantic=True)
        return results[:k]
    except Exception as e:
        print(f"  Search error: {e}")
        return []


def evaluate_precision_at_k(
    results: list[dict[str, Any]],
    relevant_ids: set[str],
    k: int = 5,
) -> float:
    """P@k: fraction of top-k results that are relevant."""
    if not results:
        return 0.0
    top_k = results[:k]
    relevant = sum(1 for r in top_k if r.get("entity_id", r.get("id", "")) in relevant_ids)
    return relevant / min(k, len(top_k))


def evaluate_recall_at_k(
    results: list[dict[str, Any]],
    relevant_ids: set[str],
    k: int = 5,
) -> float:
    """R@k: fraction of all relevant items retrieved in top-k."""
    if not relevant_ids:
        return 0.0
    top_k = results[:k]
    retrieved = sum(1 for r in top_k if r.get("entity_id", r.get("id", "")) in relevant_ids)
    return retrieved / len(relevant_ids)


def evaluate_mrr(
    results: list[dict[str, Any]],
    relevant_ids: set[str],
) -> float:
    """MRR: 1 / rank of first relevant result."""
    for i, r in enumerate(results, 1):
        if r.get("entity_id", r.get("id", "")) in relevant_ids:
            return 1.0 / i
    return 0.0


def run_eval(
    client: Client,
    workspace_id: str,
    queries: list[dict[str, Any]],
    k: int = 5,
) -> dict[str, Any]:
    """Run full eval harness against a workspace."""
    p_at_k: list[float] = []
    r_at_k: list[float] = []
    mrr_vals: list[float] = []
    results: dict[str, Any] = {"queries": []}

    for q in queries:
        query_text = q["query"]
        relevant_ids = set(q.get("relevant_ids", []))
        description = q.get("description", "")

        search_results = run_hybrid_search(client, workspace_id, query_text, k=k)

        p = evaluate_precision_at_k(search_results, relevant_ids, k)
        r = evaluate_recall_at_k(search_results, relevant_ids, k)
        mrr = evaluate_mrr(search_results, relevant_ids) if relevant_ids else 0.0

        p_at_k.append(p)
        r_at_k.append(r)
        mrr_vals.append(mrr)

        results["queries"].append({
            "query": query_text,
            "description": description,
            "results_count": len(search_results),
            f"P@{k}": p,
            f"R@{k}": r,
            "MRR": mrr,
        })

        print(f"  {query_text[:40]:<40}  P@{k}={p:.1%}  R@{k}={r:.1%}  MRR={mrr:.2f}")

    n = len(p_at_k) if p_at_k else 1
    avg_p = sum(p_at_k) / n
    avg_r = sum(r_at_k) / n
    avg_mrr = sum(mrr_vals) / n

    results["summary"] = {
        f"P@{k}": avg_p,
        f"R@{k}": avg_r,
        "MRR": avg_mrr,
        "queries_evaluated": len(queries),
        "note": "Without labeled relevant_ids, P/R metrics are 0.0 (baseline only).",
    }

    print(f"\n  Average: P@{k}={avg_p:.1%}  R@{k}={avg_r:.1%}  MRR={avg_mrr:.2f}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="GBrain-style retrieval eval harness")
    parser.add_argument("--workspace-id", required=True, help="Target workspace")
    parser.add_argument(
        "--queries-file", default=None,
        help="JSONL file with queries and relevant_ids",
    )
    parser.add_argument("--k", type=int, default=5, help="K for P@K and R@K")
    args = parser.parse_args()

    client = _c()

    if args.queries_file and os.path.exists(args.queries_file):
        queries = []
        with open(args.queries_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    queries.append(json.loads(line))
    else:
        queries = DEFAULT_QUERIES

    print(f"Eval Harness — {len(queries)} queries, K={args.k}")
    print(f"Workspace: {args.workspace_id[:16]}...")
    print()

    results = run_eval(client, args.workspace_id, queries, k=args.k)

    # Save results
    out_path = f"/tmp/eval_results_{int(time.time())}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved: {out_path}")


if __name__ == "__main__":
    main()
