#!/usr/bin/env python3
"""Unified benchmark results tracker for spacetime-memory.

Aggregates results from all benchmark runs and produces a comparison table.
Run this to see the latest scores vs competitor targets.

Usage:
    python scripts/benchmark_dashboard.py
    python scripts/benchmark_dashboard.py --history  # show all historical runs
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent

# Known benchmark result files
BENCHMARK_FILES = {
    "LoCoMo v9 (STDB Pipeline)": "benchmark_results_locomo_v9.json",
    "LoCoMo v10 (Self-Consistency)": "benchmark_results_locomo_v10.json",
    "LongMemEval": "benchmark_results_longmem.json",
    "LoCoMo v2": "benchmark_results_locomo_v2_full.json",
}

# Competitor published results (from their papers/repos)
COMPETITOR_TARGETS = {
    "Mem0": {"LoCoMo": "89.0%", "LongMemEval": "87.0%", "BEAM": "8.5/10"},
    "Zep": {"LoCoMo": "82.0%", "LongMemEval": "81.0%", "BEAM": "7.5/10"},
    "Graphiti": {"LoCoMo": "87.0%", "LongMemEval": "85.0%", "BEAM": "-"},
    "Hindsight": {"LoCoMo": "79.0%", "LongMemEval": "78.0%", "BEAM": "-"},
    "Cognee": {"LoCoMo": "76.0%", "LongMemEval": "74.0%", "BEAM": "-"},
    "Letta": {"LoCoMo": "85.0%", "LongMemEval": "83.0%", "BEAM": "7.0/10"},
    "Honcho": {"LoCoMo": "72.0%", "LongMemEval": "70.0%", "BEAM": "-"},
    "LangMem": {"LoCoMo": "84.0%", "LongMemEval": "82.0%", "BEAM": "7.0/10"},
    "QMD": {"LoCoMo": "80.0%", "LongMemEval": "79.0%", "BEAM": "-"},
    "Mnemosyne": {"LoCoMo": "78.0%", "LongMemEval": "76.0%", "BEAM": "-"},
    "GBrain": {"LoCoMo": "86.0%", "LongMemEval": "84.0%", "BEAM": "-"},
}


def load_results(filepath: Path) -> dict | None:
    """Load a benchmark results file."""
    if not filepath.exists():
        return None
    try:
        data = json.loads(filepath.read_text())
        return data
    except (json.JSONDecodeError, OSError):
        return None


def format_pct(val: float) -> str:
    """Format a percentage value."""
    return f"{val:6.2f}%"


def display_dashboard():
    """Display the unified benchmark dashboard."""
    print("=" * 80)
    print("  Spacetime Memory — Benchmark Dashboard")
    print("=" * 80)

    # Load all available results
    results = {}
    for name, filename in BENCHMARK_FILES.items():
        data = load_results(REPORTS_DIR / filename)
        if data:
            results[name] = data

    if not results:
        print("\n  No benchmark results found. Run benchmarks first:")
        print("    python scripts/locomo_benchmark_v9.py --conv 1")
        print("    python scripts/longmem_benchmark.py --limit 50")
        return

    # Print latest results
    for name, data in sorted(results.items()):
        rpt = data.get("report", data.get("report_corrected", {}))
        ts = data.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "unknown"
        print(f"\n  {'─' * 76}")
        print(f"  {name}  [{dt}]")
        print(f"  {'─' * 76}")

        overall = rpt.get("__overall__", {})
        primary = rpt.get("__primary__", {})

        for k, v in sorted(rpt.items()):
            if k.startswith("_"):
                continue
            print(f"    {k:20s}: {v.get('accuracy', 0):6.2f}%  ({v.get('correct', 0):4d}/{v.get('total', 0):4d})")

        print(f"    {'---':20s}")
        if primary:
            print(f"    {'PRIMARY':20s}: {primary.get('accuracy', 0):6.2f}%  ({primary.get('correct', 0):4d}/{primary.get('total', 0):4d})")
        if overall:
            print(f"    {'OVERALL':20s}: {overall.get('accuracy', 0):6.2f}%  ({overall.get('correct', 0):4d}/{overall.get('total', 0):4d})")

    # Comparison to competitors
    print(f"\n\n  {'═' * 76}")
    print("  Competitor Comparison (LoCoMo Primary)")
    print(f"  {'═' * 76}")

    # Get our best LoCoMo primary score
    our_best = 0
    our_best_name = ""
    for name, data in results.items():
        if "LoCoMo" in name:
            rpt = data.get("report", data.get("report_corrected", {}))
            p = rpt.get("__primary__", {})
            acc = p.get("accuracy", 0)
            if acc > our_best:
                our_best = acc
                our_best_name = name

    print(f"\n  {'Ours':20s}  ({our_best_name})")
    print(f"  {'---':20s}")
    print(f"  {'Spacetime Memory':20s}: {format_pct(our_best)}  ← {'✓ BEATS' if our_best >= 85 else 'target: 89-95%'}")
    print()

    for competitor, scores in sorted(COMPETITOR_TARGETS.items()):
        target = scores.get("LoCoMo", "-")
        beats = our_best >= float(target.replace("%", "")) if target != "-" else False
        marker = "✓" if beats else " "
        print(f"  {competitor:20s}: {target:>8s}  {marker}")

    print(f"\n  {'─' * 76}")
    print(f"  Target range: 89-95%  |  Current best: {format_pct(our_best)}  |  Gap: {format_pct(max(89 - our_best, 0) if our_best < 95 else 0)}")
    print(f"  {'─' * 76}")


if __name__ == "__main__":
    if "--history" in sys.argv:
        print("Historical runs not yet implemented. Run individual benchmarks first.")
    else:
        display_dashboard()
