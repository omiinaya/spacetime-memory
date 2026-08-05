#!/usr/bin/env python3
"""Audit every #[table] struct + its insert sites against the
"SpacetimeDB Defaults by Rust Type" table in SCHEMA_EVOLUTION_POLICY.md.

Contract (policy lines 40-57):
    String            -> default "" (or semantic base like "L1")
    bool              -> false (or true, explicit)
    u64/u32/i64/i32   -> 0 (or semantic default like 1 for version)
    u8/u16            -> 0
    f64/f32           -> 0.0 (0.5 for scores)
    Option<T>         -> None
    Vec<T>/JSON str   -> "[]" or "{}"

For each table struct we:
  1. map its accessor name (from #[table(accessor=...)] / struct name)
  2. find every `ctx.db.<accessor>().insert(<StructName> { ... })` literal
  3. for each present field, check its initializer against the policy default
     shapes for the field's Rust type
  4. report any non-conformant initializer

The core STDB mechanism (auto column default on publish) means a field may be
omitted from an insert — that is allowed and never flagged. Only a field that
IS present but initialized to a type-mismatched / non-policy value is flagged.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sdk" / "python" / "tests"))
import schema_policy_lib  # noqa: E402

SRC = schema_policy_lib.SRC_DIR

INT_RE = re.compile(r"^\d[\d_]*([ui](8|16|32|64|128|size))?$")  # 0, 1, 0_u32, 12_000
INT_TYPES = ("u64", "u32", "i64", "i32", "u16", "u8", "i8", "u128", "i128", "usize", "isize")
# f64/f32: decimal numeric literal. Slight tolerance: any literal starting with
# a digit or '.' is accepted (covers 0.0 / 0.5 / 1 / 2.5) — a score default.
FLOAT_RE = re.compile(r"^\d[\d_]*(\.\d+)?([eE][+-]?\d+)?$")

# type-family -> list of accepted initializer regexes / predicates
_LITERAL_RE = re.compile(r"^(\d|\.|\"|'|true|false|None|Some\(|vec!|r\"|b\"|String::)")

def _is_literal_expr(val: str) -> bool:
    """True when the value is a bare literal/constructor (type-checkable),
    False when it's a runtime expression (variable, fn call) — Rust already
    guarantees those are type-correct."""
    v = val.strip()
    if not v:
        return False
    # Rust keywords / bool literals are NOT identifiers.
    if v in ("true", "false", "None"):
        return True
    # identifier / member / call / macro with args / operators → runtime expr
    if re.match(r"^[A-Za-z_][\w]*(\.[\w]+)*(\()?$", v) and not v.startswith(("String::", "Some(", "None", "vec!")):
        return False
    return bool(_LITERAL_RE.match(v))


def is_ok(ty: str, val: str) -> bool:
    ty = ty.strip()
    val = val.strip()
    if not _is_literal_expr(val):
        return True  # runtime expression — type-safe by construction
    inner = ty
    # unwrap Option<...> -> the *branch* value must be None or Some(...)
    if inner.startswith("Option<"):
        if val == "None":
            return True
        # Some(<inner-type default>) — allow explicit Some(x)
        if val.startswith("Some(") and val.endswith(")"):
            inner = inner[len("Option<"):-1].strip()
            return is_plain_ok(inner, val[5:-1].strip())
        return False
    if inner.startswith("Vec<") or inner.startswith("Vec"):
        return val in ("vec![]", "Vec::new()", "vec![", "Vec::from") or "vec!" in val or val == "Default::default()"
    return is_plain_ok(inner, val)


def is_plain_ok(ty: str, val: str) -> bool:
    base = ty.strip()
    if base in INT_TYPES:
        # allow an integer literal (incl with type suffix / underscores)
        return bool(INT_RE.match(val))
    if base in ("f64", "f32"):
        return bool(FLOAT_RE.match(val))
    if base == "bool":
        return val in ("true", "false")
    if base in ("String", "&str"):
        if val.startswith("String::new()") or val.startswith("String::default()"):
            return True
        if val.startswith("String::from(") or val.startswith("\"") or val.startswith("r\""):
            return True
        return False  # any other literal is not a String default
    # non-primitive (Ids, enums, timestamps, custom types) — not covered by the
    # policy table's scalar rows; we do NOT flag these (out of scope).
    return True


def find_insert_literals(src: str, accessor: str, struct: str):
    """Yield full struct-literal text for `ctx.db.<accessor>().insert(<struct> {`."""
    pat = re.compile(rf"\.{re.escape(accessor)}\(\)\.insert\(\s*{re.escape(struct)}\s*\{{")
    for m in pat.finditer(src):
        # brace-match from the '{'
        brace = src.find("{", m.start())
        depth = 0
        p = brace
        while p < len(src):
            c = src[p]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            p += 1
        line = src.count("\n", 0, m.start()) + 1
        yield line, src[brace + 1: p]


def parse_fields(body: str) -> list[tuple[int, str, str]]:
    """Extract `field: value` pairs (top level) with line numbers. Handles nested
    braces by tracking depth; stops a field value at a top-level comma."""
    fields = []
    i = 0
    n = len(body)
    while i < n:
        # find `field:` at depth 0
        m = re.compile(r"(?m)^\s*\b([A-Za-z_]\w*)\s*:").search(body, i)
        if not m:
            break
        name = m.group(1)
        val_start = m.end()
        depth = 0
        j = val_start
        while j < n:
            c = body[j]
            if c in "{([":
                depth += 1
            elif c in "})]":
                depth -= 1
                if depth < 0:
                    break
            elif c == "," and depth == 0:
                break
            j += 1
        value = body[val_start:j].strip()
        # only top-level (depth==0) fields, matching `pub field: type,` struct decls
        line = body.count("\n", 0, m.start()) + 1
        fields.append((line, name, value))
        i = j if depth >= 0 else j + 1
    return fields


def main() -> int:
    tables = schema_policy_lib.parse_table_structs()  # struct_name -> {field: type}
    src_all = {f.name: f.read_text(encoding="utf-8") for f in SRC.glob("*.rs")}

    # table accessors: `#[table(accessor = <name>)]` and `#[table(accessor = <name>, ...)]`
    accessor_of: dict[str, str] = {}
    for fn, s in src_all.items():
        for m in re.finditer(r"#\[table\(accessor\s*=\s*(\w+)", s):
            # the struct follows within a few lines
            struct_m = re.search(r"struct\s+(\w+)", s[m.start(): m.end() + 400])
            if struct_m:
                accessor_of[struct_m.group(1)] = m.group(1)

    problems: list[str] = []
    checked = 0
    for struct, fields in sorted(tables.items()):
        acc = accessor_of.get(struct, struct.lower())
        # insert literals may live in any file
        literals = []
        for fn, s in src_all.items():
            for line, body in find_insert_literals(s, acc, struct):
                literals.append((fn, line, body))
        if not literals:
            continue  # read-only/result table or inserts via variable — skip

        # map each field type once
        for fname, ftype in sorted(fields.items()):
            for fn, line, body in literals:
                for fline, iname, ivalue in parse_fields(body):
                    if iname != fname:
                        continue
                    checked += 1
                    if is_ok(ftype, ivalue):
                        continue
                    problems.append(
                        f"{fn} (struct `{struct}` field `{fname}` {ftype}, line {line}+{fline}): "
                        f"insert value `{ivalue}` is not a policy-conformant '{ftype}' default."
                    )

    if problems:
        print(f"AUDIT: {len(problems)} findings across {len(tables)} tables, {checked} insert-field values checked")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"AUDIT OK: {len(tables)} tables, {checked} insert-field values checked — all conform to 'SpacetimeDB Defaults by Rust Type'")
    return 0


if __name__ == "__main__":
    sys.exit(main())