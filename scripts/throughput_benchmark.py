#!/usr/bin/env python3
"""Throughput / QPS benchmark for Spacetime Memory.

Measures queries per second under concurrent load — a metric NO competitor
publishes, giving us an opportunity to dominate this dimension.

Usage:
    python3 scripts/throughput_benchmark.py [--concurrency 1 4 8 16 32]
    python3 scripts/throughput_benchmark.py --quick
"""

import json
import os
import sys
import time
import math
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://localhost:3001")
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")
TANTIVY_URL = os.environ.get("TANTIVY_URL", "http://localhost:9091")
DB = os.environ.get(
    "SPACETIMEDB_DB",
    "c20076381c624767a61e93ef07b3a8f2a2f012f11d5312a479dbcecc72066e5c",
)

# Sample queries of increasing complexity
SAMPLE_QUERIES = [
    "machine learning",
    "reinforcement learning from human feedback",
    "transformer neural network architecture",
    "how does attention mechanism work in large language models",
    "convolutional neural networks for image recognition",
    "batch normalization and dropout regularization",
    "long short term memory networks",
    "generative adversarial networks training",
    "transfer learning fine tuning pre trained models",
    "gradient descent optimization algorithms",
    "python programming data science",
    "database indexing query optimization",
    "distributed systems consensus algorithms",
    "memory retrieval augmented generation RAG",
    "vector embeddings semantic similarity search",
]

SAMPLE_MEMORIES = [
    "Rust is a systems programming language focused on safety and performance.",
    "Python is widely used for data science and machine learning applications.",
    "SpacetimeDB provides a global database with deterministic reducers for game backend logic.",
    "The Transformer architecture uses self-attention mechanisms to process sequential data.",
    "Reinforcement learning trains agents through trial and error interactions with environments.",
    "Knowledge graphs represent entities and their relationships in a structured format.",
    "BM25 is a ranking function used by search engines to estimate document relevance.",
    "Cosine similarity measures the angle between two vectors in embedding space.",
    "Hybrid search combines keyword matching with semantic vector similarity for better results.",
    "Tantivy is a full-text search engine library written in Rust, similar to Lucene.",
    "BGE-M3 is a multi-lingual embedding model supporting dense and sparse retrieval.",
    "Rate limiting controls the rate of traffic sent or received by a network interface.",
    "JWTs (JSON Web Tokens) are used for stateless authentication in web APIs.",
    "Redis is an in-memory data structure store used as a cache and message broker.",
    "PostgreSQL is an advanced open-source relational database with JSON support.",
    "Docker containers encapsulate applications and their dependencies for reproducible deployment.",
    "Kubernetes orchestrates containerized applications across clusters of machines.",
    "gRPC is a high-performance RPC framework using Protocol Buffers for serialization.",
    "WebAssembly enables near-native performance for web applications.",
    "REST APIs use HTTP methods to perform CRUD operations on resources.",
]


