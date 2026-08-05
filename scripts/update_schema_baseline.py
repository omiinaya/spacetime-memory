#!/usr/bin/env python3
"""Regenerate the committed schema baseline (append-only enforcement).

The baseline at ``sdk/python/tests/data/schema_baseline.json`` is the LOWER
BOUND of the SpacetimeDB schema: ``tests/test_schema_evolution_policy.py``
asserts ``current schema ⊇ baseline`` with the policy's single allowed
transition (``T`` -> ``Option<T>``). New tables and new fields NEVER require
regeneration — the baseline only needs refreshing when schema legitimately
evolves and you want the new shape protected going forward.

DANGER: this script REFUSES to write a baseline that shrinks or re-types
existing entries (that would let a breaking change masquerade as a refresh).
If you genuinely need a breaking change (requires explicit policy deviation
approved in PR review), pass ``--force-breaking``.

Usage:
    python scripts/update_schema_baseline.py            # regenerate (safe)
    python scripts/update_schema_baseline.py --check    # exit 1 if stale/breaking
    python scripts/update_schema_baseline.py --force-breaking   # deviating
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python" / "tests"))

from schema_policy_lib import (  # noqa: E402
    BASELINE_PATH,
    dump_baseline,
    find_violations,
    load_baseline,
    parse_table_structs,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the committed baseline is stale or the "
        "current schema breaks the append-only contract.",
    )
    ap.add_argument(
        "--force-breaking",
        action="store_true",
        help="Allow writing a baseline that removes/renames/re-types existing "
        "entries (explicit policy deviation — only for approved breaking changes).",
    )
    args = ap.parse_args()

    current = parse_table_structs()

    violations: list[str] = []
    old = None
    if BASELINE_PATH.exists():
        old = load_baseline()
        violations = find_violations(old, current)

    if violations and not args.force_breaking:
        print("SCHEMA POLICY VIOLATIONS (append-only contract):\n", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "\nRefusing to regenerate: the new schema breaks SCHEMA_EVOLUTION_POLICY.md "
            "'Non-Additive Changes (Breaking)'. Fix the code (restore the field / "
            "keep the old type) — do NOT paper over it with a baseline refresh.\n"
            "If this is an APPROVED breaking deviation, re-run with --force-breaking.\n",
            file=sys.stderr,
        )
        return 1

    new_text = dump_baseline(current)
    is_identical = old is not None and BASELINE_PATH.read_text(encoding="utf-8") == new_text

    if args.check:
        # --check fails ONLY on contract violations. Pure additions (new tables
        # / new fields) are legal per policy and never fail --check; they are
        # reported as an advisory so contributors know a refresh is available.
        if violations:
            return 1  # already printed above
        if not is_identical:
            print(
                "NOTE: baseline is stale by PURE ADDITIONS only (no policy "
                "violations). Run `python scripts/update_schema_baseline.py` to "
                f"refresh {BASELINE_PATH} and extend protection to new fields."
            )
            return 0
        print(f"Baseline up to date: {BASELINE_PATH}")
        return 0

    if is_identical:
        print(f"Baseline up to date: {BASELINE_PATH}")
        return 0

    BASELINE_PATH.write_text(new_text, encoding="utf-8")
    added_tables = sorted(set(current) - set(old or {}))
    print(f"Wrote {BASELINE_PATH} ({len(current)} tables, "
          f"{sum(len(v) for v in current.values())} fields)")
    if added_tables:
        print("New tables now protected:", ", ".join(added_tables))
    if violations:
        print("WARNING: --force-breaking was used; review the violations above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
