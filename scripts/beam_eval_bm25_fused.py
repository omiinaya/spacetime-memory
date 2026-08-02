#!/usr/bin/env python3
"""BEAM benchmark — in-process BM25 with multi-query fusion.

Measures retrieval quality independently of STDB storage/search pipeline.

For each query:
  1. Use in-process BM25 on the seed texts (no STDB)
  2. Apply multi-query fusion (3 query variations, RRF)
  3. Score against expected content

This isolates retrieval quality from storage pipeline overhead.
Standalone BM25 baseline: 82.9%. Target: exceed it.
"""
import json, os, sys, time, re, math, argparse
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SCENARIOS_PATH = DATA_DIR / "beam_scenarios.json"

ABILITY_NAMES = {
    "IE": "Information Extraction",
    "MR": "Memory Retrieval",
    "TR": "Temporal Reasoning",
    "ABS": "Abstractive Summarization / Abstention",
    "CR": "Counterfactual Reasoning",
    "KU": "Knowledge Updating",
    "EO": "Entity Ordering",
    "IF": "Inference",
    "PF": "Property/Attribute Following",
    "SUM": "Summarization",
    "ALL": "End-to-end Narrative",
}

STOPWORDS = {
    "a","an","the","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","could","should",
    "may","might","can","shall","to","of","in","for","on","with","at","by",
    "from","as","into","through","during","before","after","above","below",
    "between","out","off","over","under","again","further","then","once",
    "here","there","when","where","why","how","all","each","every","both",
    "few","more","most","other","some","such","no","nor","not","only","own",
    "same","so","than","too","very","just","because","but","and","or","if",
    "while","that","this","these","those","it","its",
}


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def compute_bm25(query: str, corpus: list[str], k1: float = 1.2, b: float = 0.75) -> list[tuple[float, int]]:
    q_tokens = tokenize(query)
    if not q_tokens:
        return [(0.0, i) for i in range(len(corpus))]
    n = len(corpus)
    tokenized = [tokenize(d) for d in corpus]
    avg_dl = sum(len(t) for t in tokenized) / max(n, 1)
    
    idf = {}
    for t in set(q_tokens):
        nc = sum(1 for dt in tokenized if t in dt)
        idf[t] = math.log((n - nc + 0.5) / (nc + 0.5) + 1.0)
    
    scores = []
    for i in range(n):
        dt = tokenized[i]
        dl = len(dt)
        s = 0.0
        for t in q_tokens:
            tf = dt.count(t)
            if tf == 0: continue
            s += idf.get(t, 0) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / avg_dl)))
        scores.append((s, i))
    scores.sort(key=lambda x: -x[0])
    return scores


def generate_query_variations(query: str) -> list[str]:
    """Generate up to 3 query variations for multi-query fusion."""
    variants = [query]
    tokens = tokenize(query)
    
    # Variation 2: entity-focused (capitalized words, numbers)
    words = re.findall(r"[A-Z][a-zA-Z]+", query)
    numbers = re.findall(r"\d+[A-Za-z]*", query)
    if not words:
        words = sorted(set(tokens), key=len, reverse=True)[:3]
    entity_phrase = " ".join(words + numbers)
    if entity_phrase:
        variants.append(f"{query} {entity_phrase}")
    
    # Variation 3: keyword-only
    if len(tokens) >= 2:
        unique = list(dict.fromkeys(tokens))
        variants.append(" ".join(unique[:8]))
    
    seen = set()
    unique = []
    for v in variants:
        key = v.lower().strip()
        if key not in seen:
            seen.add(key); unique.append(v)
    while len(unique) < 3:
        unique.append(query)
    return unique[:3]


def rrf_fuse(scores_list: list[list[tuple[float, int]]], k: int = 60) -> list[int]:
    index_scores = defaultdict(float)
    for rank_list in scores_list:
        for rank, (score, idx) in enumerate(rank_list):
            index_scores[idx] += 1.0 / (k + rank + 1)
    return sorted(index_scores.keys(), key=lambda i: -index_scores[i])


def score_query(query_spec: dict, top5_texts: list[str]) -> dict:
    """Score query results against expected content."""
    expected = query_spec.get("expected_content", [])
    expect_abstain = query_spec.get("expect_abstain", False)
    is_summary = query_spec.get("summary", False)
    min_facts = query_spec.get("min_facts", 3)
    all_text = " ".join(top5_texts)

    if expect_abstain:
        if not expected:
            return {"passed": True, "score": 1.0, "expected": [], "matched": [], "note": "abstain check"}
        for kw in expected:
            if kw.lower() in all_text.lower():
                return {"passed": False, "score": 0.0, "expected": expected, "matched": [kw], "note": "should have abstained"}
        return {"passed": True, "score": 1.0, "expected": expected, "matched": [], "note": "correctly abstained"}

    if is_summary:
        if not expected:
            if len(all_text) > 100:
                return {"passed": True, "score": 1.0, "expected": [], "matched": [], "note": f"summary ({len(all_text)} chars)"}
            return {"passed": False, "score": 0.0, "expected": [], "matched": [], "note": "summary too brief"}
        matched = [kw for kw in expected if kw.lower() in all_text.lower()]
        score = min(len(matched) / len(expected) if expected else 0.0, 0.8)
        if len(matched) >= min(min_facts, len(expected)):
            score = max(score, 0.8)
        return {"passed": score >= 0.5, "score": round(score, 4), "expected": expected, "matched": matched,
                "note": f"summary: {len(matched)}/{len(expected)} facts"}

    matched = [kw for kw in expected if kw.lower() in all_text.lower()]
    if not expected:
        return {"passed": True, "score": 1.0, "expected": [], "matched": [], "note": "no expectations"}
    score = len(matched) / len(expected)
    return {"passed": score >= 0.5, "score": round(score, 4), "expected": expected, "matched": matched,
            "top_content": [t[:120] for t in top5_texts[:3]]}


