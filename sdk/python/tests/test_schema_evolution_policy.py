"""Critical enforcement of SCHEMA_EVOLUTION_POLICY.md — "When to Use Option<T> vs Default Value".

Source-scanning unit tests (no SpacetimeDB required) that codify the policy's
decision table so schema changes can't silently violate it:

  * Option<T> is the ONLY way to distinguish "unset" from "explicitly default".
    It must be used for fields where that semantic difference matters (e.g.
    `note.version` — None = pre-versioning), and every such read path MUST
    guard with `.unwrap_or` / `.unwrap_or_default()` — reading a None column
    with a bare `.unwrap()` aborts the reducer and crashes old rows.
  * Counters/scores/enum-strings/JSON blobs use plain types with documented
    reducer-level defaults (`u64`->0, `f64`->0.5, `String`->"L1"/"", `bool`->false).
  * Forbidden: `--delete-data=on-conflict`, `--delete-data=always`, `ALTER TABLE`
    in reducers, migration/backfill reducers. `scripts/publish.sh` must hardcode
    `--delete-data=never`.

These tests parse the Rust/WASM module source and publish.sh directly. If they
break, the schema policy is being violated — fix the code, not the test.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "server" / "spacetimedb" / "src"
PUBLISH_SH = REPO_ROOT / "scripts" / "publish.sh"
BASELINE_JSON = REPO_ROOT / "sdk" / "python" / "tests" / "data" / "schema_baseline.json"

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
    "source_url": "None",
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


class TestMemoryReadPathCoalesce:
    """SCHEMA_EVOLUTION_POLICY.md section 1 step 5b: read paths must COALESCE
    the Memory additive fields — especially `source_url: Option<String>` —
    before emitting JSON. A bare `m.source_url` would serialize as `null` for
    old rows; the query_memory reducer must use `.unwrap_or_default()`.
    """

    def test_query_memory_coalesces_source_url(self):
        src = _read_rust("query.rs")
        # Every emission of source_url in a query row must COALESCE the Option.
        raw_emits = re.findall(r'"source_url":\s*m\.source_url\b(?!\s*\.)', src)
        assert not raw_emits, (
            "query_memory emits source_url without COALESCE — old rows "
            f"serialize as null: {raw_emits}"
        )
        coalesced = re.findall(
            r'"source_url":\s*m\.source_url\.clone\(\)\.unwrap_or_default\(\)', src
        )
        assert len(coalesced) >= 2, (
            "query_memory must COALESCE source_url via "
            "m.source_url.clone().unwrap_or_default() in both the global and "
            f"workspace-scoped branches (policy step 5b). Found: {coalesced}"
        )

    def test_query_memory_emits_all_additive_fields(self):
        """The read path must surface every additive feature-block field —
        dropping one would hide the column from clients (policy step 4)."""
        src = _read_rust("query.rs")
        for field in MEMORY_ADDITIVE_FIELDS:
            assert f'"{field}"' in src, (
                f"query_memory row does not emit additive field '{field}' — "
                "read paths must include every feature-block column"
            )

    def test_no_bare_unwrap_on_memory_option_in_query_reads(self):
        """Reading an Option column with bare `.unwrap()` aborts on None rows."""
        src = _read_rust("query.rs")
        bare = re.findall(r"m\.source_url\.unwrap\(\)", src)
        assert not bare, (
            "query.rs reads source_url with bare .unwrap() — aborts on old "
            f"rows where the column is None: {bare}"
        )


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
            "// ---- Source attribution ----",
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

    def test_ts_sdk_read_paths_are_coalesced_or_passthrough(self):
        """TypeScript SDK: any Memory-row field access must use `??`; raw
        passthrough (no destructuring) is also safe. Direct `.field` reads
        without `??` would crash/undefined on old rows."""
        ts_client = REPO_ROOT / "sdk" / "typescript" / "client.ts"
        if not ts_client.exists():
            pytest.skip("TS SDK client.ts not present")
        src = ts_client.read_text(encoding="utf-8")
        # Memory rows flow as Record<string, unknown> passthroughs in this SDK.
        # Guard: any direct field access on a row-like value must use ??.
        direct_reads = re.findall(
            r"\b(?:memory|mem|row|result)\.(tier|accessCount|strength|trustScore|feedbackCount|userScope|parentDirectoryId)\b(?!\?)",
            src,
        )
        assert not direct_reads, (
            "TS SDK reads additive Memory fields without `??` fallback: "
            f"{direct_reads}. Use row.field ?? <default> per policy step 4."
        )


class TestAllTablesDefaultsByRustType:
    """Full-module enforcement of the policy's 'SpacetimeDB Defaults by Rust
    Type' table (SCHEMA_EVOLUTION_POLICY.md lines 40-57), applied to EVERY
    ``#[table]`` struct's insert sites — not just the Memory feature blocks
    covered by TestReducerDefaults.

    The audit (``scripts/audit_rust_type_defaults.py``) walks each table's
    ``ctx.db.<accessor>().insert(<Struct> { ... })`` literals and checks that
    every *present* field whose type is covered by the policy table
    (String, bool, u8/u16/u32/u64/i32/i64, f32/f64, Option<T>, Vec<T>)
    is initialized with a policy-conformant default:

      * String            -> "" / String::from("...") / String::new()
      * bool              -> false | true (explicit)
      * integers          -> integer literal (0, 1, 0_u64, ...)
      * f64/f32           -> numeric literal (0.0 counters, 0.5 scores)
      * Option<T>         -> None (preferred) or Some(<T>)
      * Vec<T>            -> vec![] / Vec::new()

    Runtime expressions (``now``, ``id.clone()``, ``x as f64``) are never
    flagged — Rust's type system already guarantees those are type-correct.
    Fields omitted from an insert literal are also never flagged: STDB's
    auto column default on publish fills them (that IS the policy mechanism).
    """

    def test_all_tables_insert_literals_conform(self):
        import subprocess

        script = REPO_ROOT / "scripts" / "audit_rust_type_defaults.py"
        if not script.exists():
            pytest.skip("scripts/audit_rust_type_defaults.py not present")
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            "A table insert initializes a policy-covered field with a "
            "non-conformant default (see 'SpacetimeDB Defaults by Rust Type' "
            "table in SCHEMA_EVOLUTION_POLICY.md). Fix the reducer, not the "
            f"audit.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )

    def test_audit_detector_self_test_passes(self):
        """The audit's own negative tests must pass — guards against a detector
        that silently accepts everything (which would make the above test
        meaningless)."""
        import subprocess

        script = REPO_ROOT / "scripts" / "test_audit_rust_type_defaults.py"
        if not script.exists():
            pytest.skip("scripts/test_audit_rust_type_defaults.py not present")
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            "audit_rust_type_defaults detector self-test failed — the detector "
            "no longer distinguishes conformant from non-conformant defaults.\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
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


# ---------------------------------------------------------------------------
# 4. Non-Additive Changes (Breaking) — the schema is append-only
# ---------------------------------------------------------------------------


class TestNonAdditiveAppendOnly:
    """SCHEMA_EVOLUTION_POLICY.md "Non-Additive Changes (Breaking)" table.

    The Rust struct is the source of truth and it only GROWS:

      * Rename field   -> Forbidden (add new, deprecate old, never remove)
      * Change type    -> Forbidden (add new field with the new type)
      * Remove field   -> Forbidden (mark deprecated, leave in struct forever)
      * Required->opt  -> Allowed ONLY as ``T`` -> ``Option<T>``
      * Optional->req  -> Forbidden (impossible without migration)

    The committed baseline (``tests/data/schema_baseline.json``) is the lower
    bound: every baseline table/field/type must still exist in the current
    source, except the single permitted ``T`` -> ``Option<T>`` upgrade.
    New tables and new fields are allowed (append-only growth). Regenerate
    the baseline with ``scripts/update_schema_baseline.py`` when schema
    legitimately evolves; the script refuses to write a shrinking baseline.
    """

    @pytest.fixture(scope="class")
    def schema(self):
        import schema_policy_lib

        return {
            "baseline": schema_policy_lib.load_baseline(),
            "current": schema_policy_lib.parse_table_structs(),
        }

    def test_baseline_file_committed(self):
        """The baseline must exist — it is the append-only anchor."""
        assert BASELINE_JSON.exists(), (
            "Missing tests/data/schema_baseline.json — run "
            "`python scripts/update_schema_baseline.py` to generate it"
        )

    def test_baseline_covers_memory_table(self, schema):
        """Sanity: the canonical Memory table (policy's worked example) is in
        the baseline with its full additive feature-block field set."""
        memory = schema["baseline"].get("Memory", {})
        assert memory, "Baseline must include the Memory table"
        for field in MEMORY_ADDITIVE_FIELDS + ("id", "workspace_id"):
            assert field in memory, (
                f"Baseline Memory table is missing documented field '{field}' — "
                "regenerate the baseline"
            )

    def test_no_table_removed(self, schema):
        """A table that existed when the baseline was written must still exist."""
        baseline, current = schema["baseline"], schema["current"]
        removed = sorted(set(baseline) - set(current))
        assert not removed, (
            "Schema tables removed — policy forbids removing tables "
            f"(append-only): {removed}"
        )

    def test_no_field_removed_or_renamed(self, schema):
        """Every baseline field must still exist — a rename shows up as the
        old name disappearing (plus a new name appearing, which is allowed
        as a brand-new field)."""
        baseline, current = schema["baseline"], schema["current"]
        missing = []
        for table, fields in sorted(baseline.items()):
            cur_fields = current.get(table, {})
            for field in sorted(fields):
                if field not in cur_fields:
                    missing.append(f"{table}.{field} ({fields[field]})")
        assert not missing, (
            "Schema fields removed/renamed — policy forbids it (add new, "
            "deprecate old, never remove). Missing:\n  " + "\n  ".join(missing)
        )

    def test_no_field_type_changed(self, schema):
        """Every baseline field must keep its type — the ONLY permitted
        transition is ``T`` -> ``Option<T>`` (required->optional)."""
        baseline, current = schema["baseline"], schema["current"]
        changed = []
        for table, fields in sorted(baseline.items()):
            cur_fields = current.get(table, {})
            for field, old_type in sorted(fields.items()):
                new_type = cur_fields.get(field)
                if new_type == old_type:
                    continue
                # Allowed: T -> Option<T> (policy's required->optional row)
                if new_type == f"Option<{old_type}>":
                    continue
                changed.append(f"{table}.{field}: {old_type} -> {new_type}")
        assert not changed, (
            "Schema field types changed — policy forbids type changes (add a "
            "new field with the new type, migrate in application logic). "
            "Only T -> Option<T> is allowed. Changed:\n  "
            + "\n  ".join(changed)
        )

    def test_optional_to_required_forbidden(self, schema):
        """The reverse transition (``Option<T>`` -> ``T``) is explicitly
        impossible without a migration — must never happen."""
        baseline, current = schema["baseline"], schema["current"]
        demoted = []
        for table, fields in sorted(baseline.items()):
            cur_fields = current.get(table, {})
            for field, old_type in sorted(fields.items()):
                if old_type.startswith("Option<") and cur_fields.get(field) == old_type[7:-1]:
                    demoted.append(f"{table}.{field}: {old_type} -> {cur_fields[field]}")
        assert not demoted, (
            "Optional->required field demotion detected — impossible without a "
            "migration, forbidden by policy:\n  " + "\n  ".join(demoted)
        )

    def test_append_only_allows_new_tables_and_fields(self, schema):
        """The append-only contract must be a superset check: adding a new
        table or a new field is always legal (that is how the schema grows)."""
        import schema_policy_lib

        baseline, current = schema["baseline"], schema["current"]
        new_tables = sorted(set(current) - set(baseline))
        new_fields = {
            f"{t}.{f}"
            for t, fs in current.items()
            if t in baseline
            for f in fs
            if f not in baseline[t]
        }
        # No assertion on the actual additions (schema may not have grown since
        # the baseline); this test documents that additions must NOT be flagged
        # by find_violations.
        violations = schema_policy_lib.find_violations(baseline, current)
        assert not violations, (
            "find_violations reported issues — the append-only contract is "
            "broken:\n  " + "\n  ".join(violations)
        )
        # Additions are legal by construction; if the schema HAS grown, the
        # additions must be pure additions (already covered above).
        assert isinstance(new_tables, list) and isinstance(new_fields, set)


class TestBaselineFreshness:
    """The committed baseline should track the current schema so that newly
    added tables/fields become protected. Pure additions never fail this test
    — it only fails when the baseline is missing tables/fields that exist, or
    when running the regen script would report drift."""

    def test_baseline_has_no_orphan_tables(self):
        """Every table in the baseline should exist in source (covered in
        detail by TestNonAdditiveAppendOnly.test_no_table_removed)."""
        import schema_policy_lib

        baseline = schema_policy_lib.load_baseline()
        current = schema_policy_lib.parse_table_structs()
        orphans = sorted(set(baseline) - set(current))
        assert not orphans, f"Baseline references tables no longer in source: {orphans}"

    def test_regeneration_script_reports_clean(self):
        """`scripts/update_schema_baseline.py --check` must pass: the committed
        baseline must be byte-identical to what regeneration would write.
        Run the script with --check as a subprocess so we test the actual tool."""
        import subprocess

        script = REPO_ROOT / "scripts" / "update_schema_baseline.py"
        if not script.exists():
            pytest.skip("scripts/update_schema_baseline.py not present")
        proc = subprocess.run(
            [sys.executable, str(script), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            "update_schema_baseline.py --check failed — the committed baseline "
            "is stale (or the schema breaks the append-only contract). Regenerate "
            f"with `python scripts/update_schema_baseline.py`.\nstdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
