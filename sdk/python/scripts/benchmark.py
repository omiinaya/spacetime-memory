#!/usr/bin/env python3
"""Performance benchmark for Spacetime-Memory.

Measures p50/p90/p99 latency for core operations against a live
SpacetimeDB standalone with the module published.

Usage:
    python scripts/benchmark.py                   # 10 iterations per op
    python scripts/benchmark.py --iterations 50    # 50 iterations per op
    python scripts/benchmark.py --output results.md
"""

from __future__ import annotations

import argparse
import os
import socket
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Add repo root so we can import the SDK and the CLI helpers
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Also add the SDK package directory so ``from spacetime_memory …`` works
_sdk_root = _repo_root / "sdk" / "python"
if str(_sdk_root) not in sys.path:
    sys.path.insert(0, str(_sdk_root))

from spacetime_memory import Client

# ---------------------------------------------------------------------------
# Helpers (mirroring conftest.py patterns)
# ---------------------------------------------------------------------------


def _running_stdb() -> bool:
    """Check whether a SpacetimeDB standalone is listening on localhost:3001."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(2)
        s.connect(("127.0.0.1", 3001))
        return True
    except (ConnectionRefusedError, OSError):
        return False
    finally:
        s.close()


def _publish_module(delete_data: str = "on-conflict") -> str:
    """Publish the WASM module via HTTP API and return the database identity.

    Uses anonymous HTTP API publish (same approach as updated conftest.py).
    """
    module_dir = _repo_root / "server" / "spacetimedb"
    if not module_dir.exists():
        raise RuntimeError(
            f"Module directory {module_dir} not found. "
            "Run this script from the repo root or check the path."
        )

    wasm_path = (
        module_dir / "target" / "wasm32-unknown-unknown" / "release"
        / "spacetime_memory.opt.wasm"
    )
    if not wasm_path.exists():
        wasm_path = (
            module_dir / "target" / "wasm32-unknown-unknown" / "release"
            / "spacetime_memory.wasm"
        )
    if not wasm_path.exists():
        raise RuntimeError(f"WASM module not found at {wasm_path}. Build first.")

    wasm_data = wasm_path.read_bytes()
    import httpx

    # Establish anonymous identity
    anon = httpx.get(
        "http://127.0.0.1:3001/v1/database/anon-probe", timeout=5.0,
    )
    token = anon.headers.get("spacetime-identity-token", "")

    headers = {"Content-Type": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = "http://127.0.0.1:3001/v1/database?host_type=Wasm"
    if delete_data == "always":
        url += "&delete_data=true"

    resp = httpx.post(url, headers=headers, content=wasm_data, timeout=60.0)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Publish via HTTP API failed (HTTP {resp.status_code}):\n{resp.text[:500]}"
        )

    data = resp.json()
    if "Success" in data:
        return data["Success"].get("database_identity", "spacetime-memory")
    if "Database" in data:
        return data["Database"].get("database_identity", "spacetime-memory")
    if isinstance(data, dict):
        for key in ("database_identity", "identity"):
            if key in data:
                return data[key]
    return "spacetime-memory"


def _get_client() -> Client:
    """Create a connected Client to a freshly published database.

    Uses anonymous identity (no JWT) — same approach as updated conftest.py.
    """
    force = os.environ.get("SPACETIMEDB_HOST", "")
    if not force and not _running_stdb():
        print(
            "ERROR: SpacetimeDB standalone is not running on localhost:3001.\n"
            "Start it first or set SPACETIMEDB_HOST to point to a running instance.",
            file=sys.stderr,
        )
        sys.exit(1)

    db_identity = _publish_module(delete_data="always")

    return Client(
        host=os.environ.get("SPACETIMEDB_HOST", "localhost"),
        port=os.environ.get("SPACETIMEDB_PORT", "3001"),
        database=db_identity,
    )


def _generate_test_token() -> str:
    """Generate a JWT token from the project's key pair."""
    key_path = _repo_root / "data" / "id_ecdsa_pkcs8.pem"
    if not key_path.exists():
        return ""
    try:
        from spacetime_memory.auth import generate_token
        return generate_token(str(key_path))
    except ImportError:
        return ""


