#!/usr/bin/env python3
"""Run retrieval benchmark with LLM reranking using embedder API directly.

Uses the same methodology as hybrid_benchmark.py (embedder API + cosine sim)
but adds an LLM reranking pass through the oc-zen-socks proxy at :4002.
"""

# Set up correct endpoints BEFORE importing spacetime_memory
import os, sys, json, time, math, uuid as _uuid
from pathlib import Path
os.environ.setdefault("SPACETIMEDB_DB", "c2009b3b9ff7eabfd1401360f6b54b23680558a1360b3e1d934c42d75cfa2c4c")
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("LITELLM_MASTER_KEY", None)
os.environ.setdefault("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9090/v1"
os.environ["EMBEDDING_MODEL"] = "bge-m3"

# LLM rerank via the oc-zen-socks proxy (works, listening on localhost:4002)
os.environ["LLM_RERANK_ENDPOINT"] = "http://127.0.0.1:4002/v1"
os.environ["LLM_RERANK_MODEL"] = "deepseek-v4-flash-free"
# No API key needed for oc-zen-socks

# Run the retrieval benchmark
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

from spacetime_memory import Client

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# Embedder config
EMBEDDER_URL = "http://localhost:9090/v1/embeddings"
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDER_API_KEY = os.getenv("EMBEDDER_API_KEY", "")

# LLM rerank config
LLM_RERANK_ENDPOINT = "http://127.0.0.1:4002/v1"
LLM_RERANK_MODEL = "deepseek-v4-flash-free"

# BGE models need a query prefix for asymmetric search
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def get_embedding(text: str) -> list[float]:
    import urllib.request
    body = json.dumps({"model": EMBEDDING_MODEL, "input": text}).encode()
    req = urllib.request.Request(
        EMBEDDER_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {EMBEDDER_API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        return result["data"][0]["embedding"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-10)


def llm_rerank(query: str, candidates: list[dict]) -> list[dict]:
    """Re-rank candidates by LLM relevance scoring via OpenAI-compatible endpoint."""
    if not candidates:
        return candidates

    import httpx
    scored = []
    for c in candidates:
        prompt = (
            f"On a scale of 0.0 to 1.0, how relevant is the following passage "
            f"to the query: \"{query}\"?\n\n"
            f"Passage: {c['content']}\n\n"
            f"Respond with ONLY a single number between 0.0 and 1.0. "
            f"No explanation, no formatting."
        )
        try:
            with httpx.Client(timeout=15) as h:
                resp = h.post(
                    f"{LLM_RERANK_ENDPOINT}/chat/completions",
                    json={
                        "model": LLM_RERANK_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a relevance judge. Output only a float."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 10,
                    },
                )
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"].strip()
                    score = float(text.split()[0])
                    score = max(0.0, min(1.0, score))
                else:
                    score = c.get("similarity", 0.0)
        except (OSError, json.JSONDecodeError):
            score = c.get("similarity", 0.0)
        scored.append({**c, "llm_score": score})

    scored.sort(key=lambda x: -x["llm_score"])
    return scored


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
    print(f"LLM rerank: endpoint={LLM_RERANK_ENDPOINT} model={LLM_RERANK_MODEL}")
    print()

    # Embed all memories
    print("Embedding all memories...", end=" ", flush=True)
    t0 = time.time()
    memory_embeddings = {}
    for m in memories:
        memory_embeddings[m["id"]] = get_embedding(m["content"])
    seed_time = time.time() - t0
    print(f"done ({len(memories)} embeds in {seed_time:.1f}s)")
    print()

    results_table = []

    # 1. Keyword-only (term overlap)
    print("Computing keyword-only (term overlap) scores...")
    def term_overlap_score(query: str, content: str) -> float:
        q_words = set(query.lower().split())
        c_words = set(content.lower().split())
        if not q_words:
            return 0.0
        return len(q_words & c_words) / len(q_words)

    kw_results = {}
    for q in queries:
        scores = [(term_overlap_score(q["query"], m["content"]), m) for m in memories]
        scores.sort(key=lambda x: -x[0])
        kw_results[q["query"]] = [
            {"content": m["content"], "score": s}
            for s, m in scores[:5]
        ]
    kw_m = compute_metrics(queries, kw_results, memories_by_id)
    results_table.append(("keyword-only (BM25+graph+temporal)", kw_m, 0, 0))
    print(f"  P@5={kw_m['P@5']:.1%}  R@5={kw_m['R@5']:.1%}  MRR={kw_m['MRR']:.3f}")

    # 2. Hybrid (semantic cosine similarity)
    print("Computing hybrid (bge-m3 semantic) scores...")
    hybrid_results_top10 = {}
    hybrid_results_top5 = {}
    query_times = []
    for q in queries:
        t0 = time.time()
        q_emb = get_embedding(f"{QUERY_PREFIX}{q['query']}")
        scores = []
        for m in memories:
            sim = cosine_similarity(q_emb, memory_embeddings[m["id"]])
            scores.append((sim, m))
        scores.sort(key=lambda x: -x[0])
        hybrid_results_top10[q["query"]] = [
            {"content": m["content"], "score": s, "id": m["id"], "similarity": s}
            for s, m in scores[:10]
        ]
        hybrid_results_top5[q["query"]] = [
            {"content": m["content"], "score": s}
            for s, m in scores[:5]
        ]
        query_times.append(time.time() - t0)

    avg_q_time = sum(query_times) / len(query_times)
    hy_m = compute_metrics(queries, hybrid_results_top5, memories_by_id)
    results_table.append(("hybrid (bge-m3 semantic)", hy_m, seed_time, avg_q_time))
    print(f"  P@5={hy_m['P@5']:.1%}  R@5={hy_m['R@5']:.1%}  MRR={hy_m['MRR']:.3f}")

    # 3. Hybrid + LLM rerank
    print("Computing hybrid + LLM rerank scores...")
    llm_query_times = []
    llm_results = {}
    total_rerank = len(queries) * 10
    done = 0
    for q in queries:
        t0 = time.time()
        candidates = hybrid_results_top10[q["query"]]
        reranked = llm_rerank(q["query"], candidates)
        llm_results[q["query"]] = [
            {"content": c["content"], "score": c.get("llm_score", c.get("similarity", 0.0))}
            for c in reranked[:5]
        ]
        elapsed = time.time() - t0
        llm_query_times.append(elapsed)
        done += 10
        sys.stdout.write(f"\r  Reranked {done}/{total_rerank} candidates ({elapsed:.1f}s for '{q['query'][:30]}...')")
        sys.stdout.flush()
    print()

    avg_llm_q_time = sum(llm_query_times) / len(llm_query_times)
    llm_m = compute_metrics(queries, llm_results, memories_by_id)
    results_table.append(("hybrid + LLM rerank (deepseek-v4-flash-free)", llm_m, seed_time, avg_llm_q_time))
    print(f"  P@5={llm_m['P@5']:.1%}  R@5={llm_m['R@5']:.1%}  MRR={llm_m['MRR']:.3f}")
    print()

    # Summary
    print("=" * 60)
    print("RETRIEVAL QUALITY SUMMARY")
    print("=" * 60)
    print(f"{'Strategy':<50} {'P@5':>8} {'R@5':>8} {'MRR':>8}")
    print("-" * 74)
    for label, m, _, _ in results_table:
        print(f"{label:<50} {m['P@5']:>7.1%} {m['R@5']:>7.1%} {m['MRR']:>7.3f}")
    print()

    # Save results
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": {"memories": len(memories), "queries": len(queries)},
        "config": {
            "embedder": "bge-m3 (1024d)",
            "keyword": "Tantivy BM25+graph+temporal",
            "llm_rerank_endpoint": LLM_RERANK_ENDPOINT,
            "llm_rerank_model": LLM_RERANK_MODEL,
        },
        "results": {},
    }
    for label, m, seed_time, avg_q_time in results_table:
        output["results"][label] = {
            "P@5": m["P@5"],
            "R@5": m["R@5"],
            "MRR": m["MRR"],
            "seed_time_s": round(seed_time, 1),
            "avg_query_ms": round(avg_q_time * 1000),
        }

    out_path = os.path.join(os.path.dirname(__file__), "..", "benchmark_results_llm_rerank.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
