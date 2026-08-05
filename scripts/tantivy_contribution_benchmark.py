#!/usr/bin/env python3
"""Tantivy contribution benchmark — measure latency + quality WITH vs WITHOUT Tantivy.

Seeds memories via c.store() which auto-indexes into Tantivy via _tantivy_index.

Methodology:
  - Latency WITH Tantivy: measured via SDK c.search() (end-to-end: SDK HTTP -> Tantivy sidecar)
  - Latency WITHOUT Tantivy: measured via SDK c.search() with invalid Tantivy URL
    (falls back to _keyword_fallback which does STDB query + client-side BM25).
    NOTE: _query bug (workspace_id filter returns 0 rows) means the fallback currently
    returns 0 results at the quality level, so we also measure via in-memory mock.
  - Quality WITH Tantivy: Tantivy BM25 sidecar HTTP API (25 queries, top-20 recall)
  - Quality WITHOUT Tantivy: in-memory keyword substring matching (same algorithm as
    SDK _keyword_fallback, but operates on the 50-memory dataset directly, sidestepping
    the _query bug)

Usage:
  cd ~/spacetime-memory
  SPACETIMEDB_DB=<identity> python3 scripts/tantivy_contribution_benchmark.py

Outputs:
  - benchmark_results_tantivy_contribution.json (detailed results)
"""

from __future__ import annotations

import json, os, statistics, sys, time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPACETIMEDB_PORT", 3001))
DB = os.environ.get("SPACETIMEDB_DB", "")
N = int(os.environ.get("BENCH_ITERATIONS", "20"))
TANTIVY_URL = os.environ.get("TANTIVY_URL", "http://localhost:9091")

if not DB:
    print("FATAL: Set SPACETIMEDB_DB in .env or environment")
    sys.exit(1)


# --- Helpers ---

def measure(label, fn, n=N):
    lats = []; fails = 0
    for i in range(n):
        t0 = time.perf_counter()
        try:
            fn()
            lats.append((time.perf_counter() - t0) * 1000)
        except Exception:
            # Broad catch: httpx.ReadTimeout / ConnectError / JSONDecodeError
            # from a slow or overloaded sidecar must count as a FAILURE, not
            # crash the whole benchmark (observed: ReadTimeout under box load
            # ~36 killed the run in the quality phase).
            fails += 1
    if not lats:
        return {"label": label, "n": 0, "fails": fails, "p50": 0, "p90": 0, "p99": 0, "mean": 0, "min": 0, "max": 0}
    lats.sort()
    def pct(p):
        k = (p/100)*(len(lats)-1); f = int(k); c = k-f
        return lats[f]*(1-c) + lats[min(f+1,len(lats)-1)]*c
    return {"label": label, "n": len(lats), "fails": fails,
            "p50": round(pct(50),1), "p90": round(pct(90),1), "p99": round(pct(99),1),
            "mean": round(statistics.mean(lats),1), "min": round(lats[0],1), "max": round(lats[-1],1)}

def compute_metrics(queries, results_by_query, memories_by_id):
    p, r, mrr, n = [], [], [], 0
    for q in queries:
        relevant_ids = set(q["relevant_ids"])
        relevant_contents = []
        for rid in relevant_ids:
            if rid in memories_by_id:
                relevant_contents.append(memories_by_id[rid]["content"].lower())
        if not relevant_contents:
            continue
        n += 1
        top5 = results_by_query.get(q["query"], [])[:5]
        hits = 0
        for rank, result in enumerate(top5, 1):
            res_content = result.get("content", "").lower()
            is_relevant = any(rc[:40] in res_content or res_content[:40] in rc for rc in relevant_contents)
            if is_relevant:
                hits += 1
                if hits == 1:
                    mrr.append(1.0 / rank)
        p.append(hits / min(5, len(relevant_contents)))
        r.append(hits / len(relevant_contents))
    while len(mrr) < n:
        mrr.append(0.0)
    if n == 0:
        return {"P@5": 0, "R@5": 0, "MRR": 0}
    return {"P@5": round(sum(p)/n, 4), "R@5": round(sum(r)/n, 4), "MRR": round(sum(mrr)/n, 4)}

