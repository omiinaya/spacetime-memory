#!/usr/bin/env python3
"""Retrieval quality benchmark — test hybrid search strategies."""
from __future__ import annotations
import json, os, sys, time, uuid as _uuid

for prefix in (".", "..", "/home/user/spacetime-memory"):
    sdk_path = os.path.join(prefix, "sdk/python")
    if os.path.isdir(sdk_path): sys.path.insert(0, sdk_path); break

os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("LITELLM_MASTER_KEY", None)
os.environ["OPENAI_API_KEY"] = "REDACTED"
os.environ["OPENAI_BASE_URL"] = "http://localhost:4000/v1"
os.environ["EMBEDDING_MODEL"] = "baai/bge-m3"

from spacetime_memory import Client

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

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
            is_relevant = any(
                rc[:40] in res_content or res_content[:40] in rc
                for rc in relevant_contents
            )
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
    return {
        "P@5": round(sum(p) / n, 4),
        "R@5": round(sum(r) / n, 4),
        "MRR": round(sum(mrr) / n, 4),
    }

with open(os.path.join(DATA_DIR, "eval_memories_50.json")) as f:
    memories = json.load(f)
with open(os.path.join(DATA_DIR, "eval_queries_25.json")) as f:
    queries = json.load(f)
memories_by_id = {m["id"]: m for m in memories}

print(f"Dataset: {len(memories)} memories, {len(queries)} queries")
print()

configs = [
    ("keyword-only (BM25+graph+temporal)", False, {}),
    ("hybrid (bge-m3 semantic)", True, {}),
]

results_table = []
for label, use_semantic, kwargs in configs:
    c = Client()
    user = f"eval_{_uuid.uuid4().hex[:8]}"
    for reducer, args in [("register", [user, "Eval", "evalpass123"]),
                           ("login", [user, "evalpass123"])]:
        try:
            c._call(reducer, args)
        except RuntimeError:
            pass
    ws = f"eval-{_uuid.uuid4().hex[:8]}"
    c.create_workspace(f"Eval {label[:20]}", id=ws)

    t0 = time.time()
    for m in memories:
        c.store(workspace_id=ws, content=m["content"],
                memory_type=m.get("type", "experience"))
    seed_time = time.time() - t0

    # Wait for Tantivy indexing
    time.sleep(5)

    results = {}
    t0 = time.time()
    for i, q in enumerate(queries):
        try:
            r = c.search(workspace_id=ws, query=q["query"], limit=20,
                          semantic=use_semantic, **kwargs)
            results[q["query"]] = r
        except Exception as e:
            print(f"  FAIL: {q['query'][:40]} — {e}")
            results[q["query"]] = []
    query_time = time.time() - t0

    m = compute_metrics(queries, results, memories_by_id)
    results_table.append((label, m, seed_time, query_time / len(queries)))

    print(f"  [{label}]")
    print(f"    P@5={m['P@5']:.1%}  R@5={m['R@5']:.1%}  MRR={m['MRR']:.3f}")
    print(f"    seed={seed_time:.1f}s  {query_time/len(queries)*1000:.0f}ms/q")

print()
print("=" * 60)
print("RETRIEVAL QUALITY SUMMARY")
print("=" * 60)
print(f"{'Strategy':<40} {'P@5':>8} {'R@5':>8} {'MRR':>8}")
print("-" * 64)
for label, m, _, _ in results_table:
    print(f"{label:<40} {m['P@5']:>7.1%} {m['R@5']:>7.1%} {m['MRR']:>7.3f}")
print()
print("Reference: hybrid (bge-m3 proxy) P@5=81.3% R@5=82.0% MRR=0.960 (validated Jun 20)")
print("Reference: weight_tune.py 11.3% was INVALID — seeded via _call('store_memory') skipping index_entity")
print("GBrain reference (146K pages): P@5=49.1% R@5=97.9%")