# ---------------------------------------------------------------------------
# Latency measurement
# ---------------------------------------------------------------------------


def measure(label: str, fn: Callable[[], Any], n: int = 10) -> dict[str, Any]:
    """Run *fn* *n* times and return p50/p90/p99 statistics in ms."""
    latencies: list[float] = []
    failures = 0
    for i in range(n):
        t0 = time.perf_counter()
        try:
            fn()
            dt = time.perf_counter() - t0
            latencies.append(dt * 1000.0)  # convert to ms
        except Exception as e:
            failures += 1
            print(f"  WARN: {label} iteration {i + 1} failed: {e}", file=sys.stderr)

    if not latencies:
        return {
            "label": label,
            "n": 0,
            "failures": failures,
            "p50_ms": float("nan"),
            "p90_ms": float("nan"),
            "p99_ms": float("nan"),
            "mean_ms": float("nan"),
            "min_ms": float("nan"),
            "max_ms": float("nan"),
        }

    latencies.sort()
    return {
        "label": label,
        "n": len(latencies),
        "failures": failures,
        "p50_ms": _percentile(latencies, 50),
        "p90_ms": _percentile(latencies, 90),
        "p99_ms": _percentile(latencies, 99),
        "mean_ms": statistics.mean(latencies),
        "min_ms": latencies[0],
        "max_ms": latencies[-1],
    }


def _percentile(sorted_data: list[float], p: int) -> float:
    """Approximate percentile for small samples (same as numpy default)."""
    if not sorted_data:
        return float("nan")
    k = (p / 100.0) * (len(sorted_data) - 1)
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] * (1 - c) + sorted_data[f + 1] * c
    return sorted_data[-1]


# ---------------------------------------------------------------------------
# Benchmark suite
# ---------------------------------------------------------------------------