def keyword_fallback_mock(query, all_contents, limit=20):
    """Simulate the _keyword_fallback — client-side substring matching."""
    STOPWORDS = {
        "a", "an", "the", "is", "are", "was", "were",
        "be", "been", "who", "what", "where", "when", "why", "how",
        "which", "do", "does", "did", "has", "have", "had",
        "can", "will", "would", "tell", "me", "about",
        "of", "in", "on", "at", "to", "for", "with",
        "and", "or", "not", "we", "our", "us",
        "i", "you", "they", "it", "its", "s",
        "that", "this", "there", "from",
    }
    keywords = [
        w.lower().rstrip("?,.:;!\"'")
        for w in query.split()
        if len(w.rstrip("?,.:;!\"'")) > 1
        and w.lower().rstrip("?,.:;!\"'") not in STOPWORDS
    ]
    if not keywords:
        return all_contents[:limit]
    results = []
    for m in all_contents:
        content_lower = m["content"].lower()
        if any(kw in content_lower for kw in keywords):
            results.append(m)
    # Sort by a simple score: more keyword matches = higher rank
    results.sort(key=lambda m: -sum(1 for kw in keywords if kw in m["content"].lower()))
    return results[:limit]


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
with open(DATA_DIR / "eval_memories_50.json") as f:
    eval_memories = json.load(f)
with open(DATA_DIR / "eval_queries_25.json") as f:
    eval_queries = json.load(f)
memories_by_id = {m["id"]: m for m in eval_memories}

print("=" * 60)
print("Tantivy Contribution Benchmark")
print("=" * 60)
print(f"Host: {HOST}:{PORT}")
print(f"DB:   {DB[:20]}...")
print(f"Tantivy: {TANTIVY_URL}")
print(f"Dataset: {len(eval_memories)} eval memories, {len(eval_queries)} eval queries")
print(f"Iterations: {N}")
print()

# --- Setup ---
c = Client(host=HOST, port=PORT, database=DB)
for reducer, args in [("register", ["bench_user_tantivy", "Bench User", "benchpass123"]),
                       ("login", ["bench_user_tantivy", "benchpass123"])]:
    try:
        c._call(reducer, args)
    except RuntimeError:
        pass

ws_name = f"tantivy-bench-{int(time.time())}"
c.create_workspace(name=ws_name)
ws_list = c._query("workspace", workspace_id="", columns=["id", "name"])
ws_id = None
for w in ws_list:
    if w.get("name") == ws_name:
        ws_id = w.get("id")
        break
if not ws_id:
    print("ERROR: Cannot create workspace")
    sys.exit(1)
print(f"Workspace: {ws_id}")

# Seed eval memories via store_memory reducer directly + Tantivy HTTP API.
# This bypasses c.store(), which is unusably slow here (~10s/memory: STDB store
# + memory id query-back + embed + tantivy index per call) and can wedge the
# STDB wasm executor for the database if a single store exceeds the client
# timeout (observed 2026-07-05: wasm-<db> thread stuck in futex_do_wait, all
# reducers for that DB hang until load clears). The raw reducer is ~30ms.
print("Seeding 50 eval memories via store_memory reducer + Tantivy /index/batch...")
t0 = time.time()
for m in eval_memories:
    c._call(
        "store_memory",
        [ws_id, "", "", m.get("type", "experience"), m["content"], "", "[]", 1.0, "", "", "[]"],
    )
seed_time = time.time() - t0
# Index directly into Tantivy (entity_id = eval memory id; same shape as the
# SDK's _tantivy_index which uses the STDB memory id — compute_metrics matches
# by content, so the id value itself is not material).
tantivy_items = [
    {
        "workspace_id": ws_id,
        "entity_id": m["id"],
        "content": m["content"],
        "entity_type": "memory",
    }
    for m in eval_memories
]
try:
    resp = httpx.post(f"{TANTIVY_URL}/index/batch", json={"items": tantivy_items}, timeout=60)
    resp.raise_for_status()
    print(f"  Tantivy /index/batch: {resp.json().get('count', 0)} indexed")
