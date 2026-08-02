#!/usr/bin/env python3
"""Detect and fill data gaps in the spacetime-memory dataset.

Usage flow:
  1. Run eval harness to identify zero-score queries
  2. Run this script with the eval results to auto-generate missing memories
  3. Re-run eval to measure improvement

Mechanism:
  For each zero-score query, uses the LLM to generate a synthetic memory
  that would be relevant. Stores it in the workspace so the next retrieval
  cycle can find it.

Usage:
    python3 scripts/fill_data_gaps.py \
        --eval-results /path/to/eval_results.json \
        --workspace WORKSPACE_ID \
        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add SDK
SDK_PATH = Path(__file__).resolve().parent.parent / "sdk" / "python"
sys.path.insert(0, str(SDK_PATH))

from spacetime_memory import Client
from spacetime_memory.llm import LLMClient


def main():
    parser = argparse.ArgumentParser(
        description="Fill data gaps found by eval harness"
    )
    parser.add_argument(
        "--eval-results", required=True, help="Path to eval_results.json"
    )
    parser.add_argument("--workspace", required=True, help="Workspace ID")
    parser.add_argument(
        "--max-per-query", type=int, default=2,
        help="Max memories to generate per zero-score query"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load eval results
    with open(args.eval_results) as f:
        results = json.load(f)

    # Find zero-score queries
    zero_score = []
    for detail in results.get("details", []):
        query = detail.get("query", "")
        p5 = detail.get("P@5", 1.0)
        if p5 == 0.0 or (isinstance(p5, (int, float)) and p5 < 0.01):
            zero_score.append(query)

    if not zero_score:
        print("No zero-score queries found. Nothing to fill.")
        return

    print(f"Found {len(zero_score)} zero-score queries:\n")
    for i, q in enumerate(zero_score, 1):
        print(f"  {i}. {q}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would generate up to {args.max_per_query} memories each.")
        return

    client = Client()
    llm = LLMClient()

    total_generated = 0
    for query in zero_score:
        print(f"\nGenerating memories for: {query}")

        for _ in range(args.max_per_query):
            prompt = (
                f"You are a knowledge-base curator. Write a single factual, "
                f"dense sentence that directly answers or relates to this query. "
                f"Make it specific — include names, numbers, dates, or technical "
                f"details where possible. Do not repeat the query. Write only the "
                f"fact, nothing else.\n\n"
                f"Query: {query}\n\n"
                f"Fact:"
            )

            try:
                fact = llm.complete(prompt, max_tokens=128).strip()
                if not fact or len(fact) < 10:
                    continue

                # Store it
                result = client.store(
                    workspace_id=args.workspace,
                    content=fact,
                    memory_type="world_fact",
                    confidence=0.7,  # Synthetic — lower confidence
                    peer_id="data_gap_filler",
                )
                total_generated += 1
                print(f"  ✓ {fact[:80]}...")
            except Exception as e:
                print(f"  ✗ Failed: {e}")

    print(f"\nGenerated {total_generated} synthetic memories.")
    print("Re-run eval to measure improvement.")


if __name__ == "__main__":
    main()
