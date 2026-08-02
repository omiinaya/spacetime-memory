#!/usr/bin/env python3
"""Re-judge saved LoCoMo results with a stronger answerer/judge model.

Uses the Mem0 harness's OWN answer-generation and judge prompts
(benchmarks.locomo.run.apply_locomo_judge_to_saved_result) against the
ALREADY-SAVED retrieval (identical search results) — no STDB re-search.

This isolates model quality from engine/retrieval quality: same memories,
different answerer/judge. Run after a full search pass to get the
"what would our score be with a better model" number.

Usage:
    python3 scripts/benchmarks/reloco_rejudge.py \
        --src /tmp/mem0bench/full/predicted_stmem-full \
        --dst /tmp/mem0bench/full/predicted_stmem-full-nemotron \
        --dataset data/locomo10.json \
        --answerer nemotron-3-ultra-free \
        --judge nemotron-3-ultra-free \
        --workers 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

# Make the mem0 evaluation package importable
MEM0_EVAL = "$HOME/mem0/evaluation"
if MEM0_EVAL not in sys.path:
    sys.path.insert(0, MEM0_EVAL)

from benchmarks.common.llm_client import LLMClient  # noqa: E402
from benchmarks.locomo.run import (  # noqa: E402
    apply_locomo_judge_to_saved_result,
    load_dataset,
    cutoff_label,
)

CUTOFFS = [10, 20, 50, 200]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Re-judge saved LoCoMo results with a stronger model")
    p.add_argument("--src", required=True, help="Source dir with saved conv*_q*.json results")
    p.add_argument("--dst", required=True, help="Destination dir (copy, re-judged)")
    p.add_argument("--dataset", required=True, help="Path to locomo10.json")
    p.add_argument("--answerer", default="nemotron-3-ultra-free")
    p.add_argument("--judge", default="nemotron-3-ultra-free")
    p.add_argument("--llm-base-url", default="http://localhost:4004/v1")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--rpm", type=int, default=200)
    p.add_argument("--only-wrong", action="store_true",
                   help="Only re-judge questions judged WRONG at top_200 (default: all)")
    p.add_argument("--limit", type=int, default=None, help="Max questions to re-judge (debug)")
    p.add_argument("--cutoffs", default="200",
                   help="Comma-separated cutoffs to re-judge (default: 200 = headline only)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    src = Path(args.src)
    dst = Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)

    cutoffs = [int(c) for c in args.cutoffs.split(",") if c.strip()]
    print(f"Re-judging cutoffs: {cutoffs}")

    dataset = load_dataset(args.dataset)
    # map question_id -> (conv_idx, qa dict)
    qa_map: dict[str, tuple[int, dict]] = {}
    for conv_idx, entry in enumerate(dataset):
        for qi, qa in enumerate(entry.get("qa", entry.get("qa_pairs", []))):
            qa_map[f"conv{conv_idx}_q{qi}"] = (conv_idx, qa)

    files = sorted(src.glob("conv*_q*.json"))
    if args.limit:
        files = files[: args.limit]
    print(f"Source: {len(files)} saved results in {src.name}")

    # Copy only the ones we'll re-judge
    todo = []
    for f in files:
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if args.only_wrong:
            j = data.get("cutoff_results", {}).get("top_200", {}).get("judgment")
            if j != "WRONG":
                continue
        todo.append((f, data))
    print(f"Re-judging {len(todo)} questions with answerer={args.answerer} judge={args.judge}")

    answerer = LLMClient(model=args.answerer, provider="openai", rpm=args.rpm,
                         base_url=args.llm_base_url)
    judge_llm = LLMClient(model=args.judge, provider="openai", rpm=args.rpm,
                          base_url=args.llm_base_url)
    sem = asyncio.Semaphore(args.workers)
    done = 0

    async def rejudge_one(f: Path, data: dict) -> None:
        nonlocal done
        qid = f.stem
        if qid not in qa_map:
            print(f"  SKIP {qid}: no qa entry in dataset")
            return
        conv_idx, qa = qa_map[qid]
        async with sem:
            try:
                await apply_locomo_judge_to_saved_result(
                    data, qa, conv_idx, answerer, judge_llm, cutoffs, evidence_lookup=None,
                )
                (dst / f.name).write_text(json.dumps(data, indent=2))
                done += 1
                if done % 25 == 0:
                    print(f"  {done}/{len(todo)} re-judged", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  FAIL {qid}: {type(e).__name__}: {e}", flush=True)

    async def run_all() -> None:
        await asyncio.gather(*[rejudge_one(qf, qd) for qf, qd in todo])

    asyncio.run(run_all())

    # Score the destination
    correct = {c: 0 for c in cutoffs}
    counts = {c: 0 for c in cutoffs}
    for f in dst.glob("conv*_q*.json"):
        data = json.loads(f.read_text())
        for c in cutoffs:
            j = data.get("cutoff_results", {}).get(cutoff_label(c), {}).get("judgment")
            counts[c] += 1
            if j == "CORRECT":
                correct[c] += 1
    print(f"\n=== RE-JUDGED SCORE ({args.answerer}) — {len(list(dst.glob('conv*_q*.json')))} questions ===")
    for c in cutoffs:
        if counts[c]:
            print(f"  {cutoff_label(c)}: {correct[c]}/{counts[c]} = {100*correct[c]/counts[c]:.1f}%")


if __name__ == "__main__":
    main()