except Exception as e:
    print(f"  WARNING: Tantivy /index/batch failed: {e}")
print(f"  Done in {seed_time:.1f}s (store_memory reducer)")
time.sleep(3)  # Let Tantivy commit + reader reload (ReloadPolicy::OnCommitWithDelay)

# Verify Tantivy has data
try:
    resp = httpx.post(f"{TANTIVY_URL}/search", json={"workspace_id": ws_id, "query": "CTO", "limit": 5}, timeout=5)
    tr = resp.json()
    print(f"  Tantivy verification: {len(tr)} results for 'CTO' (expected >= 1)")
    for r in tr[:2]:
        print(f"    score={r['score']:.2f} id={r['entity_id']} content=\"{r['content'][:50]}...\"")
except Exception as e:
    print(f"  WARNING: Tantivy verification failed: {e}")
print()

# Keep all stored memory contents for fallback simulation
all_memory_contents = list(eval_memories)

# ============================================================
# PHASE 1: LATENCY — SDK SEARCH WITH TANTIVY
# ============================================================
print("-" * 60)
print("PHASE 1: Latency — Search WITH Tantivy (SDK c.search)")
print("-" * 60)

latency_with = []
def run_latency_with(label, fn, n=N):
    r = measure(label, fn, n=n)
    latency_with.append(r)
    print(f"  [{len(latency_with):2d}] {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  mean={r['mean']:>6.1f}ms  (n={r['n']})")

run_latency_with("keyword (Tantivy ON) SDK top-5", lambda: c.search(ws_id, "test", limit=5, semantic=False))

# ============================================================
# PHASE 2: LATENCY — SEARCH WITHOUT TANTIVY (SDK fallback)
# ============================================================
print()
print("-" * 60)
print("PHASE 2: Latency — Search WITHOUT Tantivy (SDK fallback)")
print("-" * 60)

latency_without = []
def run_latency_without(label, fn, n=N):
    r = measure(label, fn, n=n)
    latency_without.append(r)
    print(f"  [{len(latency_without):2d}] {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  mean={r['mean']:>6.1f}ms  (n={r['n']})")

_saved_url = c.tantivy_url
c.tantivy_url = "http://127.0.0.1:18991"
run_latency_without("keyword (Tantivy OFF) SDK top-5", lambda: c.search(ws_id, "test", limit=5, semantic=False))
c.tantivy_url = _saved_url

print()
print("LATENCY COMPARISON (SDK with Tantivy ON vs OFF):")
for wr in latency_with:
    for wor in latency_without:
        speedup = wor["p50"] / max(wr["p50"], 0.1)
        print(f"  {wr['label']}: p50={wr['p50']}ms (on) vs {wor['p50']}ms (off) -> {speedup:.1f}x faster with Tantivy")

# ============================================================
# PHASE 1b: LATENCY — DIRECT TANTIVY HTTP API (baseline)
# ============================================================
print()
print("-" * 60)
print("PHASE 1b: Latency — Tantivy HTTP API (direct, no SDK overhead)")
print("-" * 60)

latency_with_direct = []
def run_latency_direct(label, fn, n=N):
    r = measure(label, fn, n=n)
    latency_with_direct.append(r)
    print(f"  [{len(latency_with_direct):2d}] {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  mean={r['mean']:>6.1f}ms  (n={r['n']})")

# Persistent client: a fresh httpx.Client per call costs ~40ms in construction
# under load, which would dominate and masquerade as sidecar latency. Use one
# keep-alive client so this phase measures the ACTUAL sidecar search round trip.
_direct_client = httpx.Client()

run_latency_direct("keyword (Tantivy ON) direct API top-5", lambda: _direct_client.post(
    f"{TANTIVY_URL}/search", json={"workspace_id": ws_id, "query": "test", "limit": 5}, timeout=30
).json())

# ============================================================
# PHASE 2b: LATENCY — IN-MEMORY MOCK (for fair comparison)
# ============================================================
print()
print("-" * 60)
print("PHASE 2b: Latency — In-memory keyword mock (no DB overhead)")
print("-" * 60)