def run_benchmarks(client: Client, iterations: int) -> list[dict[str, Any]]:
    """Run all benchmarks against *client*.

    Returns a list of result dicts (one per benchmark) that can be formatted
    into a Markdown table.
    """
    results: list[dict[str, Any]] = []

    print(f"\nRunning benchmarks ({iterations} iterations each)...\n")

    # ---- Setup workspace ----
    ws_id = "benchmark-workspace"
    print("  Setting up workspace...")
    try:
        # Try to create or use existing workspace
        ws = client.list_workspaces()
        if not any(w.get("workspace_id") == ws_id or w.get("name") == ws_id for w in ws):
            try:
                client.create_workspace(ws_id)
            except RuntimeError:
                pass  # may already exist
    except Exception:
        client.create_workspace(ws_id)

    # The workspace_id may be the name we passed (the reducer generates it)
    # Let's re-fetch to confirm
    ws_list = client.list_workspaces()
    workspace_id = ws_id
    for w in ws_list:
        if w.get("name") == ws_id:
            workspace_id = w.get("workspace_id") or w.get("id") or ws_id
            break
        if w.get("workspace_id") == ws_id:
            workspace_id = ws_id
            break

    # -----------------------------------------------------------------------
    # 1. Memory store (single item)
    # -----------------------------------------------------------------------

    def single_store(content: str = "") -> Callable[[], Any]:
        """Return a closure that stores a single short memory."""
        _i = [0]

        def _fn() -> Any:
            _i[0] += 1
            return client.store(
                workspace_id,
                content=f"Benchmark memory {_i[0]} — {content or 'short text'}",
                memory_type="experience",
            )
        return _fn

    results.append(
        measure("memory.store (single, short text)", single_store("short text"), n=iterations)
    )

    # -----------------------------------------------------------------------
    # 2. Memory store (long text)
    # -----------------------------------------------------------------------
    long_text = (
        "This is a longer benchmark memory text that simulates a more realistic "
        "memory payload containing several sentences of contextual information "
        "about the agent's conversation or observations. " * 20
    )
    results.append(
        measure("memory.store (single, long text)", single_store(long_text), n=iterations)
    )

    # -----------------------------------------------------------------------
    # 3. Batch store (10 items)
    # -----------------------------------------------------------------------
    def batch_store(n_items: int) -> Callable[[], Any]:
        """Return a closure that stores *n_items* memories sequentially."""
        _counter = [0]

        def _fn() -> None:
            _counter[0] += 1
            batch_num = _counter[0]
            for j in range(n_items):
                client.store(
                    workspace_id,
                    content=f"Benchmark batch #{batch_num} item #{j} — batch of {n_items}",
                    memory_type="experience",
                )
        return _fn

    results.append(
        measure("memory.store (batch 10)", batch_store(10), n=iterations)
    )
    results.append(
        measure("memory.store (batch 100)", batch_store(100), n=iterations)
    )
    results.append(
        measure("memory.store (batch 1000)", batch_store(1000), n=max(1, iterations // 2))
    )

    # Pre-populate some data for search benchmarks
    print("  Populating data for search benchmarks...")
    for j in range(50):
        try:
            client.store(
                workspace_id,
                content=f"Searchable memory #{j} — The quick brown fox jumps over the lazy dog. "
                        f"Machine learning and artificial intelligence are transforming technology.",
                memory_type="experience",
            )
        except RuntimeError:
            pass
    # Add a few KG nodes for graph queries
    node_ids = []
    for label in ["machine-learning", "artificial-intelligence", "natural-language-processing",
                   "computer-vision", "reinforcement-learning", "robotics", "deep-learning"]:
        try:
            r = client.create_node(workspace_id, label, node_type="concept",
                                   summary=f"A concept node for {label}")
            # Try to get the node ID
            nodes = client._sql(
                f"SELECT id FROM kg_node WHERE label = '{label.replace(chr(39), chr(39)+chr(39))}' "
                f"AND workspace_id = '{workspace_id.replace(chr(39), chr(39)+chr(39))}'"
            )
            if nodes:
                node_ids.append(nodes[0]["id"])
        except RuntimeError:
            pass
    # Create edges between nodes
    for i in range(len(node_ids) - 1):
        try:
            client.create_edge(workspace_id, node_ids[i], node_ids[i + 1],
                               relation="related_to", weight=1.0)
        except RuntimeError:
            pass

    # -----------------------------------------------------------------------
    # 4. Semantic search
    # -----------------------------------------------------------------------
    def semantic_search() -> Any:
        return client.search(workspace_id, "machine learning AI", semantic=True, limit=5)

    results.append(
        measure("search.semantic (top-5)", semantic_search, n=iterations)
    )

    # -----------------------------------------------------------------------
    # 5. BM25 / Keyword search
    # -----------------------------------------------------------------------
    def keyword_search() -> Any:
        return client.search(workspace_id, "brown fox", semantic=False, limit=5)

    results.append(
        measure("search.keyword (top-5)", keyword_search, n=iterations)
    )

    # -----------------------------------------------------------------------
    # 6. Hybrid search
    # -----------------------------------------------------------------------
    def hybrid_search() -> Any:
        return client.search(workspace_id, "AI technology", semantic=True, limit=10)

    results.append(
        measure("search.hybrid (top-10)", hybrid_search, n=iterations)
    )

    # -----------------------------------------------------------------------
    # 7. Graph queries
    # -----------------------------------------------------------------------
    if node_ids:
        def query_graph() -> Any:
            return client.query_graph(workspace_id, "machine")

        results.append(
            measure("graph.query (label search)", query_graph, n=iterations)
        )

        def get_neighbors() -> Any:
            return client.get_neighbors(node_ids[0])

        results.append(
            measure("graph.get_neighbors", get_neighbors, n=iterations)
        )

        def get_community() -> Any:
            return client.get_community(0)

        results.append(
            measure("graph.get_community", get_community, n=iterations)
        )

    # -----------------------------------------------------------------------
    # 8. SQL read (direct)
    # -----------------------------------------------------------------------
    def sql_read() -> Any:
        return client._sql("SELECT COUNT(*) AS cnt FROM memory")

    results.append(
        measure("sql.read (COUNT)", sql_read, n=iterations)
    )

    # -----------------------------------------------------------------------
    # 9. Ping (round-trip)
    # -----------------------------------------------------------------------
    def ping() -> Any:
        return client.ping()

    results.append(
        measure("ping (round-trip)", ping, n=iterations)
    )

    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def format_markdown(results: list[dict[str, float]]) -> str:
    """Render benchmark results as a Markdown table."""
    lines = [
        "# Spacetime-Memory Benchmark Results\n",
    ]

    # Summary header
    lines.append("## Latency Summary\n")
    lines.append("| Operation | Samples | Failures | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for r in results:
        label = r.get("label", "?")
        n = r.get("n", 0)
        failures = r.get("failures", 0)
        p50 = r.get("p50_ms", float("nan"))
        p90 = r.get("p90_ms", float("nan"))
        p99 = r.get("p99_ms", float("nan"))
        mean = r.get("mean_ms", float("nan"))
        mn = r.get("min_ms", float("nan"))
        mx = r.get("max_ms", float("nan"))

        def _fmt(v: float) -> str:
            if v != v:  # NaN check
                return "—"
            return f"{v:.1f}"

        lines.append(
            f"| `{label}` | {n} | {failures} "
            f"| {_fmt(p50)} | {_fmt(p90)} | {_fmt(p99)} "
            f"| {_fmt(mean)} | {_fmt(mn)} | {_fmt(mx)} |"
        )

    # Interpretive notes
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- **Batch store** benchmarks run *n* individual `store_memory` calls sequentially to")
    lines.append("  simulate bulk-insert patterns. The latency shown is for the entire batch.")
    lines.append("- **Semantic search** calls the embedder (proxy → NVIDIA NIM) and then")
    lines.append("  runs a hybrid search reducer on SpacetimeDB.")
    lines.append("- **Keyword search** (semantic=False) fetches all active memories from the workspace")
    lines.append("  and filters client-side, since SpacetimeDB SQL does not support `LIKE`.")
    lines.append("- **Graph queries** measure KG label search, neighbour traversal, and community lookup.")
    lines.append("- p50/p90/p99 are calculated from sorted latencies using linear interpolation.")
    lines.append("- Benchmarks require a running SpacetimeDB standalone on `localhost:3001` and the")
    lines.append("  module published. See [docs/PERFORMANCE.md](../docs/PERFORMANCE.md) for details.")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Spacetime-Memory performance.",
    )
    parser.add_argument(
        "-n", "--iterations", type=int, default=10,
        help="Number of iterations per operation (default: 10)",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Write results as Markdown to this file (default: print to stdout)",
    )
    parser.add_argument(
        "--token", type=str, default=None,
        help="Optional JWT token for authenticated requests",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Spacetime-Memory Performance Benchmark")
    print("=" * 60)

    # Connect
    print("\nChecking SpacetimeDB standalone...")
    client = _get_client()

    # Ping to warm up
    print("Warming up (ping)...")
    client.ping()

    # Run
    results = run_benchmarks(client, iterations=args.iterations)

    # Format
    md = format_markdown(results)

    if args.output:
        Path(args.output).write_text(md)
        print(f"\nResults written to: {args.output}")
    else:
        print("\n" + md)

    print("\nDone.")


if __name__ == "__main__":
    main()
