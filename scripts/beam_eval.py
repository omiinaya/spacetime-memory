#!/usr/bin/env python3
"""BEAM -- Belief-based Evaluation for Artificial Memory.

Evaluates Spacetime Memory's ability to handle belief-based queries across
10 ability dimensions defined by the BEAM benchmark (ICLR 2026):

  IE  - Information Extraction
  MR  - Memory Retrieval
  TR  - Temporal Reasoning
  ABS - Abstractive Summarization / Abstention
  CR  - Counterfactual Reasoning
  KU  - Knowledge Updating
  EO  - Entity Ordering
  IF  - Inference
  PF  - Property/Attribute Following
  SUM - Summarization

Usage:
    python3 scripts/beam_eval.py [--output /tmp/beam_results.json] [--seed-only]
    python3 scripts/beam_eval.py [--workspace-id <id>] [--benchmark-only]
    python3 scripts/beam_eval.py [--standalone]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import uuid as _uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(REPO_ROOT, "data")
SCENARIOS_PATH = os.path.join(DATA_DIR, "beam_scenarios.json")

try:
    import httpx
    from spacetime_memory import Client
    HAVE_CLIENT = True
except ImportError:
    HAVE_CLIENT = False


DB = os.environ.get("SPACETIMEDB_DB", "")
HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = int(os.environ.get("SPACETIMEDB_PORT", 3001))
EMB = os.environ.get("EMBEDDER_URL", "http://localhost:9090")
TANTIVY_URL = "http://localhost:9091"
EMBEDDER_API_KEY = os.environ.get("OPENAI_API_KEY", "")

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


# ── Standalone helpers ────────────────────────────────────────────────

_EMBED_CACHE: dict[str, list[float]] = {}


def _get_embedding(text: str, max_retries: int = 3) -> list[float]:
    import urllib.request, urllib.error
    if text in _EMBED_CACHE:
        return _EMBED_CACHE[text]
    body = json.dumps({"model": "BAAI/bge-m3", "input": text}).encode()
    last_error = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                f"{EMB}/v1/embeddings", data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {EMBEDDER_API_KEY}"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                emb = json.loads(resp.read())["data"][0]["embedding"]
                _EMBED_CACHE[text] = emb
                return emb
        except (KeyError, IndexError):
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Embedding failed: {last_error}")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)) + 1e-10)


def _tokenize(text: str) -> list[str]:
    STOPWORDS = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "can", "shall", "to", "of", "in", "for", "on", "with", "at", "by",
        "from", "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then", "once",
        "here", "there", "when", "where", "why", "how", "all", "each", "every", "both",
        "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "but", "and", "or", "if",
        "while", "that", "this", "these", "those", "it", "its",
    }
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def _compute_bm25(query: str, corpus: list[str], k1: float = 1.2, b: float = 0.75) -> list[tuple[float, int]]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return [(0.0, i) for i in range(len(corpus))]
    n = len(corpus)
    avg_dl = sum(len(_tokenize(d)) for d in corpus) / max(n, 1)
    tokenized = [_tokenize(d) for d in corpus]
    idf = {}
    for token in set(q_tokens):
        nc = sum(1 for t in tokenized if token in t)
        idf[token] = math.log((n - nc + 0.5) / (nc + 0.5) + 1.0)
    scores = []
    for i in range(n):
        dt = tokenized[i]
        dl = len(dt)
        s = 0.0
        for token in q_tokens:
            tf = dt.count(token)
            if tf == 0:
                continue
            s += idf.get(token, 0) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / avg_dl)))
        scores.append(s)
    indexed = [(scores[i], i) for i in range(n)]
    indexed.sort(key=lambda x: -x[0])
    return indexed


# ── SDK helpers ──────────────────────────────────────────────────────


def _make_client() -> "Client":
    """Create authenticated client, auto-discovering DB identity via HTTP API."""
    global DB
    if not DB:
        # v2.6.1 API: /v1/database returns { "databases": [...] } 
        # Each entry has identity in __identity__ format
        try:
            resp = httpx.get(f"http://{HOST}:{PORT}/v1/database", timeout=15)
            if resp.status_code == 200:
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
                elif isinstance(dbs, list) and len(dbs) > 0:
                    entry = dbs[0]
                    if isinstance(entry, dict):
                        ident = entry.get("identity", {})
                        if isinstance(ident, dict):
                            DB = ident.get("__identity__", "").lstrip("0x")
                        else:
                            DB = str(ident)
                    elif isinstance(entry, str):
                        DB = entry
        except Exception:
            pass
        if not DB:
            print("WARNING: Could not auto-discover DB identity via HTTP API.")
    resp = httpx.get(f"http://{HOST}:{PORT}/v1/database/{DB}", timeout=5)
    token = resp.headers.get("spacetime-identity-token", "")
    identity = resp.headers.get("spacetime-identity", "")
    c = Client(database=DB, embedder_url=EMB, token=token, host=HOST, port=PORT)
    try:
        c._call("register", [f"beam-eval-{_uuid.uuid4().hex[:8]}", "beameval789", identity])
    except (OSError, json.JSONDecodeError):
        pass
    except RuntimeError:
        pass
    return c


def _index_tantivy(http: "httpx.Client", ws_id: str, entity_id: str, content: str) -> None:
    try:
        http.post(
            f"{TANTIVY_URL}/index",
            json={"workspace_id": ws_id, "entity_id": entity_id,
                  "content": content, "entity_type": "memory"},
            timeout=5,
        )
    except (OSError, json.JSONDecodeError):
        pass


def _find_entity_id(c: "Client", ws_id: str, content: str, max_retries: int = 3) -> str | None:
    for _ in range(max_retries):
        mems = c._query("memory", workspace_id=ws_id, columns=["id", "content"])
        for m in reversed(mems):
            if m.get("content", "").strip() == content.strip():
                return m["id"]
        time.sleep(1)
    return None


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    tl = text.lower()
    return [kw for kw in keywords if kw.lower() in tl]


# ── Scoring ──────────────────────────────────────────────────────────


def score_query(query_spec: dict, results: list[dict]) -> dict:
    expected = query_spec.get("expected_content", [])
    expect_abstain = query_spec.get("expect_abstain", False)
    is_summary = query_spec.get("summary", False)
    min_facts = query_spec.get("min_facts", 3)

    top5 = [r.get("memory_content", r.get("content", "")) for r in results[:5]]
    all_text = " ".join(top5)

    if expect_abstain:
        if not expected:
            return {"passed": True, "score": 1.0, "expected": [],
                    "matched": [], "note": "abstain check - no specific expected content"}
        for kw in expected:
            if kw.lower() in all_text.lower():
                return {"passed": False, "score": 0.0, "expected": expected,
                        "matched": [kw], "note": "should have abstained but matched"}
        return {"passed": True, "score": 1.0, "expected": expected,
                "matched": [], "note": "correctly abstained"}

    if is_summary:
        if not expected:
            if len(all_text) > 100:
                return {"passed": True, "score": 1.0, "expected": [],
                        "matched": [], "note": f"summary produced ({len(all_text)} chars)"}
            return {"passed": False, "score": 0.0, "expected": [],
                    "matched": [], "note": "summary too brief"}
        matched = [kw for kw in expected if _contains_any(all_text, [kw])]
        score = len(matched) / len(expected) if expected else 0.0
        if len(matched) >= min(min_facts, len(expected)):
            score = max(score, 0.8)
        return {"passed": score >= 0.5, "score": round(score, 4),
                "expected": expected, "matched": matched,
                "note": f"summary: {len(matched)}/{len(expected)} facts covered"}

    matched = [kw for kw in expected if _contains_any(all_text, [kw])]
    if not expected:
        return {"passed": True, "score": 1.0, "expected": [],
                "matched": [], "note": "no specific expectations"}
    score = len(matched) / len(expected)
    return {"passed": score >= 0.5, "score": round(score, 4),
            "expected": expected, "matched": matched,
            "top_content": [t[:120] for t in top5[:3]]}


# ── Standalone search ────────────────────────────────────────────────


def _standalone_search(query: str, seeds: list[dict]) -> list[dict]:
    corpus = [s["content"] for s in seeds]
    bm25_scores = _compute_bm25(query, corpus)
    fused = []
    for i in range(len(corpus)):
        kw = bm25_scores[i][0]
        max_kw = bm25_scores[0][0] if bm25_scores and bm25_scores[0][0] > 0 else 1.0
        fused.append((kw / max_kw, i))
    fused.sort(key=lambda x: -x[0])
    return [{"content": corpus[idx], "score": round(fused[j][0], 4)}
            for j, (_, idx) in enumerate(fused[:5])]


# ── Scenario Runners ─────────────────────────────────────────────────


def run_scenario_sdk(c, http, scenario, ws_id, seed_only=False):
    sid = scenario["id"]
    ability = scenario["ability"]
    seeds = scenario["seeds"]
    queries = scenario["queries"]
    print(f"  [{sid}] ({ability}) {scenario['description'][:60]}", flush=True)

    entity_ids = {}
    for i, seed in enumerate(seeds):
        try:
            c.store(workspace_id=ws_id, content=seed["content"],
                    memory_type=seed.get("memory_type", "world_fact"),
                    peer_id="beam-eval", confidence=seed.get("confidence", 0.9))
        except (OSError, json.JSONDecodeError):
            print(f"    SEED ERROR [{i}]: {e}", flush=True)
            continue
        eid = _find_entity_id(c, ws_id, seed["content"])
        if eid:
            entity_ids[i] = eid
            _index_tantivy(http, ws_id, eid, seed["content"])
    print(f"    Seeded {len(entity_ids)}/{len(seeds)} memories", flush=True)
    if seed_only:
        return {"id": sid, "ability": ability, "seeded": len(entity_ids), "seed_only": True}
    time.sleep(0.5)

    query_results = []
    for q in queries:
        t0 = time.time()
        try:
            results = c.search(ws_id, query=q["query"], limit=5,
                               semantic=True, rerank=False, query_expansion=False)
        except (OSError, json.JSONDecodeError):
            results = []
            print(f"    QUERY ERROR '{q['query'][:40]}': {e}", flush=True)
        elapsed = time.time() - t0
        scoring = score_query(q, results)
        query_results.append({"query": q["query"], "latency_ms": round(elapsed * 1000, 1), **scoring})

    passed = sum(1 for qr in query_results if qr["passed"])
    total = len(query_results)
    avg_score = sum(qr["score"] for qr in query_results) / total if total else 0.0
    avg_latency = sum(qr.get("latency_ms", 0) for qr in query_results) / total if total else 0.0
    return {"id": sid, "ability": ability, "description": scenario["description"],
            "difficulty": scenario.get("difficulty", "unknown"), "seeded": len(entity_ids),
            "queries_total": total, "queries_passed": passed, "accuracy": round(avg_score, 4),
            "avg_latency_ms": round(avg_latency, 1), "query_results": query_results}


def run_scenario_standalone(scenario):
    sid = scenario["id"]
    ability = scenario["ability"]
    seeds = scenario["seeds"]
    queries = scenario["queries"]
    print(f"  [{sid}] ({ability}) {scenario['description'][:60]}", flush=True)

    query_results = []
    for q in queries:
        t0 = time.time()
        try:
            results = _standalone_search(q["query"], seeds)
        except (OSError, json.JSONDecodeError):
            results = []
            print(f"    QUERY ERROR '{q['query'][:40]}': {e}", flush=True)
        elapsed = time.time() - t0
        scoring = score_query(q, results)
        query_results.append({"query": q["query"], "latency_ms": round(elapsed * 1000, 1), **scoring})

    passed = sum(1 for qr in query_results if qr["passed"])
    total = len(query_results)
    avg_score = sum(qr["score"] for qr in query_results) / total if total else 0.0
    avg_latency = sum(qr.get("latency_ms", 0) for qr in query_results) / total if total else 0.0
    return {"id": sid, "ability": ability, "description": scenario["description"],
            "difficulty": scenario.get("difficulty", "unknown"), "seeded": len(seeds),
            "queries_total": total, "queries_passed": passed, "accuracy": round(avg_score, 4),
            "avg_latency_ms": round(avg_latency, 1), "query_results": query_results}


# ── Reporting ────────────────────────────────────────────────────────


def print_results(scenario_results, meta, args):
    ability_results = {}
    for r in scenario_results:
        ability_results.setdefault(r["ability"], []).append(r)

    overall_scores = []
    total_queries = 0
    total_passed = 0
    total_latency = 0.0

    print()
    print("=" * 65)
    print("BEAM RESULTS -- Per Ability")
    print("=" * 65)
    print(f"  {'Ability':<8} {'Accuracy':>10} {'Passed/Total':>14} {'Latency':>10}")
    print(f"  {'-' * 8} {'-' * 10} {'-' * 14} {'-' * 10}")

    for ability_code in sorted(ability_results.keys()):
        results = ability_results[ability_code]
        acc = sum(r["accuracy"] for r in results) / len(results)
        passed = sum(r["queries_passed"] for r in results)
        total = sum(r["queries_total"] for r in results)
        lat = sum(r["avg_latency_ms"] for r in results) / len(results)
        name = ABILITY_NAMES.get(ability_code, ability_code)
        overall_scores.append({"ability": ability_code, "name": name,
                               "accuracy": round(acc, 4), "passed": passed,
                               "total": total, "avg_latency_ms": round(lat, 1)})
        total_queries += total
        total_passed += passed
        total_latency += lat
        print(f"  {ability_code:<8} {acc:>9.1%}  {passed:>4}/{total:<4}    {lat:>7.0f}ms")

    overall_accuracy = total_passed / total_queries if total_queries else 0.0
    print(f"  {'-' * 8} {'-' * 10} {'-' * 14} {'-' * 10}")
    print(f"  {'TOTAL':<8} {overall_accuracy:>9.1%}  {total_passed:>4}/{total_queries:<4}"
          f"    {total_latency / len(scenario_results):>7.0f}ms")
    print()

    # Zero-score queries
    zero_queries = []
    for sr in scenario_results:
        for qr in sr.get("query_results", []):
            if qr.get("score", 1.0) == 0.0:
                zero_queries.append({"scenario": sr["id"], "ability": sr["ability"],
                                     "query": qr["query"], "expected": qr.get("expected", [])})
    if zero_queries:
        print(f"Zero-score queries ({len(zero_queries)}):")
        for zq in zero_queries:
            exp = ", ".join(zq["expected"][:3])
            print(f"  X [{zq['ability']}/{zq['scenario']}] {zq['query'][:60]}")
            if exp:
                print(f"    expected: {exp}")
        print()

    result = {
        "meta": {
            "name": "BEAM -- Belief-based Evaluation for Artificial Memory",
            "version": meta["version"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "abilities": meta["abilities"],
            "config": {
                "mode": "standalone" if getattr(args, "standalone", False) else "sdk",
                "embedder": "bm25-only (no embedder in standalone)",
                "keyword": "in-memory BM25" if getattr(args, "standalone", False) else "Tantivy BM25 sidecar",
                "fusion_model": "semantic:0.65, keyword:0.25, graph:0.05, temporal:0.05",
            },
        },
        "overall": {
            "accuracy": round(overall_accuracy, 4),
            "scenarios": len(scenario_results),
            "total_queries": total_queries,
            "passed_queries": total_passed,
            "avg_latency_ms": round(total_latency / len(scenario_results) if scenario_results else 0, 1),
        },
        "per_ability": overall_scores,
        "scenarios": [{k: v for k, v in sr.items() if k != "query_results"}
                      for sr in scenario_results],
        "details": [{"scenario": sr["id"], "ability": sr["ability"],
                     "query_results": sr.get("query_results", [])}
                    for sr in scenario_results],
    }

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Results saved to {args.output}")

    beam_file = os.path.join(REPO_ROOT, "benchmark_results_beam.json")
    with open(beam_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Results saved to {beam_file}")
    return result


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="BEAM -- Belief-based Evaluation for Artificial Memory")
    parser.add_argument("--output", default="/tmp/beam_results.json", help="Output JSON path")
    parser.add_argument("--seed-only", action="store_true", help="Only seed data, skip benchmarks")
    parser.add_argument("--benchmark-only", action="store_true", help="Only run benchmarks (skip seeding)")
    parser.add_argument("--workspace-id", default="", help="Existing workspace ID for benchmark-only mode")
    parser.add_argument("--no-tantivy", action="store_true", help="Skip Tantivy indexing")
    parser.add_argument("--standalone", action="store_true", help="Run in standalone mode (no STDB Client)")
    parser.add_argument("--scenario", default="", help="Run only specific scenario (by ID prefix)")
    args = parser.parse_args()

    if not os.path.exists(SCENARIOS_PATH):
        print(f"ERROR: scenarios file not found at {SCENARIOS_PATH}")
        sys.exit(1)

    with open(SCENARIOS_PATH) as f:
        data = json.load(f)

    scenarios = data["scenarios"]
    meta = data["meta"]

    if args.scenario:
        scenarios = [s for s in scenarios if s["id"].startswith(args.scenario)]
        if not scenarios:
            print(f"No scenarios matching prefix: {args.scenario}")
            sys.exit(1)

    print(f"BEAM -- Belief-based Evaluation for Artificial Memory")
    print(f"  Scenarios: {len(scenarios)}")
    print(f"  Abilities: {', '.join(meta['abilities'].keys())}")
    print(f"  Data: {SCENARIOS_PATH}")
    print(f"  Mode: {'standalone' if args.standalone else 'sdk (SpacetimeDB Client)'}")
    print()

    if args.standalone or not HAVE_CLIENT:
        print("Running standalone mode (BM25-only, no embedder)...")
        print()
        scenario_results = [run_scenario_standalone(s) for s in scenarios]
        for sr in scenario_results:
            acc = sr["accuracy"]
            passed = sr["queries_passed"]
            total = sr["queries_total"]
            lat = sr["avg_latency_ms"]
            mark = "V" if acc >= 0.5 else "X"
            print(f"    -> {mark} accuracy={acc:.1%} ({passed}/{total}) latency={lat:.0f}ms", flush=True)
        print_results(scenario_results, meta, args)
        return

    # SDK mode
    c = _make_client()
    http = httpx.Client(timeout=10)

    ws_id = args.workspace_id
    if not ws_id:
        ws_name = f"beam-eval-{os.urandom(4).hex()}"
        ws = c.create_workspace(ws_name, "BEAM benchmark workspace")
        ws_id = ws["id"]
        c._call("set_workspace_visibility", [ws_id, True])
        print(f"  Created workspace: {ws_id}")
    else:
        print(f"  Using workspace: {ws_id}")
    print()

    scenario_results = []
    for scenario in scenarios:
        result = run_scenario_sdk(c, http, scenario, ws_id, seed_only=args.seed_only)
        scenario_results.append(result)
        if not args.seed_only:
            acc = result["accuracy"]
            passed = result["queries_passed"]
            total = result["queries_total"]
            lat = result["avg_latency_ms"]
            mark = "V" if acc >= 0.5 else "X"
            print(f"    -> {mark} accuracy={acc:.1%} ({passed}/{total}) latency={lat:.0f}ms", flush=True)

    if args.seed_only:
        print(f"Seeding complete. Workspace ID: {ws_id}")
        print(f"Run with --workspace-id {ws_id} --benchmark-only to benchmark.")
        return

    print_results(scenario_results, meta, args)


if __name__ == "__main__":
    main()