def run_scenario_bm25(scenario) -> dict:
    """Run one BEAM scenario with in-process BM25 + multi-query fusion."""
    sid = scenario["id"]
    ability = scenario["ability"]
    seeds = scenario["seeds"]
    queries = scenario["queries"]
    corpus = [s["content"] for s in seeds]

    query_results = []
    for q in queries:
        t0 = time.time()
        variants = generate_query_variations(q["query"])
        all_ranked = [compute_bm25(v, corpus) for v in variants]
        fused_indices = rrf_fuse(all_ranked)
        top5_texts = [corpus[i] for i in fused_indices[:5]]
        elapsed = time.time() - t0
        
        scoring = score_query(q, top5_texts)
        query_results.append({
            "query": q["query"][:80],
            "latency_ms": round(elapsed * 1000, 1),
            **scoring,
        })

    passed = sum(1 for qr in query_results if qr["passed"])
    total = len(query_results)
    avg_score = sum(qr["score"] for qr in query_results) / total if total else 0.0
    avg_latency = sum(qr.get("latency_ms", 0) for qr in query_results) / total if total else 0.0

    return {
        "id": sid, "ability": ability, "description": scenario["description"],
        "difficulty": scenario.get("difficulty", "unknown"),
        "queries_total": total, "queries_passed": passed,
        "accuracy": round(avg_score, 4), "avg_latency_ms": round(avg_latency, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="BEAM — in-process BM25 + multi-query fusion")
    parser.add_argument("--output", default="benchmark_results_beam_bm25.json",
                        help="Output JSON path")
    args = parser.parse_args()

    with open(SCENARIOS_PATH) as f:
        data = json.load(f)
    scenarios = data["scenarios"]

    print(f"BEAM BM25 + Multi-Query Fusion — {len(scenarios)} scenarios", flush=True)

    results = []
    for scenario in scenarios:
        r = run_scenario_bm25(scenario)
        results.append(r)
        print(f"  [{r['id']}] ({r['ability']}) {scenario['description'][:55]:<55} "
              f"{r['queries_passed']}/{r['queries_total']}={r['accuracy']*100:.1f}%  "
              f"{r['avg_latency_ms']:.1f}ms", flush=True)

    # Aggregate by ability
    by_ability = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        by_ability[r["ability"]]["passed"] += r["queries_passed"]
        by_ability[r["ability"]]["total"] += r["queries_total"]

    total_pass = sum(v["passed"] for v in by_ability.values())
    total_q = sum(v["total"] for v in by_ability.values())
    overall_accuracy = total_pass / total_q if total_q else 0

    print(f"\n{'='*60}", flush=True)
    print(f"  BEAM RESULTS — In-Process BM25 + Multi-Query Fusion", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Overall: {total_pass}/{total_q} = {overall_accuracy*100:.1f}%", flush=True)
    for ab, st in sorted(by_ability.items()):
        pct = st["passed"] / st["total"] * 100 if st["total"] else 0
        print(f"  {ab} ({ABILITY_NAMES.get(ab, '?')}): {st['passed']}/{st['total']} = {pct:.1f}%", flush=True)

    # Comparison
    print(f"\nComparison:", flush=True)
    print(f"  Standalone BM25 (previous): 82.9%", flush=True)
    print(f"  SDK pipeline (previous):    63.4%", flush=True)
    print(f"  SDK + multi-query fusion:   75.6%", flush=True)
    print(f"  In-process BM25 + fusion:   {overall_accuracy*100:.1f}%", flush=True)

    out = {
        "benchmark": "BEAM (In-Process BM25 + Multi-Query Fusion)",
        "scenarios": len(scenarios),
        "overall": {"passed": total_pass, "total": total_q, "accuracy": round(overall_accuracy, 4)},
        "by_ability": {
            ab: {"passed": st["passed"], "total": st["total"],
                 "accuracy": round(st["passed"] / st["total"], 4) if st["total"] else 0}
            for ab, st in sorted(by_ability.items())
        },
        "scenario_results": results,
        "comparison": {
            "standalone_bm25": 0.829,
            "sdk_pipeline": 0.634,
            "sdk_multi_query_fusion": 0.756,
            "bm25_multi_query_fusion": round(overall_accuracy, 4),
        },
    }

    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved to {args.output}", flush=True)
    return out


if __name__ == "__main__":
    main()
