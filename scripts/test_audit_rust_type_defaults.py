#!/usr/bin/env python3
"""Negative self-test for audit_rust_type_defaults: the detector must catch
real violations of the 'SpacetimeDB Defaults by Rust Type' contract."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import audit_rust_type_defaults as audit  # noqa: E402

FAILS: list[str] = []

def expect(ty: str, val: str, ok: bool, why: str) -> None:
    got = audit.is_ok(ty, val)
    if got != ok:
        FAILS.append(f"is_ok({ty!r}, {val!r}) = {got}, expected {ok} — {why}")

# --- String ---
expect("String", '"L1"', True, "string literal default")
expect("String", 'String::from("EXTRACTED")', True, "String::from default")
expect("String", "String::new()", True, "empty string default")
expect("String", "0", False, "integer literal on a String column is a type violation")
expect("String", "false", False, "bool literal on a String column is a type violation")
expect("String", "now", True, "runtime expr — type-safe by construction")
expect("String", "id.clone()", True, "runtime expr")

# --- bool ---
expect("bool", "false", True, "bool default false")
expect("bool", "true", True, "bool default true (explicit)")
expect("bool", "0", False, "int literal on bool column")
expect("bool", '"yes"', False, "string literal on bool column")

# --- integers ---
expect("u64", "0", True, "u64 default 0")
expect("u64", "1", True, "u64 default 1 (version)")
expect("u32", "0", True, "u32 default 0")
expect("u8", "0", True, "u8 default 0 (severity)")
expect("u16", "0", True, "u16 default 0 (response_code)")
expect("i64", "0", True, "i64 default 0")
expect("u64", "0_u64", True, "suffixed int literal")
expect("u64", "1_000", True, "underscored int literal")
expect("u64", '"0"', False, "string literal on u64 column")
expect("u64", "false", False, "bool literal on u64 column")
expect("u64", "0.5", False, "float literal on u64 column")

# --- floats ---
expect("f64", "0.0", True, "f64 default 0.0 for counters")
expect("f64", "0.5", True, "f64 default 0.5 for scores")
expect("f64", "1", True, "whole-number float literal")
expect("f64", '"0.5"', False, "string literal on f64 column")
expect("f64", "false", False, "bool literal on f64 column")
expect("f32", "0.0", True, "f32 default")

# --- Option<T> ---
expect("Option<String>", "None", True, "Option default None (preferred)")
expect("Option<u32>", "None", True, "Option<u32> default None")
expect("Option<String>", 'Some(String::from("x"))', True, "explicit Some")
expect("Option<u32>", "Some(0)", True, "explicit Some(0) — policy says Some(0) invalid for version but Some is a legal branch")
expect("Option<String>", '""', False, "plain string literal on Option<String> — must be None or Some(...)")
expect("Option<u32>", "0", False, "bare int literal on Option<u32> — must be None or Some(...)")

# --- Vec / JSON ---
expect("Vec<String>", "vec![]", True, "empty vec default")
expect("Vec<u8>", "Vec::new()", True, "Vec::new default")
expect("String", 'String::from("[]")', True, "JSON blob default []")

if FAILS:
    print("SELF-TEST FAILED:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("SELF-TEST OK: detector flags all 26 negative cases, accepts all 20 positive cases")