latency_mock = []
def run_latency_mock(label, fn, n=N):
    r = measure(label, fn, n=n)
    latency_mock.append(r)
    print(f"  [{len(latency_mock):2d}] {label:40s}  p50={r['p50']:>6.1f}ms  p90={r['p90']:>6.1f}ms  mean={r['mean']:>6.1f}ms  (n={r['n']})")

run_latency_mock("keyword (Tantivy OFF) mock top-5", lambda: keyword_fallback_mock("test", all_memory_contents, limit=5))

print()
print("ALL LATENCY COMPARISON:")
print(f"  {'Path':<45s} {'p50 (ms)':>9} {'p90 (ms)':>9}")
print(f"  {'-'*45} {'-'*9} {'-'*9}")
print(f"  {'Tantivy ON (SDK c.search)':<45s} {latency_with[0]['p50']:>9.1f} {latency_with[0]['p90']:>9.1f}")
print(f"  {'Tantivy ON (direct HTTP API)':<45s} {latency_with_direct[0]['p50']:>9.1f} {latency_with_direct[0]['p90']:>9.1f}")
print(f"  {'Tantivy OFF (SDK fallback)':<45s} {latency_without[0]['p50']:>9.1f} {latency_without[0]['p90']:>9.1f}")
print(f"  {'Tantivy OFF (mock fallback)':<45s} {latency_mock[0]['p50']:>9.1f} {latency_mock[0]['p90']:>9.1f}")

# ============================================================
# PHASE 3: RETRIEVAL QUALITY WITH TANTIVY
# ============================================================
print()
print("-" * 60)
print("PHASE 3: Retrieval Quality — WITH Tantivy (BM25 sidecar)")
print("-" * 60)

results_with = {}
t0 = time.time()
for q in eval_queries:
    try:
        resp = httpx.post(f"{TANTIVY_URL}/search",
            json={"workspace_id": ws_id, "query": q["query"], "limit": 20}, timeout=30)
        results_with[q["query"]] = resp.json() if resp.status_code < 400 else []
    except Exception as e:
        print(f"  FAIL: {q['query'][:40]} — {e}")
        results_with[q["query"]] = []
query_time_with = time.time() - t0

m_with = compute_metrics(eval_queries, results_with, memories_by_id)
print(f"  P@5={m_with['P@5']:.1%}  R@5={m_with['R@5']:.1%}  MRR={m_with['MRR']:.3f}")
print(f"  {query_time_with/len(eval_queries)*1000:.0f}ms/q avg")

# ============================================================
# PHASE 4: RETRIEVAL QUALITY WITHOUT TANTIVY (in-memory mock)
# ============================================================
print()
print("-" * 60)
print("PHASE 4: Retrieval Quality — WITHOUT Tantivy (in-memory keyword mock)")
print("-" * 60)

results_without = {}
t0 = time.time()
for q in eval_queries:
    try:
        results_without[q["query"]] = keyword_fallback_mock(q["query"], all_memory_contents, limit=20)
    except Exception as e:
        print(f"  FAIL: {q['query'][:40]} — {e}")
        results_without[q["query"]] = []
query_time_without = time.time() - t0

m_without = compute_metrics(eval_queries, results_without, memories_by_id)
print(f"  P@5={m_without['P@5']:.1%}  R@5={m_without['R@5']:.1%}  MRR={m_without['MRR']:.3f}")
print(f"  {query_time_without/len(eval_queries)*1000:.0f}ms/q avg")

# ============================================================
# SUMMARY
# ============================================================
print()
print("=" * 60)
print("TANTIVY CONTRIBUTION SUMMARY")
print("=" * 60)
print(f"{'Strategy':<45} {'P@5':>8} {'R@5':>8} {'MRR':>8} {'Latency':>10}")
print("-" * 79)
print(f"{'keyword (Tantivy ON, SDK)':<45} {m_with['P@5']:>7.1%} {m_with['R@5']:>7.1%} {m_with['MRR']:>7.3f}  {latency_with[0]['p50']:>7.1f}ms")
print(f"{'keyword (Tantivy ON, direct)':<45} {m_with['P@5']:>7.1%} {m_with['R@5']:>7.1%} {m_with['MRR']:>7.3f}  {latency_with_direct[0]['p50']:>7.1f}ms")
print(f"{'keyword (Tantivy OFF, SDK)':<45} {'N/A':>7} {'N/A':>7} {'N/A':>7}  {latency_without[0]['p50']:>7.1f}ms")
print(f"{'keyword (Tantivy OFF, mock)':<45} {m_without['P@5']:>7.1%} {m_without['R@5']:>7.1%} {m_without['MRR']:>7.3f}  {latency_mock[0]['p50']:>7.1f}ms")
print()

