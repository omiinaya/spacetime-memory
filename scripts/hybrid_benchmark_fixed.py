#!/usr/bin/env python3
"""Standalone hybrid retrieval quality benchmark — uses embedder API directly."""
from __future__ import annotations
import json, os, sys, time, math

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# Configure embedder endpoint
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090/v1/embeddings")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
EMBEDDER_API_KEY = os.environ.get("OPENAI_API_KEY", "")

def get_embedding(text: str) -> list[float]:
    """Get embedding via OpenAI-compatible API."""
    import urllib.request, urllib.error
    body = json.dumps({
        "model": EMBEDDING_MODEL,
        "input": text
    }).encode()
    req = urllib.request.Request(
        EMBEDDER_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {EMBEDDER_API_KEY}",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result["data"][0]["embedding"]
    except Exception as e:
        print(f"  Embedding error: {e}", file=sys.stderr)
        raise

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-10)

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
    with open(os.path.join(DATA_DIR, "eval_memories_50.json")) as f:
        memories = json.load(f)
    with open(os.path.join(DATA_DIR, "eval_queries_25.json")) as f:
        queries = json.load(f)
    memories_by_id = {m["id"]: m for m in memories}

    print(f"Dataset: {len(memories)} memories, {len(queries)} queries")
    print()

    # Test embedder connectivity
    print("Testing embedder...", end=" ", flush=True)
    t0 = time.time()
    test_embedding = get_embedding("test memory")
    embed_time = time.time() - t0
    print(f"OK ({len(test_embedding)} dims, {embed_time*1000:.0f}ms)")
    print()

    # ── Hybrid mode ──
    print("Computing hybrid (semantic) scores...")

    # Embed all memories
    t0 = time.time()
    memory_embeddings = {}
    for m in memories:
        memory_embeddings[m["id"]] = get_embedding(m["content"])
    seed_time = time.time() - t0
    print(f"  Embedded {len(memories)} memories in {seed_time:.1f}s")

    # For each query, embed and find top-5 by cosine similarity
    results = {}
    query_times = []
    for q in queries:
        t0 = time.time()
        q_emb = get_embedding(q["query"])
        scores = []
        for m in memories:
            sim = cosine_similarity(q_emb, memory_embeddings[m["id"]])
            scores.append((sim, m))
        scores.sort(key=lambda x: -x[0])
        results[q["query"]] = [
            {"content": m["content"], "score": s}
            for s, m in scores[:5]
        ]
        query_times.append(time.time() - t0)

    avg_query_time = sum(query_times) / len(query_times)

    m = compute_metrics(queries, results, memories_by_id)
    print(f"  [hybrid (bge-m3 semantic)]")
    print(f"    P@5={m['P@5']:.1%}  R@5={m['R@5']:.1%}  MRR={m['MRR']:.3f}")
    print(f"    seed={seed_time:.1f}s  {avg_query_time*1000:.0f}ms/q")

    # ── Also compute keyword-only using BM25-like scoring ──
    print()
    print("Computing keyword-only (term overlap) scores...")

    def term_overlap_score(query: str, content: str) -> float:
        q_words = set(query.lower().split())
        c_words = set(content.lower().split())
        if not q_words:
            return 0.0
        return len(q_words & c_words) / len(q_words)

    kw_results = {}
    for q in queries:
        scores = []
        for m in memories:
            sim = term_overlap_score(q["query"], m["content"])
            scores.append((sim, m))
        scores.sort(key=lambda x: -x[0])
        kw_results[q["query"]] = [
            {"content": m["content"], "score": s}
            for s, m in scores[:5]
        ]

    kw = compute_metrics(queries, kw_results, memories_by_id)
    print(f"  [keyword-only (term overlap)]")
    print(f"    P@5={kw['P@5']:.1%}  R@5={kw['R@5']:.1%}  MRR={kw['MRR']:.3f}")

    # ── Summary ──
    print()
    print("=" * 60)
    print("RETRIEVAL QUALITY SUMMARY")
    print("=" * 60)
    print(f"{'Strategy':<40} {'P@5':>8} {'R@5':>8} {'MRR':>8}")
    print("-" * 64)
    print(f"{'keyword-only (term overlap)':<40} {kw['P@5']:>7.1%} {kw['R@5']:>7.1%} {kw['MRR']:>7.3f}")
    print(f"{'hybrid (bge-m3 semantic)':<40} {m['P@5']:>7.1%} {m['R@5']:>7.1%} {m['MRR']:>7.3f}")
    print()

    # ── Save results to benchmark JSON ──
    results_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "benchmark_results_latest.json")
    try:
        with open(results_file) as f:
            report = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "host": "127.0.0.1",
            "port": "3001",
            "iterations": len(queries),
            "latency": [],
        }

    # Update quality section
    report["quality"] = {
        "keyword-only (term overlap)": {
            "P@5": kw["P@5"],
            "R@5": kw["R@5"],
            "MRR": kw["MRR"],
        },
        "hybrid (bge-m3 semantic)": {
            "P@5": m["P@5"],
            "R@5": m["R@5"],
            "MRR": m["MRR"],
        },
    }
    report["embedder_available"] = True
    report["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with open(results_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Results saved to {results_file}")

    # Also update embedder benchmark file
    embedder_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "benchmark_results_embedder.json")
    try:
        with open(embedder_file) as f:
            e_report = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        e_report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "host": "127.0.0.1",
            "port": "3001",
            "iterations": len(queries),
            "latency": [],
            "quality": {},
        }
    e_report["quality"] = {
        "keyword-only (term overlap)": {
            "P@5": kw["P@5"],
            "R@5": kw["R@5"],
            "MRR": kw["MRR"],
        },
        "hybrid (bge-m3 semantic)": {
            "P@5": m["P@5"],
            "R@5": m["R@5"],
            "MRR": m["MRR"],
        },
    }
    e_report["embedder_available"] = True
    e_report["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(embedder_file, "w") as f:
        json.dump(e_report, f, indent=2)
    print(f"Results saved to {embedder_file}")

if __name__ == "__main__":
    main()
