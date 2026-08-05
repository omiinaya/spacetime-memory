#!/usr/bin/env python3
"""Audit git history of the SpacetimeDB module for breaking (non-additive)
schema changes — SCHEMA_EVOLUTION_POLICY.md "Non-Additive Changes (Breaking)".

The committed baseline (sdk/python/tests/data/schema_baseline.json) anchors
the schema AT A POINT IN TIME: test_schema_evolution_policy.py asserts
current source ⊇ baseline. But a breaking change committed BEFORE the
baseline was generated — or papered over with
`scripts/update_schema_baseline.py --force-breaking` — is invisible to that
point-in-time check.

This audit closes that hole by walking `git log` of server/spacetimedb/src
and comparing every consecutive pair of commits with the SAME append-only
contract as the baseline:

    | Rename field    | Forbidden (add new, deprecate old, never remove) |
    | Change type     | Forbidden (add new field with the new type)      |
    | Remove field    | Forbidden (mark deprecated, leave in struct)     |
    | Required->opt   | Allowed ONLY as T -> Option<T>                   |
    | Optional->req   | Forbidden (impossible without migration)         |

Transient corrections: a breaking flip that was REVERTED in a later commit
(never shipped, final state restored) is recorded in
sdk/python/tests/data/schema_history_transient_exceptions.json. Every
exception entry is VALIDATED on every run:

  * it must match a real transition found in history (else: stale -> FAIL),
  * the field/table must be restored to the recorded type in the CURRENT
    schema (else: the breaking state still exists -> FAIL).

So the allowlist cannot be used to paper over a live violation — it only
documents corrections that already happened.

Usage:
    python scripts/audit_schema_history.py             # audit this repo
    python scripts/audit_schema_history.py --repo PATH  # audit another clone
    python scripts/audit_schema_history.py --commits 20 # only newest N src commits

Exit codes:
    0  history is append-only-clean (transient exceptions validated) — or no
       audit-able history (shallow clone, < 2 commits touching the module
       source, git not available)
    1  breaking transition found (not covered by a validated exception), a
       transient exception is stale/invalid, or the audit infrastructure failed
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC_SUBDIR = Path("server") / "spacetimedb" / "src"
EXCEPTIONS_PATH = REPO / "sdk" / "python" / "tests" / "data" / "schema_history_transient_exceptions.json"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def src_commits(repo: Path, cap: int | None) -> list[str]:
    """All commits touching server/spacetimedb/src, oldest -> newest."""
    out = _git(repo, "log", "--reverse", "--format=%H", "--", str(SRC_SUBDIR))
    commits = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if cap is not None and cap > 0:
        commits = commits[-cap:]
    return commits


def is_shallow(repo: Path) -> bool:
    return _git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"


def extract_src(repo: Path, sha: str, dest: Path) -> None:
    """Materialize server/spacetimedb/src at `sha` into `dest` (.rs only)."""
    proc = subprocess.run(
        ["git", "archive", sha, str(SRC_SUBDIR)],
        cwd=repo,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git archive {sha} failed: {proc.stderr.decode(errors='replace')[:300]}")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:*") as tf:
        for member in tf.getmembers():
            if member.isfile() and member.name.endswith(".rs"):
                data = tf.extractfile(member)
                if data is None:
                    continue
                (dest / Path(member.name).name).write_bytes(data.read())


# ---------------------------------------------------------------------------
# Structured violations (same contract as schema_policy_lib.find_violations,
# but as tuples so the transient-exception allowlist can match precisely).
# ---------------------------------------------------------------------------


def structured_violations(
    prev: dict[str, dict[str, str]],
    cur: dict[str, dict[str, str]],
    is_allowed_transition,
) -> list[tuple[str, str, str | None, str | None, str | None]]:
    """Return (kind, table, field, old_type, new_type) tuples.

    kind in {"table_removed", "field_removed", "type_changed"}.
    """
    viols: list[tuple[str, str, str | None, str | None, str | None]] = []
    for table, fields in sorted(prev.items()):
        if table not in cur:
            viols.append(("table_removed", table, None, None, None))
            continue
        for field, old in sorted(fields.items()):
            if field not in cur[table]:
                viols.append(("field_removed", table, field, old, None))
                continue
            new = cur[table][field]
            if not is_allowed_transition(old, new):
                viols.append(("type_changed", table, field, old, new))
    return viols


def format_violation(kind: str, table: str, field: str | None,
                     old: str | None, new: str | None) -> str:
    if kind == "table_removed":
        return f"TABLE REMOVED: `{table}` — policy forbids removing a table"
    if kind == "field_removed":
        return f"FIELD REMOVED/RENAMED: `{table}.{field}` ({old}) — add new, deprecate old, never remove"
    return f"TYPE CHANGED: `{table}.{field}` {old} -> {new} — only T -> Option<T> is allowed"


def load_exceptions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid exceptions JSON at {path}: {exc}") from exc
    excs = data.get("exceptions", []) if isinstance(data, dict) else []
    return [e for e in excs if isinstance(e, dict)]


def exception_matches(exc: dict, kind: str, table: str, field: str | None,
                      old: str | None, new: str | None) -> bool:
    if exc.get("kind", "type_changed") != kind:
        return False
    if exc.get("table") != table:
        return False
    if kind != "table_removed" and exc.get("field") != field:
        return False
    if kind == "type_changed":
        fwd = exc.get("from") == old and exc.get("to") == new
        rev = (
            exc.get("both_directions", False)
            and exc.get("from") == new and exc.get("to") == old
        )
        if not (fwd or rev):
            return False
    return True


def validate_exception_restored(exc: dict, head: dict[str, dict[str, str]]) -> str | None:
    """Return an error message if the recorded restoration did NOT happen in the
    current schema; None when the exception is still valid."""
    kind = exc.get("kind", "type_changed")
    table = exc.get("table")
    if table not in head:
        return f"table `{table}` is still absent from the current schema"
    if kind == "table_removed":
        return None  # presence checked above
    field = exc.get("field")
    cur_type = head[table].get(field)
    if cur_type is None:
        return f"field `{table}.{field}` is still absent from the current schema"
    restored = exc.get("restored_type")
    if kind == "field_removed":
        return None  # presence checked above
    if restored is not None and cur_type != restored:
        return f"field `{table}.{field}` is `{cur_type}` now, but the exception records restoration to `{restored}`"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=REPO, help="Repo to audit (default: this repo)")
    ap.add_argument(
        "--commits",
        type=int,
        default=None,
        help="Only audit the newest N commits touching the module source (fast CI smoke).",
    )
    ap.add_argument(
        "--exceptions",
        type=Path,
        default=None,
        help="Path to the transient-exceptions JSON (default: repo "
             "sdk/python/tests/data/schema_history_transient_exceptions.json).",
    )
    args = ap.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print(f"NOTE: {repo} is not a git worktree — history audit skipped "
              "(source-level baseline tests still enforce current state).")
        return 0
    if shutil.which("git") is None:
        print("NOTE: git not available — history audit skipped.")
        return 0

    sys.path.insert(0, str(repo / "sdk" / "python" / "tests"))
    try:
        import schema_policy_lib
    except ImportError as exc:  # pragma: no cover - infra failure path
        print(f"ERROR: cannot import schema_policy_lib from {repo}/sdk/python/tests: {exc}")
        return 1

    commits = src_commits(repo, args.commits)
    if len(commits) < 2:
        why = "shallow clone" if is_shallow(repo) else "fewer than 2 commits touching the module source"
        print(f"NOTE: {why} — no schema history to audit "
              "(source-level baseline tests still enforce current state).")
        return 0

    exc_path = (args.exceptions or (repo / "sdk" / "python" / "tests" / "data"
                                    / "schema_history_transient_exceptions.json")).resolve()
    try:
        exceptions = load_exceptions(exc_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    found: list[tuple[str, str, str | None, str | None, str | None]] = []
    pairs_checked = 0
    commits_skipped = 0
    prev_tables: dict[str, dict[str, str]] | None = None
    head_tables: dict[str, dict[str, str]] | None = None

    for sha in commits:
        with tempfile.TemporaryDirectory(prefix="schema-hist-") as td:
            try:
                extract_src(repo, sha, Path(td))
            except RuntimeError as exc:
                print(f"WARNING: could not extract source at {sha[:8]} — skipping: {exc}")
                commits_skipped += 1
                continue
            try:
                cur_tables = schema_policy_lib.parse_table_structs(Path(td))
            except Exception as exc:  # intermediate commits may be mid-refactor
                print(f"WARNING: unparseable table structs at {sha[:8]} — skipping "
                      f"(no comparison anchor): {exc}")
                commits_skipped += 1
                continue
        if prev_tables is not None:
            pairs_checked += 1
            found.extend(
                structured_violations(prev_tables, cur_tables,
                                      schema_policy_lib.is_allowed_transition)
            )
        prev_tables = cur_tables
        head_tables = cur_tables

    if head_tables is None:
        print("ERROR: no commit could be parsed — cannot validate transient exceptions "
              "against the current schema.")
        return 1

    # Deduplicate (same transition may appear across several pairs).
    seen: set[tuple] = set()
    uniq = []
    for v in found:
        key = tuple(v)
        if key not in seen:
            seen.add(key)
            uniq.append(v)

    # Match exceptions against detected transitions; validate restorations.
    used: set[int] = set()
    problems: list[str] = []
    for idx, exc in enumerate(exceptions):
        matched = [v for v in uniq if exception_matches(exc, *v)]
        if not matched:
            problems.append(
                f"Stale transient exception '{exc.get('id', '<no id>')}': no detected "
                f"transition matches {exc.get('kind', 'type_changed')} "
                f"{exc.get('table')}.{exc.get('field', '')} "
                f"{exc.get('from', '?')} -> {exc.get('to', '?')}. Remove or fix the entry."
            )
            continue
        err = validate_exception_restored(exc, head_tables)
        if err is not None:
            problems.append(
                f"Invalid transient exception '{exc.get('id', '<no id>')}': {err}. "
                "The breaking state is NOT restored — this exception cannot hide it."
            )
            continue
        used.add(idx)

    remaining = [v for i, v in enumerate(uniq) if not any(
        exception_matches(exc, *v) for j, exc in enumerate(exceptions) if j in used
    )]

    for idx in used:
        exc = exceptions[idx]
        print(f"KNOWN TRANSIENT (documented, corrected): {exc.get('id')} — "
              f"{exc.get('why', '').split('.')[0]}.")

    if problems:
        print(f"SCHEMA HISTORY EXCEPTION PROBLEMS ({len(problems)}):")
        for p in problems:
            print("  - " + p)
        print("\nTransient exceptions must match a REAL historical transition AND be "
              "restored in the current schema. Fix the exceptions file — do not "
              "paper over live violations.")
        return 1

    if remaining:
        print(f"SCHEMA HISTORY VIOLATIONS: {len(remaining)} breaking (non-additive) "
              f"transition(s) across {pairs_checked} commit pairs:")
        for kind, table, field, old, new in remaining:
            print(f"  - {format_violation(kind, table, field, old, new)}")
        print("\nPolicy (SCHEMA_EVOLUTION_POLICY.md 'Non-Additive Changes (Breaking)'): "
              "rename/type-change/remove are FORBIDDEN — schema is append-only. "
              "The struct is the source of truth and it only grows. Fix the code "
              "to restore the old field/type; history audits have no --force-breaking.")
        return 1

    print(f"SCHEMA HISTORY AUDIT OK: {len(commits)} commits, {pairs_checked} "
          f"consecutive-pair transition(s) checked, {len(used)} documented "
          f"transient exception(s) validated"
          + (f", {commits_skipped} skipped (unparseable/infrastructure)" if commits_skipped else "")
          + " — schema has only grown (append-only, T -> Option<T> allowed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
