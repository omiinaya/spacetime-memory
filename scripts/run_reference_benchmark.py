#!/usr/bin/env python3
"""Regenerate PERFORMANCE.md 'Reference Results (Full Suite)'.

Replicates sdk/python/scripts/benchmark.py's suite — the 10 ops shown in the
PERFORMANCE.md/benchmarks.md Reference Results table, at the documented
methodology: 20 iterations per op, 3 for the expensive semantic ops.

Phased execution (each phase is bounded so it survives any long-run watchdog):

  python3 scripts/run_reference_benchmark.py setup   # publish fresh DB + auth + singles + batch10
  python3 scripts/run_reference_benchmark.py batch   # batch 100 (the long one)
  python3 scripts/run_reference_benchmark.py search  # seed + semantic/keyword/hybrid + graph/sql/ping + save

State (published DB id + workspace id) persists in /tmp/refbench_state.json.

Safe: publishes a FRESH database via HTTP API (delete_data=never — no existing
data touched).
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sdk" / "python"))
sys.path.insert(0, str(REPO / "sdk" / "python" / "scripts"))

from spacetime_memory import Client  # noqa: E402
from benchmark import measure, _get_client  # noqa: E402

STATE = Path("/tmp/refbench_state.json")
USER, PASS = "bench_user", "benchpass123"
WS_NAME = "benchmark-workspace"


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {}


def save_state(**kw) -> None:
    st = load_state()
    st.update(kw)
    STATE.write_text(json.dumps(st, indent=2))


def auth_client(client: Client) -> None:
    try:
        client._call("login", [USER, PASS])
    except RuntimeError:
        client._call("register", [USER, "Bench User", PASS])
        client._call("login", [USER, PASS])


def _guard(client: Client, fn):
    """Re-auth + retry once on 'Not authenticated'.

    The module's ``login`` reducer re-links the account to the *calling*
    identity, so any concurrent login as the same user (another process,
    a dashboard probe) silently steals the account and turns every later
    call into "Not authenticated".  Guarding the benchmark fns makes each
    phase resilient instead of crashing the whole run.
    """
    def wrapped():
        try:
            return fn()
        except RuntimeError as e:
            if "Not authenticated" not in str(e):
                raise
            auth_client(client)
            return fn()
    return wrapped


def resolve_workspace(client: Client) -> str:
    try:
        client.create_workspace(WS_NAME)
    except RuntimeError:
        pass
    for w in client.list_workspaces():
        if w.get("name") == WS_NAME:
            return w.get("workspace_id") or w.get("id") or WS_NAME
    return WS_NAME


def single_store(client: Client, ws: str, content: str = ""):
    i = [0]

    def fn():
        i[0] += 1
        return client.store(ws, content=f"Benchmark memory {i[0]} — {content or 'short text'}",
                            memory_type="experience")
    return fn


def batch_store(client: Client, ws: str, n: int):
    co = [0]

    def fn():
        co[0] += 1
        b = co[0]
        for j in range(n):
            client.store(ws, content=f"Benchmark batch #{b} item #{j} — batch of {n}",
                         memory_type="experience")
    return fn


def phase_setup() -> None:
    st = load_state()
    if st.get("database"):
        # Idempotent: reuse the already-published DB (skips slow republish)
        print(f"Reusing published DB {st['database'][:16]}...", flush=True)
        client = Client(host="127.0.0.1", port="3001", database=st["database"])
        client.ping()
        auth_client(client)
        ws = st["workspace"]
    else:
        print("Publishing fresh DB (delete_data=never)...", flush=True)
        client = _get_client()
        client.ping()
        auth_client(client)
        print(f"Authenticated: {client._whoami()}", flush=True)
        ws = resolve_workspace(client)
        print(f"Workspace: {ws}", flush=True)
        save_state(database=getattr(client, "database", "?"), workspace=ws)

    results = [
        measure("memory.store (single, short)", _guard(client, single_store(client, ws, "short text")), n=20),
        measure("memory.store (single, long)", _guard(client, single_store(client, ws, "L" * 5000)), n=20),
        measure("memory.store (batch 10)", _guard(client, batch_store(client, ws, 10)), n=20),
    ]
    for r in results:
        print(f"  [{r['label']}] p50={r['p50_ms']:.1f}ms fails={r['failures']}", flush=True)
    save_state(results=[r for r in results])


def phase_batch() -> None:
    st = load_state()
    client = Client(host="127.0.0.1", port="3001", database=st["database"])
    auth_client(client)
    ws = st["workspace"]
    print(f"Batch 100 on {st['database'][:16]}... (20 iters, ~7 min)", flush=True)
    r = measure("memory.store (batch 100)", _guard(client, batch_store(client, ws, 100)), n=20)
    print(f"  [{r['label']}] p50={r['p50_ms']:.1f}ms fails={r['failures']}", flush=True)
    st["results"] = st.get("results", []) + [r]
    save_state(**st)


def phase_search() -> None:
    st = load_state()
    client = Client(host="127.0.0.1", port="3001", database=st["database"])
    auth_client(client)
    ws = st["workspace"]

    for j in range(50):
        try:
            client.store(ws, content=f"Searchable memory #{j} — The quick brown fox jumps over the lazy dog. "
                                     "Machine learning and artificial intelligence are transforming technology.",
                         memory_type="experience")
        except RuntimeError:
            pass
    node_ids = []
    for label in ["machine-learning", "artificial-intelligence", "natural-language-processing",
                  "computer-vision", "reinforcement-learning", "robotics", "deep-learning"]:
        try:
            client.create_node(ws, label, node_type="concept", summary=f"A concept node for {label}")
            nodes = client._sql(
                f"SELECT id FROM kg_node WHERE label = '{label.replace(chr(39), chr(39)+chr(39))}' "
                f"AND workspace_id = '{ws.replace(chr(39), chr(39)+chr(39))}'"
            )
            if nodes:
                node_ids.append(nodes[0]["id"])
        except RuntimeError:
            pass
    for i in range(len(node_ids) - 1):
        try:
            client.create_edge(ws, node_ids[i], node_ids[i + 1], relation="related_to", weight=1.0)
        except RuntimeError:
            pass
    print(f"  seeded {len(node_ids)} KG nodes", flush=True)

    results = st.get("results", [])
    results.append(measure("search.semantic (top-5)",
                           _guard(client, lambda: client.search(ws, "machine learning AI", semantic=True, limit=5)), n=3))
    print("  done semantic", flush=True)
    results.append(measure("search.keyword (top-5)",
                           _guard(client, lambda: client.search(ws, "brown fox", semantic=False, limit=5)), n=20))
    print("  done keyword", flush=True)
    results.append(measure("search.hybrid (top-10)",
                           _guard(client, lambda: client.search(ws, "AI technology", semantic=True, limit=10)), n=3))
    print("  done hybrid", flush=True)
    if node_ids:
        results.append(measure("graph.query", _guard(client, lambda: client.query_graph(ws, "machine")), n=20))
    results.append(measure("sql.read (COUNT)", _guard(client, lambda: client._sql("SELECT COUNT(*) AS cnt FROM memory")), n=20))
    results.append(measure("ping (round-trip)", _guard(client, lambda: client.ping()), n=20))

    ts = time.strftime("%Y%m%d_%H%M%S")
    out = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": "127.0.0.1", "port": "3001",
        "database": st["database"], "workspace_id": ws,
        "iterations": 20, "semantic_iterations": 3,
        "embedder_available": True, "tantivy_available": True,
        "latency": [
            {"label": r["label"], "n": r["n"], "fails": r["failures"],
             "p50": round(r["p50_ms"], 1), "p90": round(r["p90_ms"], 1),
             "p99": round(r["p99_ms"], 1), "mean": round(r["mean_ms"], 1),
             "min": round(r["min_ms"], 1), "max": round(r["max_ms"], 1)}
            for r in results
        ],
    }
    json_path = REPO / f"benchmark_results_{ts}.json"
    json_path.write_text(json.dumps(out, indent=2))
    print(f"\nSaved: {json_path.name}", flush=True)
    print("| # | Operation | p50 (ms) | p90 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms)", flush=True)
    print("|---|-----------|---------:|---------:|---------:|----------:|---------:|---------:", flush=True)
    for i, r in enumerate(results, 1):
        print(f"| {i} | {r['label']} | {r['p50_ms']:.1f} | {r['p90_ms']:.1f} | {r['p99_ms']:.1f} "
              f"| {r['mean_ms']:.1f} | {r['min_ms']:.1f} | {r['max_ms']:.1f}", flush=True)
    total_n = sum(r["n"] for r in results)
    total_f = sum(r["failures"] for r in results)
    print(f"**Failures:** {total_f}/{total_n} ({total_f / max(total_n, 1) * 100:.1f}%)", flush=True)


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "setup"
    {"setup": phase_setup, "batch": phase_batch, "search": phase_search}[phase]()
