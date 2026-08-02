#!/usr/bin/env python3
"""Standardized LongMemEval Benchmark — apples-to-apples with Mem0.

Uses the same judge methodology as Mem0's open-source benchmark suite.

Usage:
  python scripts/benchmarks/run_longmemeval.py --stdb --limit 10
  python scripts/benchmarks/run_longmemeval.py --bm25 --limit 5
"""

import json
import logging
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "sdk" / "python"))

# Share judge + LLM infrastructure from LoCoMo runner
from run_locomo import (
    llm_judge, generate_answer, generate_query_variations,
    LLM_JUDGE_MODEL, LLM_ANSWER_MODEL,
    _llm_call, _env_path, _API_KEYS, _API_KEY_IDX,
    JUDGE_SYSTEM_PROMPT as _JUDGE_SYS,
)

DATA_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "longmemeval_s.json")

QUESTION_TYPES = [
    "single-session-user", "single-session-assistant",
    "multi-session-user", "multi-session-assistant",
    "temporal-user", "temporal-assistant",
]


def load_dataset(path: str = DATA_PATH) -> list[dict]:
    """Load LongMemEval dataset."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"LongMemEval data not found at {path}. "
            f"Download from https://github.com/boschresearch/LongMemEval"
        )
    with open(path) as f:
        return json.load(f)


# ─── STDB Pipeline ───────────────────────────────────────────────────────────

def store_haystack_stdb(client, workspace_id: str, item: dict, idx: int, max_turns_per_chunk: int = 5):
    """Store the conversation haystack for a LongMemEval question into STDB.

    Chunks large sessions into multiple memories to avoid STDB reducer timeouts
    on oversized reducer calls.
    """
    # LongMemEval stores sessions in haystack_sessions (list of lists)
    sessions = item.get("haystack_sessions", item.get("haystack", []))
    if isinstance(sessions, list) and len(sessions) > 0:
        # Check if it's a flat list of messages or list of sessions
        if isinstance(sessions[0], list):
            # Nested: list of sessions, each a list of messages
            for si, session in enumerate(sessions):
                # Chunk: split long sessions into manageable pieces
                for chunk_start in range(0, len(session), max_turns_per_chunk):
                    chunk = session[chunk_start:chunk_start + max_turns_per_chunk]
                    turns = []
                    for msg in chunk:
                        role = msg.get("role", "?")
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            content = " ".join(c.get("text", str(c)) for c in content)
                        turns.append(f"{role}: {content}")
                    if turns:
                        content = "\n".join(turns)
                        # Skip if content is too large (>500KB)
                        if len(content.encode('utf-8')) > 500_000:
                            logger.warning(f"Q{idx} session {si} chunk {chunk_start} too large ({len(content)} chars), skipping")
                            continue
                        batch = [{
                            "content": content,
                            "summary": f"LongMemEval Q{idx} session {si} part {chunk_start//max_turns_per_chunk}",
                            "memory_type": "conversation",
                        }]
                        client.store_batch(workspace_id, batch)
                        time.sleep(0.5)  # Rate-limit: let STDB energy budget replenish
        else:
            # Flat: list of messages
            for chunk_start in range(0, len(sessions), max_turns_per_chunk):
                chunk = sessions[chunk_start:chunk_start + max_turns_per_chunk]
                turns = []
                for msg in chunk:
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(c.get("text", str(c)) for c in content)
                    turns.append(f"{role}: {content}")
                if turns:
                    content = "\n".join(turns)
                    if len(content.encode('utf-8')) > 500_000:
                        logger.warning(f"Q{idx} flat chunk {chunk_start} too large ({len(content)} chars), skipping")
                        continue
                    batch = [{
                        "content": content,
                        "summary": f"LongMemEval Q{idx} haystack part {chunk_start//max_turns_per_chunk}",
                        "memory_type": "conversation",
                    }]
                client.store_batch(workspace_id, batch)
                time.sleep(0.5)  # Rate-limit: let STDB energy budget replenish


def search_stdb(client, workspace_id: str, query: str, top_k: int = 200) -> list[dict]:
    """Search STDB."""
    return client.search(workspace_id, query, limit=top_k)


# ─── BM25 Pipeline ───────────────────────────────────────────────────────────

def build_bm25_index(items: list[dict]):
    """Build in-process BM25 index from all haystack data combined."""
    from run_locomo import SimpleBM25 as _BM25
    all_texts = []
    for item in items:
        sessions = item.get("haystack_sessions", item.get("haystack", []))
        if isinstance(sessions, list) and len(sessions) > 0:
            if isinstance(sessions[0], list):
                # Nested sessions
                all_conversations = []
                for session in sessions:
                    turns = []
                    for msg in session:
                        role = msg.get("role", "?")
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            content = " ".join(c.get("text", str(c)) for c in content)
                        turns.append(f"{role}: {content}")
                    all_conversations.append("\n".join(turns))
                all_texts.append("\n".join(all_conversations))
            else:
                # Flat messages
                turns = []
                for msg in sessions:
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(c.get("text", str(c)) for c in content)
                    turns.append(f"{role}: {content}")
                all_texts.append("\n".join(turns))
        else:
            all_texts.append("")
    bm25 = _BM25()
    bm25.fit(all_texts)
    return bm25


# ─── Evaluation Loop ─────────────────────────────────────────────────────────

def run_evaluation(items: list[dict], search_fn, judge_model: str = None,
                   resume: bool = False, checkpoint_path: str | None = None) -> list[dict]:
    """Run evaluation for a list of items using the provided search function.

    Supports checkpoint/resume: results are saved incrementally after every
    question. On resume, already-judged questions are skipped.
    """
    global LLM_JUDGE_MODEL
    if judge_model:
        LLM_JUDGE_MODEL = judge_model

    # Load checkpoint (resume support)
    results = []
    completed_indices = set()
    if resume and checkpoint_path and os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path) as f:
                ckpt = json.load(f)
            results = ckpt.get("results", [])
            completed_indices = set(ckpt.get("completed_indices", []))
            print(f"Resuming from checkpoint: {len(results)} results, "
                  f"{len(completed_indices)} questions already judged", file=sys.stderr)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not load checkpoint ({e}); starting fresh", file=sys.stderr)

    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = int(os.environ.get("LLM_MAX_CONSECUTIVE_FAILURES", "10"))
    for idx, item in enumerate(items):
        if idx in completed_indices:
            continue  # Already judged in a previous run

        question = item.get("question", "")
        expected = item.get("answer", "")
        qtype = item.get("question_type", "unknown")

        print(f"\n[{idx+1}/{len(items)}] [{qtype}] Q: {str(question)[:80]}...", file=sys.stderr)

        # Search
        query_variations = generate_query_variations(question)
        all_results = []
        for qv in query_variations:
            batch = search_fn(qv)
            all_results.extend(batch)

        # RRF fusion across query variations
        seen = {}
        fused = []
        for rank, r in enumerate(all_results):
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
        is_api_error = (str(answer).startswith("ERROR") or "api error" in str(answer))

        # Judge
        judgment = llm_judge(question, expected, answer)
        mark = "✓" if judgment["is_correct"] else "✗"
        print(f"  {mark} Expected: {str(expected)[:60]}", file=sys.stderr)
        print(f"  {mark} Got: {str(answer)[:60]}", file=sys.stderr)

        results.append({
            "question_id": item.get("question_id", idx),
            "question_type": qtype,
            "question": question,
            "expected": expected,
            "answer": answer,
            "is_correct": judgment["is_correct"],
            "reasoning": judgment["reasoning"],
        })
        completed_indices.add(idx)

        # Save checkpoint after every question
        if checkpoint_path:
            with open(checkpoint_path, "w") as f:
                json.dump({"results": results, "completed_indices": sorted(completed_indices)}, f)

        # Graceful abort on persistent LLM outage (proxy down, etc.)
        if is_api_error or "api error" in str(judgment.get("reasoning", "")):
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"\nABORT: {consecutive_failures} consecutive LLM failures — proxy may be down. "
                      f"Checkpoint saved ({len(results)} results). Exiting for launcher to retry.", file=sys.stderr)
                sys.exit(3)
        else:
            consecutive_failures = 0

    return results


def compute_metrics(results: list[dict]) -> dict:
    """Compute per-type and overall metrics."""
    total = len(results)
    correct = sum(1 for r in results if r["is_correct"])

    metrics = {
        "overall": {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total * 100, 2) if total else 0,
        },
        "by_type": {},
    }

    by_type = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        t = r["question_type"]
        by_type[t]["total"] += 1
        if r["is_correct"]:
            by_type[t]["correct"] += 1

    for t, counts in sorted(by_type.items()):
        metrics["by_type"][t] = {
            "total": counts["total"],
            "correct": counts["correct"],
            "accuracy": round(counts["correct"] / counts["total"] * 100, 2) if counts["total"] else 0,
        }

    return metrics


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Standardized LongMemEval Benchmark")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stdb", action="store_true", help="Use STDB pipeline (default)")
    group.add_argument("--bm25", action="store_true", help="Use BM25 baseline")
    parser.add_argument("--limit", type=int, default=None, help="Limit questions evaluated")
    parser.add_argument("--type", type=str, default=None, choices=QUESTION_TYPES,
                        help="Filter by question type")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--judge-model", type=str, default=None)
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint (skip already-judged questions)")
    parser.add_argument("--workspace-id", type=str, default=None, help="Reuse an existing workspace (implies --skip-ingest)")
    args = parser.parse_args()

    use_bm25 = args.bm25
    use_stdb = args.stdb or not args.bm25

    # Load dataset
    print("Loading LongMemEval dataset...", file=sys.stderr)
    data = load_dataset()
    print(f"  {len(data)} questions", file=sys.stderr)

    if args.type:
        data = [d for d in data if d.get("question_type") == args.type]
        print(f"  Filtered to type '{args.type}': {len(data)} questions", file=sys.stderr)

    if args.limit:
        data = data[:args.limit]
        print(f"  Limited to {args.limit} questions", file=sys.stderr)

    if use_stdb:
        print(f"\n=== STDB Pipeline === (judge: {args.judge_model or LLM_JUDGE_MODEL})", file=sys.stderr)

        # Import and auth
        from run_locomo import _auth_client as _auth
        client, _identity = _auth()
        # Increase timeout for large dataset operations
        client._http = __import__('httpx').Client(timeout=120.0)

        # Reuse existing workspace on resume
        if args.workspace_id:
            ws_id = args.workspace_id
            print(f"Reusing workspace {ws_id} (skip-ingest)", file=sys.stderr)
        else:
            ws = client.create_workspace(f"longmemeval_{int(time.time())}")
            ws_id = ws.get("id")

            # Store all haystacks
            print(f"\nStoring {len(data)} haystacks into workspace {ws_id}...", file=sys.stderr, flush=True)
            for idx, item in enumerate(data):
                store_haystack_stdb(client, ws_id, item, idx)
                time.sleep(1.0)  # Let STDB energy budget replenish between items
                if (idx + 1) % 50 == 0:
                    print(f"  Stored {idx+1}/{len(data)}", file=sys.stderr, flush=True)

        def search_fn(query):
            return search_stdb(client, ws_id, query)

        results_dir = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "results" / "longmemeval"
        os.makedirs(results_dir, exist_ok=True)
        checkpoint_path = results_dir / f"longmemeval_checkpoint_{ws_id}.json"
        results = run_evaluation(data, search_fn, args.judge_model,
                                 resume=args.resume, checkpoint_path=str(checkpoint_path))

    else:
        print(f"\n=== BM25 Baseline === (judge: {args.judge_model or LLM_JUDGE_MODEL})", file=sys.stderr)
        bm25 = build_bm25_index(data)

        def search_fn(query):
            return bm25.search(query, top_k=200)

        results = run_evaluation(data, search_fn, args.judge_model)

    # Compute and report
    metrics = compute_metrics(results)
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"LONGMEMEVAL RESULTS (judge: {args.judge_model or LLM_JUDGE_MODEL})", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"OVERALL: {metrics['overall']['accuracy']:.2f}% "
          f"({metrics['overall']['correct']}/{metrics['overall']['total']})", file=sys.stderr)
    for t, d in metrics["by_type"].items():
        print(f"  {t:30s}: {d['accuracy']:6.2f}%  ({d['correct']:4d}/{d['total']:4d})", file=sys.stderr)

    # Save
    output_path = args.output or str(Path(__file__).resolve().parent.parent.parent /
                                      "benchmarks" / "results" / "longmemeval" /
                                      f"longmemeval_results_{int(time.time())}.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    output_data = {
        "metadata": {
            "benchmark": "longmemeval",
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
