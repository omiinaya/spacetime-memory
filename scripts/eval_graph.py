#!/usr/bin/env python3
"""GBrain graph eval harness.

Seeds a known org-chart graph into a SpacetimeDB workspace, then runs
benchmarks against the knowledge-graph operations and reports metrics.

Operations benchmarked:
  - create_node        (latency, success rate)
  - create_edge        (latency, success rate)
  - query_graph        (label search — precision/recall at K)
  - get_neighbors      (correct neighbor retrieval)
  - graph_traverse     (BFS/DFS node retrieval by graph context)

Usage:
    python3 scripts/eval_graph.py --workspace-id <id>
    python3 scripts/eval_graph.py --workspace-id <id> --seed-only
    python3 scripts/eval_graph.py --workspace-id <id> --benchmark-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

from spacetime_memory import Client
from spacetime_memory.auth import generate_token

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB = "c2007f52296c94e0c7fb057d3cca532ce42a97a15b4820e0c60476a956be95ff"
TOKEN_PATH = "/tmp/stdb-data/jwt_priv_pk8.pem"
DEFAULT_BENCHMARK_ITERATIONS = 5

# Known seed graph: small organisation.
# Each entry: (label, summary, node_type)
SEED_NODES: list[tuple[str, str, str]] = [
    ("Alice", "CEO and co-founder of the company", "person"),
    ("Bob", "CTO, leads engineering team", "person"),
    ("Carol", "Senior engineer working on backend systems", "person"),
    ("Dave", "Senior engineer working on infrastructure", "person"),
    ("Eve", "Lead designer responsible for product design", "person"),
    ("Frank", "Product manager coordinating cross-team work", "person"),
]

# Each entry: (source_label, target_label, relation, fact)
SEED_EDGES: list[tuple[str, str, str, str]] = [
    ("Alice", "Bob", "reports_to", "Alice manages Bob"),
    ("Bob", "Carol", "leads", "Bob leads Carol"),
    ("Bob", "Dave", "leads", "Bob leads Dave"),
    ("Alice", "Eve", "reports_to", "Alice manages Eve"),
    ("Bob", "Frank", "works_with", "Bob works with Frank"),
    ("Carol", "Dave", "collaborates_with", "Carol collaborates with Dave"),
    ("Eve", "Carol", "works_with", "Eve works with Carol on product features"),
    ("Frank", "Eve", "works_with", "Frank works with Eve on requirements"),
    ("Frank", "Carol", "works_with", "Frank works with Carol on sprints"),
]

# Queries with known ground-truth node label matches.
# (query, expected_node_labels)
QUERY_GROUND_TRUTHS: list[tuple[str, list[str]]] = [
    ("Alice", ["Alice"]),
    ("Bob", ["Bob"]),
    ("CEO", ["Alice"]),         # Alice summary contains "CEO"
    ("CTO", ["Bob"]),           # Bob summary contains "CTO"
    ("engineer", ["Carol", "Dave"]),   # summaries contain "engineer"
]

# Neighbor ground truths: source_label -> set of target_labels
NEIGHBOR_GROUND_TRUTHS: dict[str, set[str]] = {
    "Alice": {"Bob", "Eve"},
    "Bob": {"Alice", "Carol", "Dave", "Frank"},
    "Carol": {"Bob", "Dave", "Eve", "Frank"},
    "Dave": {"Bob", "Carol"},
    "Eve": {"Alice", "Carol", "Frank"},
    "Frank": {"Bob", "Eve", "Carol"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ms() -> float:
    return time.monotonic() * 1000.0


def _make_client() -> Client:
    """Create an authenticated client pointing at the STDB."""
    token = generate_token(TOKEN_PATH)
    c = Client(host="localhost", port=3001, database=DB, token=token)
    # Login if needed
    try:
        c._call("login", ["eval_graph", "evalpass123"])
    except RuntimeError:
        try:
            c._call("register", ["eval_graph", "Eval Graph", "evalpass123"])
            c._call("login", ["eval_graph", "evalpass123"])
        except RuntimeError:
            pass
    return c


def _resolve_ws(c: Client, ws_id: str) -> str:
    """Return ws_id as-is — we trust the caller passes a valid UUID."""
    return ws_id


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_graph(c: Client, ws_id: str) -> dict[str, str]:
    """Create the known org-chart graph.

    Returns a dict mapping node label -> DB-assigned node uuid.
    """
    print(f"  Seeding graph into workspace {ws_id}...")

    # Create nodes
    node_ids: dict[str, str] = {}
    for label, summary, node_type in SEED_NODES:
        try:
            c.create_node(
                workspace_id=ws_id,
                label=label,
                node_type=node_type,
                summary=summary,
            )
        except RuntimeError as e:
            print(f"    WARN: create_node({label}) failed: {e}")
        # Query back to get assigned ID
        rows = c._query("kg_node", workspace_id=ws_id,
                        filter_dict={"label": label}, columns=["id", "label"])
        if rows:
            node_ids[label] = rows[-1]["id"]
            print(f"    Created node '{label}' -> id={rows[-1]['id'][:12]}...")
        else:
            print(f"    WARN: node '{label}' not found after creation")

    # Create edges
    for src_label, tgt_label, relation, fact in SEED_EDGES:
        src_id = node_ids.get(src_label)
        tgt_id = node_ids.get(tgt_label)
        if not src_id or not tgt_id:
            print(f"    SKIP edge {src_label}->{tgt_label} (missing node ids)")
            continue
        meta = json.dumps({"fact": fact})
        try:
            c.create_edge(
                workspace_id=ws_id,
                source_node_id=src_id,
                target_node_id=tgt_id,
                relation=relation,
                weight=1.0,
                metadata_json=meta,
            )
            print(f"    Created edge {src_label} -[{relation}]-> {tgt_label}")
        except RuntimeError as e:
            print(f"    WARN: create_edge({src_label},{tgt_label}) failed: {e}")

    # Wait briefly for indexing
    print("  Waiting 2s for indexing...")
    time.sleep(2)

    return node_ids


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

def benchmark_create_node(c: Client, ws_id: str,
                          iterations: int = DEFAULT_BENCHMARK_ITERATIONS,
                          label_prefix: str = "bench_node") -> dict:
    """Benchmark create_node latency and success rate."""
    latencies: list[float] = []
    successes = 0
    failures = 0

    for i in range(iterations):
        label = f"{label_prefix}_{i}_{_uuid.uuid4().hex[:6]}"
        start = _now_ms()
        try:
            c.create_node(workspace_id=ws_id, label=label,
                          node_type="benchmark", summary=f"Benchmark node {i}")
            latencies.append(_now_ms() - start)
            successes += 1
        except RuntimeError:
            latencies.append(_now_ms() - start)
            failures += 1

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    total = successes + failures
    return {
        "operation": "create_node",
        "iterations": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "avg_latency_ms": round(avg_lat, 2),
        "min_latency_ms": round(min(latencies), 2) if latencies else 0.0,
        "max_latency_ms": round(max(latencies), 2) if latencies else 0.0,
        "latencies_ms": [round(l, 2) for l in latencies],
    }


def benchmark_create_edge(c: Client, ws_id: str,
                          node_ids: dict[str, str],
                          iterations: int = DEFAULT_BENCHMARK_ITERATIONS) -> dict:
    """Benchmark create_edge latency and success rate using known nodes."""
    latencies: list[float] = []
    successes = 0
    failures = 0

    # Use first two nodes as sources/targets
    labels = list(node_ids.keys())
    if len(labels) < 2:
        return {"operation": "create_edge", "error": "Not enough nodes"}

    src_label = labels[0]
    tgt_label = labels[1]
    src_id = node_ids[src_label]
    tgt_id = node_ids[tgt_label]

    for i in range(iterations):
        relation = f"bench_rel_{i}"
        meta = json.dumps({"fact": f"{src_label} {relation} {tgt_label}"})
        start = _now_ms()
        try:
            c.create_edge(
                workspace_id=ws_id,
                source_node_id=src_id,
                target_node_id=tgt_id,
                relation=relation,
                weight=1.0,
                metadata_json=meta,
            )
            latencies.append(_now_ms() - start)
            successes += 1
        except RuntimeError:
            latencies.append(_now_ms() - start)
            failures += 1

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    total = successes + failures
    return {
        "operation": "create_edge",
        "iterations": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "avg_latency_ms": round(avg_lat, 2),
        "min_latency_ms": round(min(latencies), 2) if latencies else 0.0,
        "max_latency_ms": round(max(latencies), 2) if latencies else 0.0,
        "latencies_ms": [round(l, 2) for l in latencies],
    }


def benchmark_query_graph(c: Client, ws_id: str,
                          all_node_labels: set[str]) -> dict:
    """Benchmark query_graph label search precision/recall.

    Runs QUERY_GROUND_TRUTHS against query_graph() and calculates
    P@K and R@K for each query.
    """
    per_query: list[dict] = []
    overall_true_positives = 0
    overall_false_positives = 0
    overall_false_negatives = 0

    for query, expected_labels in QUERY_GROUND_TRUTHS:
        start = _now_ms()
        try:
            results = c.query_graph(workspace_id=ws_id, query=query)
        except RuntimeError as e:
            results = []
        latency_ms = _now_ms() - start

        found_labels = set(r.get("label", "") for r in results)

        true_positives = len(found_labels & set(expected_labels))
        false_positives = len(found_labels - set(expected_labels))
        false_negatives = len(set(expected_labels) - found_labels)

        overall_true_positives += true_positives
        overall_false_positives += false_positives
        overall_false_negatives += false_negatives

        precision = true_positives / (true_positives + false_positives) \
            if (true_positives + false_positives) > 0 else 0.0
        recall = true_positives / (true_positives + false_negatives) \
            if (true_positives + false_negatives) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) \
            if (precision + recall) > 0 else 0.0

        per_query.append({
            "query": query,
            "expected_labels": expected_labels,
            "found_labels": sorted(found_labels),
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "latency_ms": round(latency_ms, 2),
        })

    total_expected = overall_true_positives + overall_false_negatives
    total_retrieved = overall_true_positives + overall_false_positives
    macro_p = overall_true_positives / total_retrieved \
        if total_retrieved > 0 else 0.0
    macro_r = overall_true_positives / total_expected \
        if total_expected > 0 else 0.0
    macro_f1 = 2 * macro_p * macro_r / (macro_p + macro_r) \
        if (macro_p + macro_r) > 0 else 0.0

    return {
        "operation": "query_graph",
        "queries": len(QUERY_GROUND_TRUTHS),
        "macro_precision": round(macro_p, 4),
        "macro_recall": round(macro_r, 4),
        "macro_f1": round(macro_f1, 4),
        "per_query": per_query,
    }


def benchmark_get_neighbors(c: Client, ws_id: str,
                            node_ids: dict[str, str]) -> dict:
    """Benchmark get_neighbors correctness against NEIGHBOR_GROUND_TRUTHS."""
    per_node: list[dict] = []
    overall_correct = 0
    overall_expected = 0
    overall_retrieved = 0
    latencies: list[float] = []

    for node_label, expected_targets in NEIGHBOR_GROUND_TRUTHS.items():
        node_id = node_ids.get(node_label)
        if not node_id:
            per_node.append({
                "node": node_label,
                "error": "Node ID not found (not seeded?)",
            })
            continue

        start = _now_ms()
        try:
            edges = c.get_neighbors(node_id, workspace_id=ws_id)
        except RuntimeError:
            edges = []
        latency_ms = _now_ms() - start
        latencies.append(latency_ms)

        # Extract unique neighbor labels from edges
        neighbor_labels: set[str] = set()
        for e in edges:
            src_lab = e.get("source_label", "")
            tgt_lab = e.get("target_label", "")
            if src_lab == node_label:
                neighbor_labels.add(tgt_lab)
            elif tgt_lab == node_label:
                neighbor_labels.add(src_lab)
            else:
                # Edge between two other nodes — shouldn't happen but track
                pass

        correct = len(neighbor_labels & expected_targets)
        extra = neighbor_labels - expected_targets
        missing = expected_targets - neighbor_labels

        overall_correct += correct
        overall_expected += len(expected_targets)
        overall_retrieved += len(neighbor_labels)

        per_node.append({
            "node": node_label,
            "expected_neighbors": sorted(expected_targets),
            "found_neighbors": sorted(neighbor_labels),
            "correct": correct,
            "extra": sorted(extra),
            "missing": sorted(missing),
            "latency_ms": round(latency_ms, 2),
        })

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    precision = overall_correct / overall_retrieved \
        if overall_retrieved > 0 else 0.0
    recall = overall_correct / overall_expected \
        if overall_expected > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) \
        if (precision + recall) > 0 else 0.0

    return {
        "operation": "get_neighbors",
        "nodes_tested": len(per_node),
        "total_expected_neighbors": overall_expected,
        "total_correct": overall_correct,
        "avg_latency_ms": round(avg_lat, 2),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "per_node": per_node,
    }


def benchmark_traverse(c: Client, ws_id: str,
                       node_ids: dict[str, str]) -> dict:
    """Benchmark 'traversal' by calling query_graph with broader context.

    Uses the MCP-like query_graph() with a known label to see how
    many relevant nodes are reachable from a starting point.
    """
    if not node_ids:
        return {"operation": "graph_traverse", "error": "No nodes"}

    # Pick Alice as the root
    alice_id = node_ids.get("Alice")
    if not alice_id:
        return {"operation": "graph_traverse", "error": "Alice node not found"}

    # Count how many nodes are reachable within the workspace
    start = _now_ms()
    try:
        # query_graph with empty query returns ALL nodes in workspace
        all_nodes = c.query_graph(workspace_id=ws_id, query="")
    except RuntimeError:
        all_nodes = []
    all_nodes_latency = _now_ms() - start

    # Get Alice's immediate neighbors as a proxy for 1-hop BFS
    start = _now_ms()
    try:
        alice_edges = c.get_neighbors(alice_id, workspace_id=ws_id)
    except RuntimeError:
        alice_edges = []
    neighbor_latency = _now_ms() - start

    # Count unique nodes reachable from Alice within 1 hop
    reachable_labels: set[str] = set()
    for e in alice_edges:
        src = e.get("source_label", "")
        tgt = e.get("target_label", "")
        if src:
            reachable_labels.add(src)
        if tgt:
            reachable_labels.add(tgt)

    seed_labels = {n[0] for n in SEED_NODES}
    total_seeded = len(seed_labels)
    reachable_count = len(reachable_labels)

    return {
        "operation": "graph_traverse",
        "total_nodes_in_workspace": len(all_nodes),
        "seed_nodes_expected": total_seeded,
        "seed_nodes_found": len([n for n in all_nodes
                                  if n.get("label", "") in seed_labels]),
        "alice_1hop_reachable": reachable_count,
        "alice_expected_neighbors": len(NEIGHBOR_GROUND_TRUTHS.get("Alice", set())),
        "alice_neighbor_latency_ms": round(neighbor_latency, 2),
        "all_nodes_latency_ms": round(all_nodes_latency, 2),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GBrain graph evaluation harness",
    )
    parser.add_argument(
        "--workspace-id", required=True,
        help="SpacetimeDB workspace UUID to use",
    )
    parser.add_argument(
        "--seed-only", action="store_true",
        help="Only seed the graph, skip benchmarks",
    )
    parser.add_argument(
        "--benchmark-only", action="store_true",
        help="Only run benchmarks (skip seeding)",
    )
    parser.add_argument(
        "--iterations", type=int, default=DEFAULT_BENCHMARK_ITERATIONS,
        help=f"Number of iterations per benchmark (default: {DEFAULT_BENCHMARK_ITERATIONS})",
    )
    parser.add_argument(
        "--output", default="",
        help="Write JSON report to file (default: stdout only)",
    )
    args = parser.parse_args()

    ws_id = args.workspace_id

    print("=" * 60)
    print("GBrain Graph Evaluation Harness")
    print("=" * 60)
    print(f"Workspace: {ws_id}")
    print(f"Database:  {DB}")
    print(f"Iterations per benchmark: {args.iterations}")
    print()

    # Make client
    print("Connecting to SpacetimeDB...")
    c = _make_client()
    print("  Connected.")
    print()

    # Ensure workspace exists
    try:
        c._call("create_workspace", ["Eval Graph", "GBrain graph eval", ws_id])
    except RuntimeError:
        pass

    node_ids: dict[str, str] = {}

    # Seed phase
    if not args.benchmark_only:
        node_ids = seed_graph(c, ws_id)
        print(f"  Seeded {len(node_ids)} nodes.")
        print()

        if args.seed_only:
            print("Seed-only mode. Exiting.")
            return

    # Benchmark phase
    print("-" * 60)
    print("Running benchmarks...")
    print("-" * 60)

    results: dict[str, dict] = {}

    # If we didn't just seed, query existing nodes
    if not node_ids:
        print("  Fetching existing nodes from workspace...")
        node_rows = c._query("kg_node", workspace_id=ws_id,
                             columns=["id", "label"])
        for r in node_rows:
            lbl = r.get("label", "")
            uid = r.get("id", "")
            if lbl and uid:
                node_ids[lbl] = uid
        print(f"  Found {len(node_ids)} existing nodes.")

    all_seeded_labels = {n[0] for n in SEED_NODES}

    # 1. create_node benchmark
    print("\n[1/5] Benchmark: create_node ...")
    results["create_node"] = benchmark_create_node(
        c, ws_id, iterations=args.iterations,
    )
    r = results["create_node"]
    print(f"       Success rate: {r['success_rate']:.1%}  "
          f"Avg latency: {r['avg_latency_ms']}ms  "
          f"({r['successes']}/{r['iterations']})")

    # 2. create_edge benchmark
    print("\n[2/5] Benchmark: create_edge ...")
    results["create_edge"] = benchmark_create_edge(
        c, ws_id, node_ids, iterations=args.iterations,
    )
    if "error" not in results["create_edge"]:
        r = results["create_edge"]
        print(f"       Success rate: {r['success_rate']:.1%}  "
              f"Avg latency: {r['avg_latency_ms']}ms  "
              f"({r['successes']}/{r['iterations']})")
    else:
        print(f"       ERROR: {results['create_edge']['error']}")

    # 3. query_graph benchmark (label search)
    print("\n[3/5] Benchmark: query_graph (label search) ...")
    results["query_graph"] = benchmark_query_graph(c, ws_id, all_seeded_labels)
    r = results["query_graph"]
    print(f"       Macro P@K={r['macro_precision']:.3f}  "
          f"R@K={r['macro_recall']:.3f}  F1={r['macro_f1']:.3f}")
    for pq in r["per_query"]:
        p_str = f"P={pq['precision']:.3f}" if pq['true_positives'] > 0 else "P=N/A"
        r_str = f"R={pq['recall']:.3f}" if pq['true_positives'] + pq['false_negatives'] > 0 else "R=N/A"
        print(f"         '{pq['query']}': {p_str} {r_str} "
              f"({pq['true_positives']} TP, {pq['false_positives']} FP, "
              f"{pq['false_negatives']} FN) [{pq['latency_ms']}ms]")

    # 4. get_neighbors benchmark
    print("\n[4/5] Benchmark: get_neighbors ...")
    results["get_neighbors"] = benchmark_get_neighbors(c, ws_id, node_ids)
    r = results["get_neighbors"]
    print(f"       Precision={r['precision']:.3f}  "
          f"Recall={r['recall']:.3f}  F1={r['f1_score']:.3f}  "
          f"Avg latency: {r['avg_latency_ms']}ms")
    for pn in r["per_node"]:
        if "error" in pn:
            print(f"         {pn['node']}: ERROR - {pn['error']}")
        else:
            extra_s = f" +{pn['extra']}" if pn["extra"] else ""
            miss_s = f" -{pn['missing']}" if pn["missing"] else ""
            print(f"         {pn['node']}: {pn['correct']}/{len(pn['expected_neighbors'])} correct"
                  f"{extra_s}{miss_s} [{pn['latency_ms']}ms]")

    # 5. graph_traverse benchmark
    print("\n[5/5] Benchmark: graph_traverse ...")
    results["graph_traverse"] = benchmark_traverse(c, ws_id, node_ids)
    r = results["graph_traverse"]
    if "error" not in r:
        print(f"       Total nodes in workspace: {r['total_nodes_in_workspace']}")
        print(f"       Seeded nodes found: {r['seed_nodes_found']}/{r['seed_nodes_expected']}")
        print(f"       Alice 1-hop reachable neighbors: {r['alice_1hop_reachable']} "
              f"(expected {r['alice_expected_neighbors']})")
    else:
        print(f"       ERROR: {r['error']}")

    print()
    print("=" * 60)
    print("Benchmark Complete")
    print("=" * 60)

    # Build summary
    summary = {
        "workspace_id": ws_id,
        "database": DB,
        "iterations_per_benchmark": args.iterations,
        "results": results,
    }

    # Output structured JSON
    json_report = json.dumps(summary, indent=2, default=str)

    if args.output:
        with open(args.output, "w") as f:
            f.write(json_report)
        print(f"\nJSON report written to: {args.output}")
    else:
        print("\nJSON report:\n")
        print(json_report)

    # Human-readable summary table
    print()
    print("─" * 60)
    print("SUMMARY")
    print("─" * 60)
    ops = [
        ("create_node", "Success rate", "success_rate", "{:.1%}"),
        ("create_node", "Avg latency", "avg_latency_ms", "{:.1f}ms"),
        ("create_edge", "Success rate", "success_rate", "{:.1%}"),
        ("create_edge", "Avg latency", "avg_latency_ms", "{:.1f}ms"),
        ("query_graph", "Macro P@K", "macro_precision", "{:.3f}"),
        ("query_graph", "Macro R@K", "macro_recall", "{:.3f}"),
        ("query_graph", "Macro F1", "macro_f1", "{:.3f}"),
        ("get_neighbors", "Precision", "precision", "{:.3f}"),
        ("get_neighbors", "Recall", "recall", "{:.3f}"),
        ("get_neighbors", "Avg latency", "avg_latency_ms", "{:.1f}ms"),
    ]
    for op, label, key, fmt in ops:
        if op in results and key in results[op]:
            val = results[op][key]
            if val is not None:
                print(f"  {op:20s} {label:15s} {fmt}".format(val))


if __name__ == "__main__":
    main()
