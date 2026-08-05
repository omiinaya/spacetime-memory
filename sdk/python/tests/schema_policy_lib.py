"""Shared parser + append-only validation for SCHEMA_EVOLUTION_POLICY.md.

Single source of truth used by BOTH:
  * ``tests/test_schema_evolution_policy.py``  (CI enforcement)
  * ``scripts/update_schema_baseline.py``      (baseline regeneration)

The policy's "Non-Additive Changes (Breaking)" table is codified here:

    | Rename field              | Forbidden (add new, deprecate old, never remove) |
    | Change type               | Forbidden (add new field with new type)          |
    | Remove field              | Forbidden (mark deprecated, leave in struct)     |
    | Required -> optional      | Allowed ONLY as ``T`` -> ``Option<T>``           |
    | Optional -> required      | Forbidden (impossible without migration)         |

The committed baseline (``data/schema_baseline.json``) is a LOWER BOUND on the
schema: the test asserts ``current schema ⊇ baseline`` with the single allowed
transition above. New tables/fields never require a baseline update; the
baseline only grows when schema legitimately evolves and is refreshed with
``scripts/update_schema_baseline.py`` (which refuses to shrink or re-type
existing entries unless ``--force-breaking`` is passed).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "server" / "spacetimedb" / "src"
BASELINE_PATH = REPO_ROOT / "sdk" / "python" / "tests" / "data" / "schema_baseline.json"

# Rust types that wrap another type in Option<...>
_OPTION_RE = re.compile(r"^Option<(.+)>$")


def parse_table_structs(src_dir: Path = SRC_DIR) -> dict[str, dict[str, str]]:
    """Parse every ``#[table(...)]`` struct in ``server/spacetimedb/src``.

    Returns ``{struct_name: {field_name: rust_type}}`` for all table structs.

    Robust to:
      * nested parens in table attrs (``index(accessor = x, btree(columns = [...]))``)
      * doc comments that mention ``#[table(`` (skipped — line starts with ``//``)
      * derives/docs between the attr and the struct
      * multi-line attrs
      * attribute lines (``#[primary_key]``, ``#[index(btree)]``) before fields
      * trailing ``//`` comments after the comma on field lines
    """
    tables: dict[str, dict[str, str]] = {}
    for f in sorted(src_dir.glob("*.rs")):
        src = f.read_text(encoding="utf-8")
        lines = src.splitlines()
        offsets: list[int] = []
        acc = 0
        for ln in src.splitlines(keepends=True):
            offsets.append(acc)
            acc += len(ln)

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("#[table("):
                continue
            # A '#'[table(' inside a doc/line comment is not a table decl.
            if stripped.startswith("//") or stripped.startswith("///") or stripped.startswith("*"):
                continue

            line_off = offsets[i]
            j = line.index("#[table(")
            # Balanced-paren capture of the attr (may span lines).
            depth = 0
            buf = src[line_off + j:]
            for ch in buf:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            k = i
            while depth > 0 and k + 1 < len(lines):
                k += 1
                for ch in lines[k]:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1

            # struct follows within a few lines (derives/docs between).
            window = "\n".join(lines[i : k + 8])
            sm = re.search(r"struct\s+(\w+)", window)
            if not sm:
                raise ValueError(
                    f"#[table( attr with no struct after it: {f.name}:{i + 1} {line.strip()[:60]}"
                )
            name = sm.group(1)

            si = src.find(f"struct {name}", line_off)
            brace = src.find("{", si)
            depth = 1
            p = brace + 1
            while depth > 0 and p < len(src):
                if src[p] == "{":
                    depth += 1
                elif src[p] == "}":
                    depth -= 1
                p += 1
            body = src[brace + 1 : p - 1]

            fields: dict[str, str] = {}
            for fm in re.finditer(r"^\s*pub\s+(\w+)\s*:\s*([^,]+),", body, re.M):
                fields[fm.group(1)] = re.sub(r"\s+", " ", fm.group(2)).strip()

            if name in tables:
                raise ValueError(f"Duplicate struct name {name} (in {f.name})")
            tables[name] = fields
    return tables


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict[str, str]]:
    """Load the committed schema baseline JSON."""
    if not path.exists():
        raise FileNotFoundError(
            f"Schema baseline not found at {path}. Generate it with "
            "`python scripts/update_schema_baseline.py`."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: dict(v) for k, v in data.items()}


def is_allowed_transition(old_type: str, new_type: str) -> bool:
    """Policy table for Non-Additive Changes.

    Only ONE non-identical transition is permitted: required -> optional,
    i.e. ``T`` -> ``Option<T>``. Everything else is forbidden.
    """
    if old_type == new_type:
        return True
    m = _OPTION_RE.match(new_type)
    return bool(m) and m.group(1) == old_type


def find_violations(baseline: dict[str, dict[str, str]], current: dict[str, dict[str, str]]) -> list[str]:
    """Return human-readable policy violations of ``current`` vs ``baseline``.

    Empty list == schema is append-only-legal (new tables/fields allowed).
    """
    violations: list[str] = []
    for table, fields in sorted(baseline.items()):
        if table not in current:
            violations.append(
                f"TABLE REMOVED: `{table}` — policy forbids removing a table "
                "(schema is append-only; keep the struct, deprecate in SDK)"
            )
            continue
        cur_fields = current[table]
        for field, old_type in sorted(fields.items()):
            if field not in cur_fields:
                violations.append(
                    f"FIELD REMOVED/RENAMED: `{table}.{field}` ({old_type}) — policy "
                    "forbids removing or renaming a field (add new, deprecate old, "
                    "never remove from struct)"
                )
                continue
            new_type = cur_fields[field]
            if not is_allowed_transition(old_type, new_type):
                violations.append(
                    f"TYPE CHANGED: `{table}.{field}` {old_type} -> {new_type} — "
                    "policy forbids type changes (add a new field with the new type). "
                    "Only T -> Option<T> (required->optional) is allowed."
                )
    return violations


def dump_baseline(tables: dict[str, dict[str, str]]) -> str:
    """Canonical JSON serialization (sorted keys, indent 2, trailing newline)."""
    return json.dumps(
        {n: dict(sorted(fs.items())) for n, fs in sorted(tables.items())},
        indent=2,
        sort_keys=True,
    ) + "\n"
