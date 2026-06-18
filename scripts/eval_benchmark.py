#!/usr/bin/env python3
"""GBrain-style eval harness — 50 memories, 25 labeled queries.

Seeds a test workspace, runs benchmarks at 3 config levels,
and prints P@5 / R@5 / MRR for each.

Usage:
    python3 scripts/eval_benchmark.py [--workspace-id <id>]
"""
from __future__ import annotations

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

# ── Config ──────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
MEMORIES_FILE = os.path.join(DATA_DIR, "eval_memories_50.json")
QUERIES_FILE = os.path.join(DATA_DIR, "eval_queries_25.json")

# Load reranker credentials from Hermes .env
_env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("LITELLM_MASTER_KEY="):
                _, _key = _line.split("=", 1)
                os.environ["LLM_RERANK_API_KEY"] = _key.strip().strip('"').strip("'")
                break
os.environ.setdefault("LLM_RERANK_ENDPOINT", "http://192.168.1.111:4000/v1")
os.environ.setdefault("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")


def compute_metrics(
    queries: list[dict],
    results_by_query: dict[str, list[dict]],
) -> dict[str, float]:
    """Compute P@5, R@5, MRR."""
    precision_sum = 0.0
    recall_sum = 0.0
    reciprocal_rank_sum = 0.0
    n = len(queries)

    for q in queries:
        qid = q["query"]
        relevant = set(q["relevant_ids"])
        if not relevant:
            n -= 1
            continue

        results = results_by_query.get(qid, [])
        top5_ids = [r.get("id", r.get("entity_id", "")) for r in results[:5]]

        # Precision@5
        hits = sum(1 for rid in top5_ids if rid in relevant)
        precision_sum += hits / min(5, len(relevant))

        # Recall@5
        recall_sum += hits / len(relevant)

        # MRR
        for rank, rid in enumerate(top5_ids, start=1):
            if rid in relevant:
                reciprocal_rank_sum += 1.0 / rank
                break

    if n == 0:
        return {"P@5": 0, "R@5": 0, "MRR": 0}
    return {
        "P@5": round(precision_sum / n, 4),
        "R@5": round(recall_sum / n, 4),
        "MRR": round(reciprocal_rank_sum / n, 4),
    }


def seed_memories(client: Client, workspace_id: str, memories: list[dict]) -> int:
    """Store eval memories. Returns count of successfully stored."""
    stored = 0
    for m in memories:
        try:
            client.store(
                workspace_id=workspace_id,
                content=m["content"],
                memory_type=m.get("type", "experience"),
            )
            stored += 1
            # Brief pause to avoid hammering STDB
            if stored % 10 == 0:
                print(f"  Seeded {stored}/{len(memories)}...")
        except Exception as e:
            print(f"  WARNING: Failed to store memory {m['id']}: {e}")
    print(f"  Stored {stored}/{len(memories)} memories")
    return stored


