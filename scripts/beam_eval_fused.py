#!/usr/bin/env python3
"""BEAM benchmark — SDK pipeline with multi-query fusion.

Applies the same technique that won LoCoMo (v11) to close the gap
between SDK pipeline (63.4%) and standalone BM25 (82.9%).

For each query:
  1. Store seeds in STDB via direct reducer (no embedding — keyword-only)
  2. Generate 3 query variations (original, entity-focused, keyword-emphasis)
  3. Search each with STDB keyword search
  4. Fuse results with Reciprocal Rank Fusion (RRF)
  5. Score against expected content

Usage:
    python3 scripts/beam_eval_fused.py [--output /tmp/beam_fused.json]
"""

import json, os, sys, time, re, math, uuid as _uuid, argparse
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

HOST = os.environ.get("SPACETIMEDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPACETIMEDB_PORT", "3001"))
EMB = os.environ.get("EMBEDDER_URL", "http://127.0.0.1:9090")
DB = os.environ.get("SPACETIMEDB_DB", "")

SCENARIOS_PATH = os.path.join(Path(__file__).resolve().parent.parent, "data", "beam_scenarios.json")

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


# ── Helpers ───────────────────────────────────────────────────────────

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


def _make_client() -> Client:
    global DB
    if not DB:
        resp = httpx.get(f"http://{HOST}:{PORT}/v1/database", timeout=15)
        dbs = resp.json()
        if isinstance(dbs, dict):
            for key in ("databases",):
                val = dbs.get(key)
                if val and isinstance(val, list) and len(val) > 0:
                    entry = val[0]
                    if isinstance(entry, dict):
                        ident = entry.get("identity", {})
                        if isinstance(ident, dict):
                            DB = ident.get("__identity__", "").lstrip("0x")
                        else:
                            DB = str(ident)
                    elif isinstance(entry, str):
                        DB = entry
                    break
    resp = httpx.get(f"http://{HOST}:{PORT}/v1/database/{DB}", timeout=5)
    token = resp.headers.get("spacetime-identity-token", "")
    c = Client(database=DB, embedder_url=EMB, token=token, host=HOST, port=PORT)
    try:
        c._call("register", [f"beam-fused-{_uuid.uuid4().hex[:8]}", "beameval789", token[:8]])
    except Exception:
        pass
    return c


def generate_query_variations(original: str) -> list[str]:
    """Generate 3 query variations for multi-query fusion.

    Each variation emphasizes different aspects: original verbatim,
    entity-focused (nouns/proper names), keyword-focused (content words).
    """
    variants = [original]
    
    # Variation 2: Entity-focused — emphasize nouns, proper names, numbers
    tokens = tokenize(original)
    # Identify likely entities: capitalized words and numbers
    words = re.findall(r"[A-Z][a-zA-Z0-9]+", original)
    numbers = re.findall(r"\d+[A-Za-z]*", original)
    # If no capital words, use longest content words
    if not words:
        words = sorted(set(tokens), key=len, reverse=True)[:3]
    entity_phrase = " ".join(words + numbers)
    if entity_phrase:
        variants.append(f"{original} {entity_phrase}")
    
    # Variation 3: Keyword-emphasis — key content words
    if len(tokens) >= 2:
        keywords = " ".join(tokens)
        variants.append(keywords)
    
    # Ensure we have exactly 3 unique variants
    seen = set()
    unique = []
    for v in variants:
        key = v.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(v)
    # Pad with original if needed
    while len(unique) < 3:
        unique.append(original)
    
    return unique[:3]