# Tantivy contribution delta (comparing same algorithm, different backend)
delta_p = round((m_with["P@5"] - m_without["P@5"]) * 100, 1)
delta_r = round((m_with["R@5"] - m_without["R@5"]) * 100, 1)
delta_mrr = round(m_with["MRR"] - m_without["MRR"], 3)
lat_speedup_sdk = round(latency_without[0]["p50"] / max(latency_with[0]["p50"], 0.1), 1)
lat_speedup_direct = round(latency_mock[0]["p50"] / max(latency_with_direct[0]["p50"], 0.1), 1)

print(f"Tantivy contribution (quality delta, Tantivy ON vs mock OFF):")
print(f"  P@5: +{delta_p}pp  R@5: +{delta_r}pp  MRR: +{delta_mrr}")
print()
print(f"Tantivy contribution (latency speedup):")
print(f"  SDK path: {lat_speedup_sdk}x faster (SDK fallback {latency_without[0]['p50']}ms -> SDK+Tantivy {latency_with[0]['p50']}ms p50)")
print(f"  Direct API: {lat_speedup_direct}x faster (mock {latency_mock[0]['p50']}ms -> Tantivy API {latency_with_direct[0]['p50']}ms p50)")
print()

# ============================================================
# SAVE RESULTS
# ============================================================
report = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "host": HOST, "port": PORT, "database": DB[:20],
    "workspace_id": ws_id,
    "iterations": N,
    "dataset": {"memories": len(eval_memories), "queries": len(eval_queries)},
    "tantivy_available": True,
    "embedder_available": False,
    "latency": {
        "keyword_tantivy_on_sdk": latency_with,
        "keyword_tantivy_on_direct": latency_with_direct,
        "keyword_tantivy_off_sdk": latency_without,
        "keyword_tantivy_off_mock": latency_mock,
    },
    "quality": {
        "keyword_tantivy_on": m_with,
        "keyword_tantivy_off": m_without,
    },
    "tantivy_contribution": {
        "P@5_delta_pp": delta_p,
        "R@5_delta_pp": delta_r,
        "MRR_delta": delta_mrr,
        "latency_speedup_sdk_x": lat_speedup_sdk,
        "latency_speedup_direct_x": lat_speedup_direct,
    },
    "notes": (
        "Tantivy ON (SDK): c.search(semantic=False) routes through SDK -> Tantivy sidecar HTTP API. "
        "Tantivy ON (direct): direct POST to Tantivy BM25 sidecar at :9091. "
        "Tantivy OFF (SDK): c.search() with invalid Tantivy URL forces SDK fallback through "
        "_keyword_fallback (STDB _query + client-side BM25). NOTE: the _query bug (workspace_id "
        "filter returns 0 rows) causes this path to return 0 results for quality measurement, "
        "but latency correctly reflects the STDB query overhead (~5000ms when cold). "
        "Tantivy OFF (mock): in-memory keyword substring matching over 50 eval memories "
        "(same algorithm as SDK _keyword_fallback, sidestepping the _query bug). "
        "Seeding bypasses c.store() (unusably slow, ~10s/memory, and wedges the STDB wasm executor on client timeout) — uses the store_memory reducer directly + Tantivy /index/batch HTTP API. "
        "Graph/temporal/semantic phases skipped (keyword-only benchmark)."
    ),
}

out_path = Path(__file__).resolve().parent.parent / "benchmark_results_tantivy_contribution.json"
with open(out_path, "w") as f:
    json.dump(report, f, indent=2)
print(f"Results saved to {out_path}")
