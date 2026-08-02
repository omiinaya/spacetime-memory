#!/usr/bin/env python3
"""Standardized BEAM Benchmark — apples-to-apples with Mem0.

Uses the same judge methodology as Mem0's open-source benchmark suite.

Two modes:
  --stdb   : Use real STDB pipeline (default)
  --bm25   : Use in-process BM25 for baseline comparison

Usage:
  python scripts/benchmarks/run_beam.py --stdb --limit 10
  python scripts/benchmarks/run_beam.py --bm25
"""

import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "sdk" / "python"))

# Share judge + LLM infrastructure
from run_locomo import (
    llm_judge, generate_answer, generate_query_variations,
    LLM_JUDGE_MODEL, LLM_ANSWER_MODEL, SimpleBM25,
)

BEAM_DATA = str(Path(__file__).resolve().parent.parent.parent / "data" / "beam_scenarios.json")

# BEAM ability types
ABILITY_NAMES = {
    "IE": "Information Extraction",
    "MR": "Memory Retrieval",
    "CR": "Counterfactual Reasoning",
    "ABS": "Abstention",
    "TR": "Temporal Reasoning",
    "KU": "Knowledge Updating",
    "PF": "Property Following",
    "EO": "Entity Ordering",
    "IF": "Inference",
    "SUM": "Summarization",
    "ALL": "End-to-end Narrative",
}


def load_dataset(path: str = BEAM_DATA) -> list[dict]:
    """Load BEAM scenarios."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"BEAM data not found at {path}")
    with open(path) as f:
        return json.load(f)


# ─── STDB Pipeline ───────────────────────────────────────────────────────────

def store_scenario_stdb(client, workspace_id: str, scenario: dict):
    """Store a BEAM scenario's content into STDB."""
    # BEAM stores content in seeds[]
    seeds = scenario.get("seeds", [])
    for seed in seeds:
        content = seed if isinstance(seed, str) else seed.get("text", seed.get("content", str(seed)))
        if content:
            batch = [{
                "content": str(content),
                "summary": f"BEAM seed {scenario.get('id', '')}",
                "memory_type": "fact",
            }]
            client.store_batch(workspace_id, batch)


# ─── Evaluation ──────────────────────────────────────────────────────────────

def run_beam_evaluation(scenarios: list[dict], search_fn, judge_model: str = None) -> list[dict]:
    """Run BEAM evaluation."""
    global LLM_JUDGE_MODEL
    if judge_model:
        LLM_JUDGE_MODEL = judge_model

    results = []
    for idx, scenario in enumerate(scenarios):
        # BEAM format: queries[] with query + expected_content + score
        queries = scenario.get("queries", [])
        if not queries:
            # Try alternative field names
            queries = scenario.get("questions", scenario.get("qa", []))
        if not queries:
            continue

        ability = scenario.get("ability", scenario.get("type", "unknown"))
        scenario_id = scenario.get("id", scenario.get("name", idx))

        for q in queries:
            question = q.get("query", q.get("question", ""))
            expected = q.get("expected_content", q.get("answer", q.get("expected", "")))
            if isinstance(expected, list):
                expected = "; ".join(str(e) for e in expected)

            print(f"\n[{idx+1}/{len(scenarios)}] [{ability}] Q: {str(question)[:80]}...", file=sys.stderr)

            # Search with multi-query fusion + RRF
            query_variations = generate_query_variations(question)
            all_batches = []
            for qv in query_variations:
                batch = search_fn(qv)
                all_batches.append(batch)

            # RRF fusion across query variations
            seen = {}
            fused = []
            for rank, batch_results in enumerate(all_batches):
                for r in batch_results:
                    content = r.get("content", r.get("memory", ""))
                    if content:
                        if content not in seen:
                            seen[content] = 1.0 / (rank + 60)
                            r["rrf_score"] = 1.0 / (rank + 60)
                            fused.append(r)
                        else:
                            seen[content] += 1.0 / (rank + 60)
                            for d in fused:
                                if d.get("content") == content or d.get("memory") == content:
                                    d["rrf_score"] = d.get("rrf_score", 0) + 1.0 / (rank + 60)
                                    break

            fused.sort(key=lambda x: -x.get("rrf_score", 0))
            deduped = fused[:200]

            # Generate answer
            answer = generate_answer(question, deduped)

            # Judge
            judgment = llm_judge(question, expected, answer)
            mark = "✓" if judgment["is_correct"] else "✗"
            print(f"  {mark} Expected: {str(expected)[:60]}", file=sys.stderr)
            print(f"  {mark} Got: {str(answer)[:60]}", file=sys.stderr)

            results.append({
                "scenario_id": str(scenario_id),
                "ability": ability,
                "ability_name": ABILITY_NAMES.get(ability, ability),
                "question": question,
                "expected": expected,
                "answer": answer,
                "is_correct": judgment["is_correct"],
                "reasoning": judgment["reasoning"],
            })

    return results


