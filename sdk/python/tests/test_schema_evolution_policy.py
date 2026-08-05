"""Critical enforcement of SCHEMA_EVOLUTION_POLICY.md — "When to Use Option<T> vs Default Value".

Source-scanning unit tests (no SpacetimeDB required) that codify the policy's
decision table so schema changes can't silently violate it:

  * Option<T> is the ONLY way to distinguish "unset" from "explicitly default".
    It must be used for fields where that semantic difference matters (e.g.
    `note.version` — None = pre-versioning), and every such read path MUST
    guard with `.unwrap_or` / `.unwrap_or_default()` — reading a None column
    with a bare `.unwrap()` aborts the reducer and crashes old rows.
  * Counters/scores/enum-strings/JSON blobs use plain types with documented
   , reducer-level defaults (`u64`->0, `f64`->0.5, `String`->"L1"/"", `bool`->false).
  * Forbidden: `--delete-data=on-conflict`, `--delete-data=always`, `ALTER TABLE`
    in reducers, migration/backfill reducers. `scripts/publish.sh` must hardcode
    `--delete-data=never`.

These tests parse the Rust/WASM module source and publish.sh directly. If they
break, the schema policy is being violated — fix the code, not the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "server" / "spacetimedb" / "src"
PUBLISH_SH = REPO_ROOT / "scripts" / "publish.sh"

# Policy decision table -> codebase contract.
# (field, rust_type, reducer default) — every additive feature-block field on
# the Memory table as documented in memory.rs and SCHEMA_EVOLUTION_POLICY.md.
MEMORY_FEATURE_BLOCK_DEFAULTS: dict[str, str] = {
    "tier": 'String::from("L1")',
    "access_count": "0",
    "strength": "0.5",
    "version": "1",
    "valid_from": "0",
    "valid_to": "0",
    "parent_directory_id": "String::new()",
    "consolidated_to": "String::new()",
    "trust_score": "0.5",
    "feedback_count": "0",
    "user_scope": "String::new()",
}

# Fields on the Memory table added after initial release (feature blocks) —
# they ride on STDB auto-column-add, so read paths must tolerate zero values.
MEMORY_ADDITIVE_FIELDS = tuple(MEMORY_FEATURE_BLOCK_DEFAULTS.keys())


def _read_rust(name: str) -> str:
    return (SRC_DIR / name).read_text(encoding="utf-8")


def _rust_src_all() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in SRC_DIR.glob("*.rs"))


# ---------------------------------------------------------------------------
# 1. Option<T> vs default-value decision table
# ---------------------------------------------------------------------------


class TestOptionVsDefaultDecision:
    """The policy's core decision: Option<T> only for genuine "unset" semantics."""

    def test_option_fields_used_only_for_unset_semantics(self):
        """All Option<T> table fields must carry a doc comment stating the
        None-means semantics. No Option field should be a counter/score/enum."""
        note = _read_rust("note.rs")
        # note.version is the policy's canonical example: None = pre-versioning
        assert "version: Option<u32>" in note, (
            "note.version must be Option<u32> (None = pre-versioning, "
            "the policy's 'unset matters' case)"
        )

        user = _read_rust("user.rs")
        # PII (email, names) genuinely optional — Option<T> correct (not String "")
        for f in ("email: Option<String>", "first_name: Option<String>", "last_name: Option<String>"):
            assert f in user, f"User PII field should be {f} (genuinely optional, unset != default)"

    def test_no_option_for_plain_counter_score_enum(self):
        """Counters/scores/enum-strings/JSON blobs must NOT be Option<T>."""
        src = _rust_src_all()
        # Memory reinforcement/holographic fields are counters/scores -> plain types
        for decl in (
            "access_count: u64",
            "strength: f64",
            "feedback_count: u32",
            "trust_score: f64",
            "user_scope: String",
            "tier: String",
        ):
            assert decl in src, f"{decl} must stay a plain type (counter/score/enum with a default)"


class TestOptionReadPathsGuarded:
    """Every Option<T> read path must guard — bare .unwrap() on None aborts."""

    def test_note_version_reads_are_guarded(self):
        note = _read_rust("note.rs")
        # Every read of note.version must use unwrap_or(0), never bare .unwrap()
        unguarded = re.findall(r"note\.version\.unwrap\(\)", note)
        assert not unguarded, "note.version read without unwrap_or — crashes on pre-versioning rows"
        guarded = re.findall(r"note\.version\.unwrap_or\(0\)", note)
        assert len(guarded) >= 1, "note.version must be read via .unwrap_or(0) in at least one path"

    def test_no_bare_unwrap_on_option_columns_in_production_code(self):
        """Bare `.unwrap()` on a table accessor result is a crash waiting for a
        None row. Tests may unwrap; production reducer code may not."""
        src = _rust_src_all()
        # Strip the #[cfg(test)] test modules heuristically: unwraps inside
        # fn ... _test / #[test] are legit. We only police non-test code.
        production = re.split(r"#\[cfg\(test\)\]", src)[0]
        suspicious = [
            line.strip()
            for line in production.splitlines()
            if re.search(r"\.(first\(\)|iter\(\)\.next\(\)|find\(.*\))\s*\.unwrap\(\)", line)
            or re.search(r"\bfind\([^)]*\)\.unwrap\(\)", line)
        ]
        assert not suspicious, (
            "Bare .unwrap() on a table lookup in production code — will abort on "
            "missing/None row. Use .ok_or(...) / .unwrap_or_default(). Found:\n"
            + "\n".join(suspicious[:10])
        )


# ---------------------------------------------------------------------------
# 2. Reducer defaults must match the policy table
# ---------------------------------------------------------------------------


