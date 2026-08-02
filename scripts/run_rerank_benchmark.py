#!/usr/bin/env python3
"""Record P@5, R@5, MRR for +LLM reranking mode using embedder API.

Uses direct embedding (bge-m3 via embedder API) for semantic search,
then an LLM for relevance reranking.

Key difference from SDK's llm_rerank(): uses httpx directly with
higher max_tokens (8192) and handles reasoning models robustly.
"""
import json, os, sys, time, math, uuid as _uuid
from pathlib import Path
import httpx

os.environ["LLM_RERANK_ENDPOINT"] = "http://127.0.0.1:4002/v1"
os.environ["LLM_RERANK_MODEL"] = "deepseek-v4-flash-free"

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

EMBEDDER_URL = "http://127.0.0.1:9090/v1/embeddings"
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDER_API_KEY = os.getenv("EMBEDDER_API_KEY", "")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
LLM_ENDPOINT = "http://127.0.0.1:4002/v1"
LLM_MODEL = "deepseek-v4-flash-free"

http = httpx.Client(timeout=60)


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
        return json.loads(resp.read())["data"][0]["embedding"]


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


_RERANK_PROMPT = """Score each search result for relevance to the query (1-10).

10 — perfectly answers the query, exact match
7-9 — highly relevant, contains key information
4-6 — partially relevant, related concepts
1-3 — barely relevant, tangential mention

Query: {query}

Candidates:
{candidates}

Provide your scores as a JSON array in this exact format, no other text:
[{{"index": 0, "score": 8, "reason": "contains exact match for 'auth'"}}, ...]

JSON:"""


def llm_rerank(query: str, candidates: list[dict], top_k: int = 10) -> list[dict]:
    """Rerank candidates using LLM (local implementation with high max_tokens)."""
    if not candidates:
        return candidates

    candidates_text = "\n".join(
        f"[{i}] {r.get('content', '')[:500]}" for i, r in enumerate(candidates[:top_k])
    )
    prompt = _RERANK_PROMPT.format(query=query, candidates=candidates_text)

    for attempt in range(3):
        try:
            resp = http.post(
                f"{LLM_ENDPOINT}/chat/completions",
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 8192,  # generous for reasoning models
                },
            )
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = (msg.get("content") or "").strip()

            # Reasoning models: try content first, then reasoning_content
            if not content:
                content = (msg.get("reasoning_content") or "").strip()
                if content:
                    # Reasoning text is not JSON - skip it
                    raise ValueError("Only reasoning tokens returned, no JSON content")

            # Strip markdown code fences
            if content.startswith("```"):
                # Find first ``` and last ```
                lines = content.split("\n")
                if len(lines) > 2:
                    # Remove first line (```json) and last line (```)
                    content = "\n".join(lines[1:-1]).strip()

            scores = json.loads(content)
            if not isinstance(scores, list):
                raise ValueError(f"Expected list, got {type(scores)}")

            # Merge scores
            score_map = {}
            for s in scores:
                idx = int(s["index"])
                score_map[idx] = (float(s["score"]) / 10.0, s.get("reason", ""))

            for i, r in enumerate(candidates[:top_k]):
                if i in score_map:
                    r["score"] = score_map[i][0]
                    r["rerank_reason"] = score_map[i][1]
                else:
                    r["score"] = r.get("score", 0.0) * 0.5
                    r["rerank_reason"] = "not reranked by LLM"

            # Re-sort
            candidates[:top_k] = sorted(
                candidates[:top_k],
                key=lambda x: x.get("score", 0.0),
                reverse=True,
            )
            return candidates

        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            print(f"\n  LLM rerank failed after 3 attempts: {e}", file=sys.stderr)
            # On final failure, return original candidates
            return candidates

    return candidates


def main():
    with open(os.path.join(DATA_DIR, "eval_memories_50.json")) as f:
        memories = json.load(f)
    with open(os.path.join(DATA_DIR, "eval_queries_25.json")) as f:
        queries = json.load(f)
    memories_by_id = {m["id"]: m for m in memories}

    print(f"Dataset: {len(memories)} memories, {len(queries)} queries")
    print(f"LLM rerank: {LLM_ENDPOINT} model={LLM_MODEL}")
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
    results_table.append(("keyword-only (term overlap)", kw_m, 0, 0))
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
        reranked = llm_rerank(q["query"], candidates, top_k=10)
        llm_results[q["query"]] = [
            {"content": c["content"], "score": c.get("score", 0.0)}
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
            "keyword": "term overlap (baseline)",
            "llm_rerank_endpoint": LLM_ENDPOINT,
            "llm_rerank_model": LLM_MODEL,
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