class ClientPool:
    """Thread-safe pool of pre-authenticated clients."""

    def __init__(self, size: int):
        self._clients: list[Client] = []
        self._lock = threading.Lock()
        self._index = 0
        for _ in range(size):
            try:
                resp = httpx.get(f"{STDB_URL}/v1/database/{DB}", timeout=10)
                token = resp.headers.get("spacetime-identity-token", "")
                identity = resp.headers.get("spacetime-identity", "")
                c = Client(
                    database=DB,
                    embedder_url=EMBEDDER_URL,
                    token=token or None,
                )
                try:
                    c._call("register", [
                        f"throughput-{os.urandom(4).hex()}",
                        "benchmark789",
                        identity,
                    ])
                except (RuntimeError, OSError, json.JSONDecodeError):
                    pass
                ws = c.create_workspace(
                    f"throughput-bench-{os.urandom(4).hex()}",
                    "Throughput Benchmark Workspace",
                )
                ws_id = ws.get("id") or ws.get("workspace_id", "")
                if ws_id:
                    # Seed initial memories
                    for mem_text in SAMPLE_MEMORIES:
                        try:
                            c.store(
                                workspace_id=ws_id,
                                content=mem_text,
                                memory_type="benchmark",
                                confidence=0.9,
                            )
                        except (OSError, json.JSONDecodeError):
                            pass
                    # Index in Tantivy
                    try:
                        all_mems = c._query("memory", workspace_id=ws_id)
                        for m in all_mems:
                            mem_id = m.get("id", "")
                            content = m.get("content", "")
                            if mem_id and content:
                                try:
                                    httpx.post(
                                        f"{TANTIVY_URL}/index",
                                        json={
                                            "workspace_id": ws_id,
                                            "entity_id": mem_id,
                                            "content": content,
                                            "entity_type": "memory",
                                        },
                                        timeout=5,
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    self._clients.append((c, ws_id, token))
            except Exception as e:
                print(f"  [POOL] Failed to create client: {e}", file=sys.stderr)
        if not self._clients:
            raise RuntimeError("Could not create any authenticated clients")

    def acquire(self) -> tuple[Client, str, str]:
        with self._lock:
            c = self._clients[self._index % len(self._clients)]
            self._index += 1
            return c


def benchmark_single_op(client: Client, ws_id: str, op: str, query: str = "") -> float:
    """Execute a single operation and return latency in ms."""
    t0 = time.time()
    try:
        if op == "store":
            client.store(
                workspace_id=ws_id,
                content=f"Throughput test memory at {time.time()}",
                memory_type="benchmark",
                confidence=0.9,
            )
        elif op == "semantic_search":
            client.search(
                workspace_id=ws_id,
                query=query or "machine learning",
                limit=5,
                semantic=True,
                rerank=False,
            )
        elif op == "keyword_search":
            client.search(
                workspace_id=ws_id,
                query=query or "machine learning",
                limit=5,
                semantic=False,
                rerank=False,
            )
        elif op == "hybrid_search":
            client.search(
                workspace_id=ws_id,
                query=query or "machine learning",
                limit=10,
                semantic=True,
                rerank=False,
            )
        elif op == "graph_query":
            # _query returns all rows — no limit param
            client._query("memory", workspace_id=ws_id, columns=["id", "content"])
        elif op == "create_workspace":
            client.create_workspace(
                f"perf-{os.urandom(4).hex()}",
                "Performance workspace",
            )
        else:
            return -1.0
    except (OSError, json.JSONDecodeError, RuntimeError):
        return -1.0
    return (time.time() - t0) * 1000


def run_concurrency_level(
    concurrency: int,
    duration_secs: int = 10,
) -> dict:
    """Run benchmark at a given concurrency level for a fixed duration."""
    pool_size = max(concurrency, 4)
    pool = ClientPool(pool_size)

    queries_per_op = {}
    latencies_per_op = defaultdict(list)
    start_time = time.time()
    deadline = start_time + duration_secs

    ops = ["store", "semantic_search", "keyword_search", "graph_query"]
    op_cycle = 0

    def worker():
        nonlocal op_cycle
        local_start = time.time()
        ops_done = 0
        while time.time() < deadline:
            try:
                client, ws_id, _ = pool.acquire()
                op = ops[op_cycle % len(ops)]
                op_cycle += 1
                latency = benchmark_single_op(client, ws_id, op)
                if latency >= 0:
                    latencies_per_op[op].append(latency)
                    ops_done += 1
            except Exception:
                pass
        return ops_done, time.time() - local_start

    workers = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker) for _ in range(concurrency)]
        for f in as_completed(futures):
            workers.append(f.result())

    total_ops = sum(w[0] for w in workers)
    total_time = max(w[1] for w in workers)
    qps = total_ops / total_time if total_time > 0 else 0

    results = {
        "concurrency": concurrency,
        "duration_secs": duration_secs,
        "total_operations": total_ops,
        "total_wall_time": round(total_time, 2),
        "qps_overall": round(qps, 1),
        "per_operation": {},
    }

    for op in ops:
        lats = latencies_per_op.get(op, [])
        if lats:
            lats_sorted = sorted(lats)
            n = len(lats_sorted)
            p50 = lats_sorted[n // 2] if n > 0 else 0
            p90 = lats_sorted[int(n * 0.9)] if n > 0 else 0
            p99 = lats_sorted[int(n * 0.99)] if n > 0 else 0
            results["per_operation"][op] = {
                "count": n,
                "p50_ms": round(p50, 1),
                "p90_ms": round(p90, 1),
                "p99_ms": round(p99, 1),
                "mean_ms": round(sum(lats) / n, 1),
                "min_ms": round(min(lats), 1),
                "max_ms": round(max(lats), 1),
            }

    # Expose per-op QPS
    for op in ops:
        count = results["per_operation"].get(op, {}).get("count", 0)
        if count > 0:
            results["per_operation"][op]["qps"] = round(count / total_time, 1)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Throughput / QPS Benchmark")
    parser.add_argument(
        "--concurrency", type=str, default="1,4,8,16,32,64",
        help="Comma-separated concurrency levels to test",
    )
    parser.add_argument("--duration", type=int, default=10, help="Duration per concurrency level (seconds)")
    parser.add_argument("--quick", action="store_true", help="Quick mode: fewer levels, shorter duration")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    if args.quick:
        concurrency_levels = [1, 4, 16]
        duration = 5
    else:
        concurrency_levels = [int(x) for x in args.concurrency.split(",")]
        duration = args.duration

    print("=" * 65)
    print("  THROUGHPUT / QPS BENCHMARK")
    print("  Measures queries per second under concurrent load")
    print("=" * 65)
    print(f"  Concurrency levels: {concurrency_levels}")
    print(f"  Duration per level: {duration}s")
    print(f"  Ops: store, semantic_search, keyword_search, graph_query")
    print()

    all_results = {}
    for c in concurrency_levels:
        print(f"\n--- Concurrency={c} ---")
        result = run_concurrency_level(c, duration)
        all_results[c] = result

        qps = result["qps_overall"]
        print(f"  Overall QPS: {qps:.1f}")
        for op, stats in result["per_operation"].items():
            print(f"    {op}: {stats['qps']:.1f} qps  (p50={stats['p50_ms']}ms, p90={stats['p90_ms']}ms)")

    # Summary
    print("\n" + "=" * 65)
    print("  QPS SCALING SUMMARY")
    print("=" * 65)
    print(f"  {'Concurrency':>12} {'QPS':>10} {'Store':>10} {'Semantic':>10} {'Keyword':>10} {'Graph':>10}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for c in concurrency_levels:
        r = all_results[c]
        s = r["per_operation"]
        print(f"  {c:>12} {r['qps_overall']:>10.1f} "
              f"{s.get('store',{}).get('qps','-'):>10} "
              f"{s.get('semantic_search',{}).get('qps','-'):>10} "
              f"{s.get('keyword_search',{}).get('qps','-'):>10} "
              f"{s.get('graph_query',{}).get('qps','-'):>10}")

    output_path = args.output or os.path.join(
        Path(__file__).resolve().parent.parent,
        f"benchmark_results_throughput_{int(time.time())}.json",
    )
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