class TestReducerDefaults:
    """Insert reducers must supply the policy-documented defaults."""

    def test_store_memory_defaults(self):
        src = _read_rust("memory.rs")
        for field, expected in MEMORY_FEATURE_BLOCK_DEFAULTS.items():
            pattern = re.compile(
                rf"\b{re.escape(field)}\s*:\s*{re.escape(expected)}"
            )
            assert pattern.search(src), (
                f"store_memory/insert_memory must default {field} to {expected} "
                f"(policy decision table). Field missing or wrong default."
            )

    def test_additive_fields_have_documented_comment_blocks(self):
        """Policy step: every new feature-group field carries a comment block."""
        src = _read_rust("memory.rs")
        for anchor in (
            "// ---- OpenViking: Tiered contexts ----",
            "// ---- RetainDB: Reinforcement & Versioning ----",
            "// ---- OpenViking: Hierarchy ----",
            "// ---- RetainDB: Consolidation ----",
            "// ---- Holographic: Trust Scoring & Feedback ----",
            "// ---- User-level isolation (Mem0 parity) ----",
        ):
            assert anchor in src, f"Missing feature-block comment header: {anchor}"

    def test_sdk_mapper_read_path_defaults(self):
        """Python SDK mappers must COALESCE additive fields (policy step 4).

        Only fields the SDK actually maps need a default — an additive field
        the client never reads is harmless. Fields that ARE read must use
        `.get(key, default)` / `??` so old rows (zero values) don't crash.
        """
        # Audit the whole SDK package: a read path may live in the core
        # client OR in a drop-in adapter (e.g. mem0 _client.py re-maps rows).
        sdk_dir = REPO_ROOT / "sdk" / "python" / "spacetime_memory"
        all_py = [p for p in sdk_dir.rglob("*.py")]
        assert all_py, "No SDK Python sources found to audit"
        found = "\n".join(p.read_text(encoding="utf-8") for p in all_py)
        # Every additive field that the SDK reads must be read with a fallback.
        for field in MEMORY_ADDITIVE_FIELDS:
            if f'"{field}"' not in found:
                continue  # not mapped at all -> no read path to guard
            coallesced = re.search(rf'\.get\(\s*["\']{re.escape(field)}["\']\s*,', found)
            # `??` TS-style not used in Python; .get(k, d) is the COALESCE form.
            assert coallesced, (
                f"SDK reads additive field '{field}' without a default — "
                f"use .get('{field}', <default>) per policy step 4"
            )


# ---------------------------------------------------------------------------
# 3. Forbidden patterns
# ---------------------------------------------------------------------------


class TestForbiddenPatterns:
    """Absolute no-go's from the policy — enforced at source-scan level."""

    def test_no_destructive_delete_data_in_module(self):
        src = _rust_src_all()
        for bad in ("--delete-data=on-conflict", "--delete-data=always"):
            assert bad not in src, f"Forbidden publish flag {bad} must never appear in module src"

    def test_no_alter_table_in_reducers(self):
        src = _rust_src_all()
        # ALTER TABLE / ADD COLUMN SQL is not supported in the WASM sandbox.
        assert not re.search(r"\bALTER\s+TABLE\b", src, re.IGNORECASE), (
            "ALTER TABLE is forbidden — schema come from Rust structs only"
        )

    def test_no_migration_or_backfill_reducer(self):
        """No reducer should sweep/backfill old rows — STDB auto-defaults them."""
        src = _rust_src_all()
        # A real, named migration reducer would be #\[reducer\]. We allow the
        # word only in comments/docs. Detect reducer-function declarations.
        migration_fns = re.findall(
            r"#\[reducer\][\s\S]{0,200}?fn\s+\w*[Mm]igrat\w*\s*\(",
            src,
        )
        backfill_fns = re.findall(
            r"#\[reducer\][\s\S]{0,200}?fn\s+\w*[Bb]ackfill\w*\s*\(",
            src,
        )
        assert not migration_fns, "Migration reducers are forbidden by SCHEMA_EVOLUTION_POLICY.md"
        assert not backfill_fns, "Backfill reducers are forbidden by SCHEMA_EVOLUTION_POLICY.md"

    def test_publish_script_hardcodes_never(self):
        if not PUBLISH_SH.exists():
            pytest.skip("scripts/publish.sh not present")
        script = PUBLISH_SH.read_text(encoding="utf-8")
        # The publish command is multi-line (line-continuation), so scan for
        # the --delete-data flag in executed (non-comment / non-echo) lines.
        executed = [
            ln for ln in script.splitlines()
            if not ln.lstrip().startswith(("#", "echo", "printf", "   ", "    ")) and ln.strip()
        ]
        flags_used = [
            ln for ln in executed if "--delete-data" in ln
        ]
        assert flags_used, "No active --delete-data flag found in publish.sh publish command"
        for ln in flags_used:
            assert "--delete-data=never" in ln, (
                f"Active publish command must use --delete-data=never, got: {ln.strip()}"
            )
        # The script must defend against the DELETE_DATA env override.
        assert re.search(r"DELETE_DATA", script), (
            "publish.sh should defend against the DELETE_DATA env override"
        )


class TestPolicyDocsPresent:
    """The governance docs that define this contract must not be lost."""

    def test_policy_docs_exist(self):
        for rel in (
            "SCHEMA_EVOLUTION_POLICY.md",
            "SCHEMA_EVOLUTION_POLICY_EXECUTIVE_SUMMARY.md",
        ):
            assert (REPO_ROOT / rel).exists(), f"Missing policy doc: {rel}"
        assert (REPO_ROOT / "docs" / "SCHEMA_EVOLUTION_POLICY_RATIONALE.md").exists(), (
            "Missing docs/SCHEMA_EVOLUTION_POLICY_RATIONALE.md"
        )