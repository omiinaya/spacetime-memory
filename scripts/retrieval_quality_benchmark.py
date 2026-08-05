#!/usr/bin/env python3
"""End-to-end retrieval quality benchmark — seeds eval memories into a fresh
workspace, runs the REAL SDK search path (keyword / semantic / hybrid fusion),
and computes P@5 / R@5 / MRR against the eval relevance judgments.

This reproduces the "Retrieval Quality" numbers in PERFORMANCE.md using the
actual production retrieval pipeline (STDB + Tantivy + embedder), instead of
the standalone in-memory scripts.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPACETIMEDB_PORT", 3001))
DB = os.environ.get("SPACETIMEDB_DB", "")
TANTIVY_URL = os.environ.get("TANTIVY_URL", "http://127.0.0.1:9091")
# Default to the GPU embedder (:9093, CUDAExecutionProvider) — the CPU one
# (:9090) times out on multi-text batches under host load (measured >120s at
# load average 73). Both run the identical BAAI/bge-m3 model, so quality
# numbers are equivalent; only latency differs. Override with EMBEDDER_URL.
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://127.0.0.1:9093/v1")

if not DB:
    print("FATAL: Set SPACETIMEDB_DB")
    sys.exit(1)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


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


def main():
    with open(DATA_DIR / "eval_memories_50.json") as f:
        memories = json.load(f)
    with open(DATA_DIR / "eval_queries_25.json") as f:
        queries = json.load(f)
    memories_by_id = {m["id"]: m for m in memories}

    print("=" * 60)
    print("END-TO-END RETRIEVAL QUALITY BENCHMARK")
    print("=" * 60)
    print(f"Host: {HOST}:{PORT} DB: {DB[:20]}...")
    print(f"Dataset: {len(memories)} memories, {len(queries)} queries")

    c = Client(host=HOST, port=PORT, database=DB, embedder_url=EMBEDDER_URL,
               tantivy_url=TANTIVY_URL, timeout=60)
    for reducer, args in [("register", ["bench_retq", "Bench RetQ", "benchpass123"]),
                           ("login", ["bench_retq", "benchpass123"])]:
        try:
            c._call(reducer, args)
        except RuntimeError:
            pass

    ws_name = f"retq-bench-{int(time.time())}"
    c.create_workspace(name=ws_name)
    ws_list = c._query("workspace", workspace_id="", columns=["id", "name"])
    ws_id = None
    for w in ws_list:
        if w.get("name") == ws_name:
            ws_id = w.get("id")
            break
    if not ws_id:
        print("ERROR: cannot create workspace")
        sys.exit(1)
    print(f"Workspace: {ws_id}")

    # ── Seed via store_memory reducer (fast, ~30ms) ──
    print("Seeding 50 eval memories via store_memory reducer...")
    t0 = time.time()
    for m in memories:
        c._call(
            "store_memory",
            [ws_id, "", "", m.get("type", "experience"), m["content"], "", "[]", 1.0, "", "", "[]"],
        )
    print(f"  Done in {time.time()-t0:.1f}s")

    # ── Fetch real memory IDs (match by content prefix, like SDK store()) ──
    # The store_memory reducer generates its own UUIDs; Tantivy and search_index
    # must be keyed by those real IDs so enrichment lookups resolve.
    mems = c._query("memory", workspace_id=ws_id, columns=["id", "content"])
    content_to_id: dict[str, str] = {}
    for m in sorted(mems, key=lambda x: x.get("created_at", 0), reverse=True):
        key = m.get("content", "")[:100]
        if key not in content_to_id:
            content_to_id[key] = m["id"]
    print(f"  Fetched {len(content_to_id)} memory ids from STDB")

    # ── Embed contents (plain text — matches production store_batch) ──
    print("Embedding 50 memories via embedder...")
    embeds: list[list[float]] = []

    def _embed_texts(texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            f"{EMBEDDER_URL}/embeddings",
            json={"input": texts, "model": "BAAI/bge-m3"},
            timeout=300,
        )
        resp.raise_for_status()
        return [d["embedding"] for d in resp.json()["data"]]

    for chunk_start in range(0, len(memories), 5):
        chunk = memories[chunk_start:chunk_start + 5]
        chunk_texts = [m["content"] for m in chunk]
        # Retry the batch twice, then fall back to per-item embedding so a
        # single slow embedder response can't abort the whole run.
        got = None
        for attempt in range(3):
            try:
                got = _embed_texts(chunk_texts)
                break
            except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
                if attempt == 2:
                    print(f"  batch embed failed ({repr(e)[:80]}), retrying per-item")
                else:
                    print(f"  batch embed attempt {attempt+1} failed ({repr(e)[:60]}), retrying")
        if got is None:
            got = []
            for text in chunk_texts:
                try:
                    got.append(_embed_texts([text])[0])
                except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
                    print(f"  item embed failed ({repr(e)[:60]}), skipping")
                    got.append([])
        embeds.extend(got)
    print(f"  Embedded {len(embeds)} memories")

    # ── Populate search_index via index_entity_batch (semantic search source) ──
    # CRITICAL: without this, client-side semantic search finds zero rows and
    # every config collapses to keyword-only results (the all-identical 61.3%
    # numbers in the 2026-08-05 run). This mirrors what SDK store() does.
    entity_tuples = []
    for m, emb in zip(memories, embeds):
        mid = content_to_id.get(m["content"][:100], "")
        if mid:
            entity_tuples.append((ws_id, "memory", mid, m["content"], json.dumps(emb)))
    if entity_tuples:
        c._call("index_entity_batch", [json.dumps(entity_tuples)])
    print(f"  index_entity_batch: {len(entity_tuples)} rows in search_index")

    # ── Index into Tantivy (real memory ids — same shape as SDK _tantivy_index) ──
    tantivy_items = [
        {"workspace_id": ws_id, "entity_id": content_to_id.get(m["content"][:100], ""),
         "content": m["content"], "entity_type": "memory"}
        for m in memories
    ]
    resp = httpx.post(f"{TANTIVY_URL}/index/batch", json={"items": tantivy_items}, timeout=60)
    resp.raise_for_status()
    print(f"  Tantivy /index/batch: {resp.json().get('count', 0)} indexed")
    time.sleep(3)  # Tantivy commit + reader reload

    # ── Run the three search modes ──
    results_keyword = {}
    results_hybrid = {}
    results_semantic_only = {}

    for q in queries:
        qq = q["query"]
        # Keyword-only: semantic=False → Tantivy BM25
        try:
            r = c.search(ws_id, qq, limit=5, semantic=False, cross_encoder=False)
            results_keyword[qq] = [
                {"content": x.get("content", x.get("memory_content", "")), "score": x.get("score", 0)}
                for x in r
            ]
        except Exception as e:
            print(f"  keyword FAIL {qq[:40]}: {repr(e)[:120]}")
            results_keyword[qq] = []

        # Hybrid: semantic=True → fusion (semantic + Tantivy keyword + graph + temporal)
        try:
            r = c.search(ws_id, qq, limit=5, semantic=True, cross_encoder=False)
            results_hybrid[qq] = [
                {"content": x.get("content", x.get("memory_content", "")), "score": x.get("score", 0)}
                for x in r
            ]
        except Exception as e:
            print(f"  hybrid FAIL {qq[:40]}: {repr(e)[:120]}")
            results_hybrid[qq] = []

        # Semantic-only: hybrid with keyword weight zeroed
        try:
            r = c.search(
                ws_id, qq, limit=5, semantic=True, cross_encoder=False,
                fusion_weights={"semantic": 1.0, "keyword": 0.0, "binary": 0.0,
                                "graph": 0.0, "temporal": 0.0},
            )
            results_semantic_only[qq] = [
                {"content": x.get("content", x.get("memory_content", "")), "score": x.get("score", 0)}
                for x in r
            ]
        except Exception as e:
            print(f"  semantic-only FAIL {qq[:40]}: {repr(e)[:120]}")
            results_semantic_only[qq] = []

    m_kw = compute_metrics(queries, results_keyword, memories_by_id)
    m_hy = compute_metrics(queries, results_hybrid, memories_by_id)
    m_se = compute_metrics(queries, results_semantic_only, memories_by_id)

    print()
    print("=" * 60)
    print("RETRIEVAL QUALITY SUMMARY (end-to-end SDK path)")
    print("=" * 60)
    print(f"{'Strategy':<40} {'P@5':>8} {'R@5':>8} {'MRR':>8}")
    print("-" * 64)
    print(f"{'keyword-only (Tantivy BM25)':<40} {m_kw['P@5']:>7.1%} {m_kw['R@5']:>7.1%} {m_kw['MRR']:>7.3f}")
    print(f"{'semantic-only (bge-m3)':<40} {m_se['P@5']:>7.1%} {m_se['R@5']:>7.1%} {m_se['MRR']:>7.3f}")
    print(f"{'hybrid (semantic+Tantivy)':<40} {m_hy['P@5']:>7.1%} {m_hy['R@5']:>7.1%} {m_hy['MRR']:>7.3f}")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": HOST, "port": PORT, "database": DB[:20],
        "workspace_id": ws_id,
        "dataset": {"memories": len(memories), "queries": len(queries)},
        "quality": {
            "keyword_tantivy": m_kw,
            "semantic_only": m_se,
            "hybrid_semantic_tantivy": m_hy,
        },
    }
    out = Path(__file__).resolve().parent.parent / "benchmark_results_retrieval_quality.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Results saved to {out}")


if __name__ == "__main__":
    main()