def rrf_fuse(results_list: list[list[dict]], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion over multiple search result sets."""
    scores = {}
    content_map = {}
    
    for rank_list in results_list:
        for rank, r in enumerate(rank_list):
            cid = r.get("id", "") or r.get("source_session_id", "") or r.get("content", "")[:100]
            if cid not in scores:
                scores[cid] = 0.0
                content_map[cid] = r
            scores[cid] += 1.0 / (k + rank + 1)
    
    sorted_ids = sorted(scores.keys(), key=lambda x: -scores[x])
    return [content_map[cid] for cid in sorted_ids]


def beam_search_fused(c, ws_id, query: str, limit: int = 5) -> list[dict]:
    """Multi-query fusion search: 3 variations → RRF."""
    variants = generate_query_variations(query)
    all_results = []
    
    for v in variants:
        try:
            sr = c.search(ws_id, v, limit=limit * 2, semantic=False, cross_encoder=False)
        except Exception:
            sr = []
        all_results.append(sr)
    
    fused = rrf_fuse(all_results)
    return fused[:limit]


def score_query(query_spec: dict, results: list[dict]) -> dict:
    """Score a single query result against expected content."""
    expected = query_spec.get("expected_content", [])
    expect_abstain = query_spec.get("expect_abstain", False)
    is_summary = query_spec.get("summary", False)
    min_facts = query_spec.get("min_facts", 3)

    top5 = [r.get("content", "") for r in results[:5]]
    all_text = " ".join(top5)

    if expect_abstain:
        if not expected:
            return {"passed": True, "score": 1.0, "expected": [],
                    "matched": [], "note": "abstain check"}
        for kw in expected:
            if kw.lower() in all_text.lower():
                return {"passed": False, "score": 0.0, "expected": expected,
                        "matched": [kw], "note": "should have abstained"}
        return {"passed": True, "score": 1.0, "expected": expected,
                "matched": [], "note": "correctly abstained"}

    if is_summary:
        if not expected:
            if len(all_text) > 100:
                return {"passed": True, "score": 1.0, "expected": [],
                        "matched": [], "note": f"summary ({len(all_text)} chars)"}
            return {"passed": False, "score": 0.0, "expected": [],
                    "matched": [], "note": "summary too brief"}
        matched = [kw for kw in expected if kw.lower() in all_text.lower()]
        score = min(len(matched) / len(expected) if expected else 0.0, 0.8)
        if len(matched) >= min(min_facts, len(expected)):
            score = max(score, 0.8)
        return {"passed": score >= 0.5, "score": round(score, 4),
                "expected": expected, "matched": matched,
                "note": f"summary: {len(matched)}/{len(expected)} facts"}

    matched = [kw for kw in expected if kw.lower() in all_text.lower()]
    if not expected:
        return {"passed": True, "score": 1.0, "expected": [],
                "matched": [], "note": "no expectations"}
    score = len(matched) / len(expected)
    return {"passed": score >= 0.5, "score": round(score, 4),
            "expected": expected, "matched": matched,
            "top_content": [t[:120] for t in top5[:3]]}


def run_scenario_fused(c, ws_id, scenario) -> dict:
    """Run one BEAM scenario with multi-query fusion."""
    sid = scenario["id"]
    ability = scenario["ability"]
    seeds = scenario["seeds"]
    queries = scenario["queries"]
    print(f"  [{sid}] ({ability}) {scenario['description'][:60]}", flush=True)

    # Store seeds via direct reducer call (no embedding — keyword-only)
    stored = 0
    for seed in seeds:
        try:
            c._call("store_memory", [
                ws_id,                # workspace_id
                "",                   # peer_id
                "",                   # observer_id
                seed.get("memory_type", "world_fact"),  # memory_type
                seed["content"],      # content
                seed["content"][:200],# summary
                "[]",                 # entities_json
                seed.get("confidence", 0.9),  # confidence
                "",                   # source_session_id
                "",                   # source_message_id
                "",                   # images_json
            ])
            stored += 1
        except Exception:
            pass

    print(f"    Seeded {stored}/{len(seeds)} memories", flush=True)
    time.sleep(0.5)

    query_results = []
    for q in queries:
        t0 = time.time()
        results = beam_search_fused(c, ws_id, q["query"], limit=5)
        elapsed = time.time() - t0
        scoring = score_query(q, results)
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
        "seeded": stored, "queries_total": total, "queries_passed": passed,
        "accuracy": round(avg_score, 4), "avg_latency_ms": round(avg_latency, 1),
        "query_results": query_results,
    }


def main():
    parser = argparse.ArgumentParser(description="BEAM — multi-query fusion eval")
    parser.add_argument("--output", default="/tmp/beam_fused_results.json",
                        help="Output JSON path")
    args = parser.parse_args()

    with open(SCENARIOS_PATH) as f:
        scenarios = json.load(f)["scenarios"]

    print(f"BEAM Multi-Query Fusion Eval — {len(scenarios)} scenarios", flush=True)

    c = _make_client()
    ws = c.create_workspace("beam-fused-" + _uuid.uuid4().hex[:8])
    WS_ID = ws["id"]
    print(f"Workspace: {WS_ID}", flush=True)

    results = []
    for scenario in scenarios:
        result = run_scenario_fused(c, WS_ID, scenario)
        results.append(result)

        # Per-ability running tally
        by_ability = defaultdict(lambda: {"passed": 0, "total": 0})
        for r in results:
            by_ability[r["ability"]]["passed"] += r["queries_passed"]
            by_ability[r["ability"]]["total"] += r["queries_total"]
        total_pass = sum(v["passed"] for v in by_ability.values())
        total_q = sum(v["total"] for v in by_ability.values())
        pct = round(total_pass / total_q * 100, 1) if total_q else 0
        by_ability_str = " | ".join(
            f"{ab}:{v['passed']}/{v['total']}={round(v['passed']/v['total']*100,1) if v['total'] else 0}%"
            for ab, v in sorted(by_ability.items())
        )
        print(f"  Running: {total_pass}/{total_q}={pct}%  {by_ability_str}", flush=True)

    # Aggregate
    by_ability = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        by_ability[r["ability"]]["passed"] += r["queries_passed"]
        by_ability[r["ability"]]["total"] += r["queries_total"]
        r.pop("query_results", None)  # strip verbose results

    total_pass = sum(v["passed"] for v in by_ability.values())
    total_q = sum(v["total"] for v in by_ability.values())
    overall_accuracy = total_pass / total_q if total_q else 0

    print(f"\n{'='*60}", flush=True)
    print(f"  BEAM RESULTS — Multi-Query Fusion", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Overall: {total_pass}/{total_q} = {overall_accuracy*100:.1f}%", flush=True)
    for ab, st in sorted(by_ability.items()):
        pct = st["passed"] / st["total"] * 100 if st["total"] else 0
        print(f"  {ab} ({ABILITY_NAMES.get(ab, '?')}): {st['passed']}/{st['total']} = {pct:.1f}%", flush=True)

    out = {
        "benchmark": "BEAM (Multi-Query Fusion)",
        "scenarios": len(scenarios),
        "workspace": WS_ID,
        "overall": {
            "passed": total_pass,
            "total": total_q,
            "accuracy": round(overall_accuracy, 4),
        },
        "by_ability": {
            ab: {"passed": st["passed"], "total": st["total"],
                 "accuracy": round(st["passed"] / st["total"], 4) if st["total"] else 0}
            for ab, st in sorted(by_ability.items())
        },
        "scenario_results": results,
        "comparison": {
            "standalone_bm25": {"accuracy": 0.829},
            "previous_sdk_pipeline": {"accuracy": 0.634},
            "multi_query_fusion": {"accuracy": round(overall_accuracy, 4)},
        },
    }

    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved to {args.output}", flush=True)

    # Also save in project root
    project_out = os.path.join(Path(__file__).resolve().parent.parent, "benchmark_results_beam_fused.json")
    with open(project_out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved to {project_out}", flush=True)

    return out


if __name__ == "__main__":
    main()