def run_queries(
    client: Client,
    workspace_id: str,
    queries: list[dict],
    *,
    semantic: bool = True,
    rerank: bool = False,
) -> dict[str, list[dict]]:
    """Run all queries and return results keyed by query text."""
    results_by_query: dict[str, list[dict]] = {}
    for i, q in enumerate(queries):
        try:
            results = client.search(
                workspace_id=workspace_id,
                query=q["query"],
                limit=20,
                semantic=semantic,
                rerank=rerank,
            )
            results_by_query[q["query"]] = results
        except Exception as e:
            print(f"  WARNING: Query '{q['query'][:50]}' failed: {e}")
            results_by_query[q["query"]] = []
        if (i + 1) % 5 == 0:
            print(f"  Ran {i+1}/{len(queries)} queries...")
    return results_by_query


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Spacetime Memory eval benchmark")
    parser.add_argument("--workspace-id", default="eval-bench-50", help="Workspace ID for eval")
    args = parser.parse_args()

    # Load data
    with open(MEMORIES_FILE) as f:
        memories = json.load(f)
    with open(QUERIES_FILE) as f:
        queries = json.load(f)

    print(f"Eval dataset: {len(memories)} memories, {len(queries)} queries")
    total_relevant = sum(len(q["relevant_ids"]) for q in queries)
    print(f"Relevance judgments: {total_relevant} (avg {total_relevant/len(queries):.1f}/query)")

    client = Client()

    # Register + login (token captured automatically from response headers)
    import uuid as _uuid
    user = f"eval_{_uuid.uuid4().hex[:8]}"
    try:
        client._call("register", [user, "Eval", "evalpass123"])
    except RuntimeError:
        pass
    try:
        client._call("login", [user, "evalpass123"])
    except RuntimeError:
        pass
    # Become admin
    try:
        who = client._whoami()
        client._call("set_initial_admin", [who])
    except RuntimeError:
        pass

    workspace_id = args.workspace_id

    # Create workspace (required before storing memories)
    try:
        client.create_workspace("Eval Benchmark", "50-memory eval dataset", id=workspace_id)
        print(f"Created workspace: {workspace_id}")
    except RuntimeError:
        print(f"Workspace {workspace_id} already exists")

    # Seed data
    print(f"\nSeeding workspace '{workspace_id}'...")
    seed_memories(client, workspace_id, memories)

    # Allow indexing to settle
    print("\nWaiting for indexing (5s)...")
    time.sleep(5)

    # ── Config 1: BM25 + graph + temporal (no embeddings) ──
    print("\n── Config 1: BM25 + graph + temporal (no semantic) ──")
    # Temporarily disable embedder by setting URL to something unreachable
    old_embedder = client.embedder_url
    client.embedder_url = "http://localhost:19999"  # nonexistent
    results_non = run_queries(client, workspace_id, queries, semantic=False)
    metrics_non = compute_metrics(queries, results_non)
    print(f"  P@5={metrics_non['P@5']:.1%}  R@5={metrics_non['R@5']:.1%}  MRR={metrics_non['MRR']:.3f}")
    client.embedder_url = old_embedder

    # ── Config 2: + semantic embeddings ──
    print("\n── Config 2: + semantic embeddings (BGE-M3 or MiniLM) ──")
    results_sem = run_queries(client, workspace_id, queries, semantic=True, rerank=False)
    metrics_sem = compute_metrics(queries, results_sem)
    print(f"  P@5={metrics_sem['P@5']:.1%}  R@5={metrics_sem['R@5']:.1%}  MRR={metrics_sem['MRR']:.3f}")

    # ── Config 3: + LLM reranking ──
    print("\n── Config 3: + LLM reranking (ds-deepseek-v4-flash) ──")
    results_rerank = run_queries(client, workspace_id, queries, semantic=True, rerank=True)
    metrics_rerank = compute_metrics(queries, results_rerank)
    print(f"  P@5={metrics_rerank['P@5']:.1%}  R@5={metrics_rerank['R@5']:.1%}  MRR={metrics_rerank['MRR']:.3f}")

    # ── Summary table ──
    print("\n" + "=" * 60)
    print(f"{'Config':<45} {'P@5':>6} {'R@5':>6} {'MRR':>6}")
    print("-" * 60)
    print(f"{'BM25 + graph + temporal':<45} {metrics_non['P@5']:>6.1%} {metrics_non['R@5']:>6.1%} {metrics_non['MRR']:>6.3f}")
    print(f"{'+ semantic embeddings':<45} {metrics_sem['P@5']:>6.1%} {metrics_sem['R@5']:>6.1%} {metrics_sem['MRR']:>6.3f}")
    print(f"{'+ LLM reranking':<45} {metrics_rerank['P@5']:>6.1%} {metrics_rerank['R@5']:>6.1%} {metrics_rerank['MRR']:>6.3f}")
    print("-" * 60)
    print(f"\nGBrain reference (146K pages): P@5=49.1%, R@5=97.9%")
    print(f"Our previous (25 memories):    P@5=55.5%, R@5=94.4%, MRR=0.898")

    # Save results
    results_path = os.path.join(DATA_DIR, "eval_results_50.json")
    with open(results_path, "w") as f:
        json.dump({
            "dataset": {"memories": len(memories), "queries": len(queries)},
            "metrics": {
                "bm25_only": metrics_non,
                "semantic": metrics_sem,
                "reranked": metrics_rerank,
            },
            "timestamp": time.time(),
        }, f, indent=2)
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    main()
