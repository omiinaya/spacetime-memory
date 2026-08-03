#!/usr/bin/env python3
"""
Repair contamination-damaged LoCoMo per-question results.

On 2026-08-03 an STDB restart (systemd Restart=always, 13:45-14:01 EDT) took the
database down ~15 min. During that window the Mem0 LoCoMo harness's search
retries all failed; StmemClient.search() returned [] (empty) after 5 attempts,
so those questions were answered + judged against EMPTY context. Their
per-question JSON files have retrieval.total_results == 0.

This script identifies every per-question file with total_results == 0,
re-runs the FULL search+answer+judge (same process_question machinery and same
StmemClient backend, same user_id) against the now-healthy STDB, overwrites the
damaged files, and reassembles the unified locomo_results_*.json.

Run ONLY after the benchmark process has fully exited. Safe: no --delete-data,
no restart, touches only the damaged questions.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# The harness modules import as `benchmarks.*`; run from the mem0/evaluation root.
HARNESS_ROOT = "$HOME/mem0/evaluation"
sys.path.insert(0, HARNESS_ROOT)

from benchmarks.common.stmem_client import StmemClient  # noqa: E402
from benchmarks.common.llm_client import LLMClient  # noqa: E402
from benchmarks.common.utils import save_result_json  # noqa: E402
from benchmarks.locomo.run import (  # noqa: E402
    load_dataset,
    expected_locomo_question_items,
    process_question,
    apply_locomo_judge_to_saved_result,
    compute_locomo_metrics,
    display_results,
    cutoff_label,
)


def find_contaminated(results_dir: str) -> list[str]:
    bad = []
    for p in Path(results_dir).glob("conv*_q*.json"):
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        retr = d.get("retrieval") or {}
        if retr.get("total_results") == 0:
            bad.append(p.stem)
    return sorted(bad)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--project-name", default="stmem-full5-zen")
    ap.add_argument("--db", default="spacetime-memory-v2")
    ap.add_argument("--stmem-host", default="127.0.0.1")
    ap.add_argument("--stmem-port", default=3001)
    ap.add_argument("--run-id", default="a2e9b6fd", help="run_id used by the live run (from user_id suffix)")
    ap.add_argument("--answerer-model", default="deepseek-v4-flash-free")
    ap.add_argument("--judge-model", default="deepseek-v4-flash-free")
    ap.add_argument("--top-k", type=int, default=200)
    ap.add_argument("--max-workers", type=int, default=4)
    ap.add_argument("--cutoff", type=int, nargs="+", default=[7, 30, 90, 180])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bad = find_contaminated(args.results_dir)
    print(f"Contaminated (total_results==0): {len(bad)}")
    for q in bad:
        print("  ", q)
    if args.dry_run:
        return
    if not bad:
        print("Nothing to repair.")
        return

    # Build dataset + the harness's expected item list (same as the live run).
    dataset = load_dataset(args.dataset)
    categories = [1, 2, 3, 4, 5]
    expected = expected_locomo_question_items(dataset, categories, max_questions=None)
    q_by_id = {qid: (conv, qi, qa) for qid, conv, qi, qa in expected}

    mem0 = StmemClient(db=args.db, host=args.stmem_host, port=args.stmem_port,
                       project_name=args.project_name)
    answerer = LLMClient(model=args.answerer_model, provider="custom")
    judge_llm = LLMClient(model=args.judge_model, provider="custom")

    run_id = args.run_id
    sem = asyncio.Semaphore(args.max_workers)

    async def repair(qid):
        if qid not in q_by_id:
            return qid, False
        conv_idx, qi, qa = q_by_id[qid]
        user_id = f"locomo_{conv_idx}_{run_id}"
        path = Path(args.results_dir) / f"{qid}.json"
        async with sem:
            res = await process_question(
                qa, qi, conv_idx, user_id, mem0, answerer, judge_llm,
                args.cutoffs, args.top_k, None, None, None, False, None,
            )
            if res.get("retrieval", {}).get("total_results", 0) == 0:
                return qid, False
            save_result_json(str(path), res)
            return qid, True

    # Warm auth once (registers bench-<project> identity) before parallel repair.
    try:
        await mem0.self_register()
    except Exception as e:  # noqa: BLE001
        print("self_register failed (non-fatal):", e)

    results = await asyncio.gather(*[repair(q) for q in bad])
    ok = [q for q, did in results if did]
    failed = [q for q, did in results if not did]
    print(f"Repaired: {len(ok)}  Remain-damaged: {len(failed)}")
    if failed:
        print("  STILL DAMAGED:", failed)

    # Reassemble the unified results (same layout run.py writes).
    qids = sorted(p.stem for p in Path(args.results_dir).glob("conv*_q*.json"))
    evals = [json.loads((Path(args.results_dir) / f"{qid}.json").read_text()) for qid in qids]
    metrics = compute_locomo_metrics(evals, args.cutoffs)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(args.results_dir, f"locomo_results_{ts}.json")
    save_result_json(out, {
        "metadata": {
            "benchmark": "locomo",
            "project_name": args.project_name,
            "run_id": "repaired-after-stdb-restart",
            "timestamp": ts,
            "answerer_model": args.answerer_model,
            "judge_model": args.judge_model,
            "provider": "custom",
            "top_k": args.top_k,
            "top_k_cutoffs": [cutoff_label(c) for c in args.cutoffs],
            "total_questions": len(evals),
            "evaluate_only": True,
            "repair_note": f"re-searched+re-judged {len(ok)} questions after STDB restart outage",
        },
        "metrics_by_cutoff": metrics,
        "evaluations": evals,
    })
    print(f"Reassembled: {out}")
    display_results(metrics, args.cutoffs)


if __name__ == "__main__":
    asyncio.run(main())