def compute_metrics(results: list[dict]) -> dict:
    """Compute per-ability and overall metrics."""
    total = len(results)
    correct = sum(1 for r in results if r.get("is_correct", False))

    metrics = {
        "overall": {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total * 100, 2) if total else 0,
        },
        "by_ability": {},
    }

    by_ability = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        a = r.get("ability", "UNKNOWN")
        by_ability[a]["total"] += 1
        by_ability[a]["name"] = r.get("ability_name", a)
        if r.get("is_correct", False):
            by_ability[a]["correct"] += 1

    for a, counts in sorted(by_ability.items()):
        metrics["by_ability"][a] = {
            "name": counts["name"],
            "total": counts["total"],
            "correct": counts["correct"],
            "accuracy": round(counts["correct"] / counts["total"] * 100, 2) if counts["total"] else 0,
        }

    return metrics


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Standardized BEAM Benchmark")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stdb", action="store_true", help="Use STDB pipeline (default)")
    group.add_argument("--bm25", action="store_true", help="Use BM25 baseline")
    parser.add_argument("--limit", type=int, default=None, help="Limit scenarios evaluated")
    parser.add_argument("--ability", type=str, default=None,
                        choices=list(ABILITY_NAMES.keys()),
                        help="Filter by ability type")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--judge-model", type=str, default=None)
    args = parser.parse_args()

    use_bm25 = args.bm25
    use_stdb = args.stdb or not args.bm25

    # Load dataset
    print("Loading BEAM scenarios...", file=sys.stderr)
    data = load_dataset()
    # Handle both list and dict-with-scenarios formats
    if isinstance(data, dict):
        for key in ["scenarios", "conversations", "data", "results"]:
            if key in data:
                data = data[key]
                print(f"  Extracted {len(data)} scenarios from '{key}' key", file=sys.stderr)
                break

    print(f"  {len(data)} scenarios", file=sys.stderr)

    if args.ability:
        data = [d for d in data if d.get("ability", d.get("type", "")) == args.ability]
        print(f"  Filtered to ability '{args.ability}': {len(data)} scenarios", file=sys.stderr)

    if args.limit and args.limit < len(data):
        data = data[:args.limit]
        print(f"  Limited to {args.limit} scenarios", file=sys.stderr)

    if use_stdb:
        print(f"\n=== STDB Pipeline === (judge: {args.judge_model or LLM_JUDGE_MODEL})", file=sys.stderr)

        from run_locomo import _auth_client as _auth
        client, _identity = _auth()
        ws = client.create_workspace(f"beam_{int(time.time())}")
        ws_id = ws.get("id")

        print(f"Workspace: {ws_id}", file=sys.stderr)
        print(f"\nStoring {len(data)} scenarios...", file=sys.stderr)
        for idx, scenario in enumerate(data):
            store_scenario_stdb(client, ws_id, scenario)
            if (idx + 1) % 20 == 0:
                print(f"  Stored {idx+1}/{len(data)}", file=sys.stderr)

        def search_fn(query):
            return client.search(ws_id, query, limit=200)

        results = run_beam_evaluation(data, search_fn, args.judge_model)

    else:
        print(f"\n=== BM25 Baseline === (judge: {args.judge_model or LLM_JUDGE_MODEL})", file=sys.stderr)

        # Build BM25 index from all scenarios
        all_texts = []
        for scenario in data:
            seeds = scenario.get("seeds", [])
            parts = []
            for seed in seeds:
                content = seed if isinstance(seed, str) else seed.get("text", seed.get("content", str(seed)))
                parts.append(str(content))
            all_texts.append("\n".join(parts) if parts else "")

        bm25 = SimpleBM25()
        bm25.fit(all_texts)

        def search_fn(query):
            return bm25.search(query, top_k=200)

        results = run_beam_evaluation(data, search_fn, args.judge_model)

    # Compute and report
    metrics = compute_metrics(results)
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"BEAM RESULTS (judge: {args.judge_model or LLM_JUDGE_MODEL})", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"OVERALL: {metrics['overall']['accuracy']:.2f}% "
          f"({metrics['overall']['correct']}/{metrics['overall']['total']})", file=sys.stderr)
    for a, d in sorted(metrics["by_ability"].items()):
        print(f"  {a:5s} {d['name']:30s}: {d['accuracy']:6.2f}%  ({d['correct']:4d}/{d['total']:4d})", file=sys.stderr)

    # Save
    output_path = args.output or str(Path(__file__).resolve().parent.parent.parent /
                                      "benchmarks" / "results" / "beam" /
                                      f"beam_results_{int(time.time())}.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    output_data = {
        "metadata": {
            "benchmark": "beam",
            "pipeline": "stdb" if use_stdb else "bm25",
            "judge_model": args.judge_model or LLM_JUDGE_MODEL,
            "total_questions": len(results),
            "timestamp": datetime.now().isoformat(),
        },
        "metrics": metrics,
        "results": results,
    }
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"\nResults saved to: {output_path}", file=sys.stderr)
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
