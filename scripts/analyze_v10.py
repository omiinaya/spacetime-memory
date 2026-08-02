#!/usr/bin/env python3
"""Analyze v10 self-consistency benchmark results.

Usage:
    python scripts/analyze_v10.py [/path/to/v10_results.json]
"""

import json
import sys
from pathlib import Path

CATEGORY_NAMES = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}


def analyze(path: str):
    data = json.load(open(path))
    rpt = data.get("report", {})
    results = data.get("results", [])

    print("=" * 60)
    print("  v10 Self-Consistency Results Analysis")
    print("=" * 60)

    print("\n  Category Breakdown:")
    for k, v in sorted(rpt.items()):
        if k.startswith("_"):
            continue
        print(f"    {k:20s}: {v['accuracy']:6.2f}%  ({v['correct']:4d}/{v['total']:4d})")

    p = rpt.get("__primary__", {})
    o = rpt.get("__overall__", {})
    print(f"    {'---':20s}")
    print(f"    {'PRIMARY':20s}: {p.get('accuracy', 0):6.2f}%  ({p.get('correct', 0):4d}/{p.get('total', 0):4d})")
    print(f"    {'OVERALL':20s}: {o.get('accuracy', 0):6.2f}%  ({o.get('correct', 0):4d}/{o.get('total', 0):4d})")

    # Compare with v9
    v9_path = Path(__file__).resolve().parent.parent / "benchmark_results_locomo_v9.json"
    if v9_path.exists():
        v9 = json.loads(v9_path.read_text())
        v9_rpt = v9.get("report", {})
        v9_p = v9_rpt.get("__primary__", {})
        v9_o = v9_rpt.get("__overall__", {})

        print(f"\n  {'─' * 60}")
        print(f"  Comparison with v9 (STDB Pipeline):")
        print(f"  {'─' * 60}")

        diff_p = p.get("accuracy", 0) - v9_p.get("accuracy", 0)
        diff_o = o.get("accuracy", 0) - v9_o.get("accuracy", 0)

        print(f"    v9  PRIMARY: {v9_p.get('accuracy', 0):6.2f}%")
        print(f"    v10 PRIMARY: {p.get('accuracy', 0):6.2f}%  (Δ {diff_p:+.2f}%)")
        print(f"    {'---':20s}")
        print(f"    v9  OVERALL: {v9_o.get('accuracy', 0):6.2f}%")
        print(f"    v10 OVERALL: {o.get('accuracy', 0):6.2f}%  (Δ {diff_o:+.2f}%)")

        # Category comparison
        print(f"\n    Category differences (v10 - v9):")
        for k in sorted(rpt):
            if k.startswith("_"):
                continue
            v10_acc = rpt[k].get("accuracy", 0) if k in rpt else 0
            v9_acc = v9_rpt.get(k, {}).get("accuracy", 0) if k in v9_rpt else 0
            diff = v10_acc - v9_acc
            marker = "↑" if diff > 2 else "↓" if diff < -2 else "→"
            print(f"      {marker} {k:20s}: v9={v9_acc:6.2f}%  v10={v10_acc:6.2f}%  (Δ {diff:+.2f}%)")

    # Self-consistency analysis
    print(f"\n  {'─' * 60}")
    print(f"  Self-Consistency Analysis:")
    print(f"  {'─' * 60}")

    correct = [r for r in results if r.get("is_correct")]
    wrong = [r for r in results if not r.get("is_correct")]

    if hasattr(results[0], "get") and "attempts" in results[0]:
        # v10 stores multiple attempts per question
        unanimous_correct = sum(1 for r in results if r.get("is_correct") and r.get("attempts", {}).get("correct_attempts", 0) == 3)
        unanimous_wrong = sum(1 for r in results if not r.get("is_correct") and r.get("attempts", {}).get("correct_attempts", 0) == 0)
        split = len(results) - unanimous_correct - unanimous_wrong
        print(f"    Unanimous correct (3/3): {unanimous_correct}")
        print(f"    Unanimous wrong (0/3):   {unanimous_wrong}")
        print(f"    Split votes:             {split}")
        print(f"    Majority correct:        {len(correct)}")
        print(f"    Majority wrong:          {len(wrong)}")

    # Wrong answer analysis
    if wrong:
        print(f"\n  {'─' * 60}")
        print(f"  Wrong Answer Patterns:")
        print(f"  {'─' * 60}")
        dont_know = sum(1 for r in wrong if any(p in (r.get("actual_answer", "") or "").lower() for p in ["i don't know", "not mention", "not provide"]))
        print(f"    'I don't know' when fact exists: {dont_know}")
        print(f"    Wrong/confabulated fact:         {len(wrong) - dont_know}")

        # Show examples
        print(f"\n    Examples:")
        for r in wrong[:5]:
            q = r.get("question", "")[:70]
            e = r.get("expected_answer", "")[:50]
            a = r.get("actual_answer", "")[:80]
            print(f"      Q: {q}")
            print(f"      E: {e}")
            print(f"      A: {a}")
            print()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v10_full_results.json"
    analyze(path)
