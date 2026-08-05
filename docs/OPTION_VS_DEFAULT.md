# When to Use `Option<T>` vs Default Value

**Part of:** [SCHEMA_EVOLUTION_POLICY.md](../SCHEMA_EVOLUTION_POLICY.md) — Schema Evolution Policy for `spacetime-memory`
**Applies to:** All Rust reducer code in `server/spacetimedb/src/` and every SDK read path
**Last updated:** 2026-08-05

---

## TL;DR

- **Use `Option<T>`** when "not set" is a *meaningful, distinct state* — the row was created before the field existed, the user never supplied a value, or the value is genuinely unknown.
- **Use a plain type with a reducer-level default** (`0`, `0.5`, `""`, `"L1"`, `false`) for counters, scores, enum-like strings, and JSON blobs — things that always have a value.
- **`Option<T>` is the ONLY way to distinguish "unset" from "explicitly set to the default"** in SpacetimeDB. If you don't need that distinction, you don't need `Option<T>`.
- **Every `Option<T>` read path MUST be guarded** with `.unwrap_or(...)` / `.unwrap_or_default()` / `??` / `.get(key, default)`. A bare `.unwrap()` on a `None` column aborts the reducer.

---

## The Core Question: Does "Unset" Mean Something?

SpacetimeDB's schema evolution auto-adds new columns on publish and fills existing
rows with the Rust type's default (`0`, `""`, `false`, `[]`, `NULL`). That means
every field in every table has **three** possible histories:

| History | Plain type reads as | `Option<T>` reads as |
|---------|--------------------|----------------------|
| Row created *after* the field existed, value set normally | the real value | `Some(value)` |
| Row created *after* the field existed, insert reducer used its default | the default (`0`, `""`, …) — **indistinguishable from a real `0`** | `Some(default)` — still set |
| Row created *before* the field existed (old row) | the default (`0`, `""`, …) — **looks like a real value** | `None` — clearly "never set" |

The only scenario where this distinction matters is the last row. Ask yourself:

> **"If I read the default value, do I need to know whether this row actually had
> that value written, or was the column just auto-defaulted because the row is old?"**

If the answer is **no** — the default is a fine value and old rows behave correctly
with it — use a plain type. If the answer is **yes**, use `Option<T>`.

---

## Decision Procedure

Walk this list top to bottom. The first rule that matches wins.

1. **Is the value genuinely optional for the domain?** (e.g. `User.email` — a user
   may have no email on file). → `Option<T>`.
2. **Do old rows need to be distinguishable from new rows?** (e.g. `Note.version` —
   `None` = created before versioning existed). → `Option<T>` (this is the policy's
   canonical "unset matters" case).
3. **Is it a counter, timestamp, or score that starts at zero/neutral?**
   (`access_count`, `feedback_count`, `created_at`, `valid_from`). → plain type,
   default `0` / `0.0` (`0.5` for scores like `strength`, `trust_score`).
4. **Is it an enum-like string with a clear base value?** (`tier` → `"L1"`,
   status → `"EXTRACTED"`). → plain `String`, default = the base value.
5. **Is it a JSON blob that can legitimately be empty?** (`metadata_json`,
   `properties_json`). → plain `String`, default `"{}"` or `"[]"`.
6. **Is it a flag with an explicit default?** (`is_active`, `immutable`). → plain
   `bool`, default `false` (or `true` if that is the safe base).
7. **Anything else?** Default to a plain type with a documented reducer default.
   `Option<T>` is the exception, not the rule.

**Reflex check:** if the field is ever used in a comparison, sort, or arithmetic
(`count > 0`, `score >= 0.5`, `ORDER BY created_at`), it almost certainly wants a
plain type — `None` rows would have to be special-cased everywhere.

---

## Decision Table

| Scenario | Use | Reducer default |
|----------|-----|-----------------|
| Field genuinely optional; "unset" has meaning distinct from default (`User.email`, `first_name`, `last_name`) | `Option<T>` | `None` |
| Old rows must be distinguishable from new rows (`Note.version`) | `Option<T>` | `None` (old rows auto-default to `NULL`) |
| Counter / timestamp starting at zero (`access_count`, `feedback_count`, `valid_from`, `created_at`) | `u64` / `i64` | `0` |
| Score with a neutral base (`strength`, `trust_score`) | `f64` | `0.5` |
| Enum-like string with a base value (`tier`, status) | `String` | `"L1"` / `"EXTRACTED"` |
| JSON blob that may be empty (`metadata_json`) | `String` | `"{}"` / `"[]"` |
| Flag with an explicit default (`is_active`, `immutable`) | `bool` | `false` (or `true`, explicitly) |
| Adding a field where old rows must be *distinguishable* | `Option<T>` — but prefer plain type + separate version field when possible | `None` |

> **Note:** `Option<T>` costs you convenience everywhere it appears — every read
> path must guard, every mapper must COALESCE, every comparison must handle
> `None`. That is the price of "unset" semantics. Do not pay it for fields where
> the default value is a perfectly good answer.

---

## Real Examples in This Codebase

### 1. `Option<T>` done right — `Note.version` (`server/spacetimedb/src/note.rs`)

```rust
/// Version number (incremented on updates for history tracking)
pub version: Option<u32>,
```

`None` = "created before versioning existed"; `Some(n)` = explicit version.
`Some(0)` would be *invalid* — so the distinction is load-bearing, not cosmetic.

Every read path guards:

```rust
let current_version = note.version.unwrap_or(0);
```

No bare `note.version.unwrap()` exists anywhere in production code — the test
suite (`test_schema_evolution_policy.py`) enforces this.

### 2. `Option<T>` done right — `User` PII (`server/spacetimedb/src/user.rs`)

```rust
pub email: Option<String>,
pub first_name: Option<String>,
pub last_name: Option<String>,
```

An empty string (`""`) is not the same as "no email on file" — `""` is a value
you might accidentally write, `None` is unambiguous. PII that a user may never
provide is the textbook `Option<String>` case.

### 3. Default values done right — `Memory` feature blocks (`server/spacetimedb/src/memory.rs`)

```rust
// ---- OpenViking: Tiered contexts ----
pub tier: String,                    // default: "L1"

// ---- RetainDB: Reinforcement & Versioning ----
pub access_count: u64,               // default: 0
pub strength: f64,                   // default: 0.5
pub version: u32,                    // default: 1
pub valid_from: i64,                 // default: 0
pub valid_to: i64,                   // default: 0

// ---- Holographic: Trust Scoring & Feedback ----
pub trust_score: f64,                // default: 0.5
pub feedback_count: u32,             // default: 0

// ---- Source attribution ----
pub source_url: Option<String>,      // default: None ("not set") — Some("") = no source recorded
```

None of these are `Option<T>` — a counter with no events is genuinely `0`, a
memory that never got feedback has `trust_score: 0.5` (neutral), an un-tiered
memory is `tier: "L1"`. Old rows reading `0`/`"L1"` behave *identically* to new
rows that were never updated, which is exactly what the product wants.

> **`source_url` is the exception:** it is `Option<String>` (see `memory.rs`).
> STDB cannot add a required `String` column to an existing table — the publish
> fails with `Changing the type of column source_url ... requires a manual
> migration` (verified 2026-08-05, see `SCHEMA_EVOLUTION_POLICY.md`). The new
> column arrives as `NULL` on old rows, which `None` models. Read paths COALESCE
> `None` to `""` when serializing (e.g. `m.source_url.clone().unwrap_or_default()`
> in `query.rs`), so SDK consumers still see a plain string. Do not "simplify"
> `Option<String>` back to `String` — it makes the module unpublishable.

### 4. `Option` as a reducer parameter — `update_note_block` (`note.rs`)

```rust
pub fn update_note_block(
    ctx: &ReducerContext,
    note_id: String,
    block_id: String,
    expected_note_version: u32,
    task_state: String,
    properties_json: String,
    block_content: String,
    is_active: Option<bool>,   // None = caller did not request a change
) -> Result<(), String>
```

This is a *different* use of `Option<T>`: "the caller did not pass this
argument" vs "the caller explicitly passed `false`". The same decision rule
applies — the distinction matters here because the reducer must not clobber
`is_active` when the caller only wanted to update `block_content`.

---

## Read-Path Guarding (Step 4 of the Policy Rule)

`Option<T>` columns are `NULL` on old rows. Reading them without a guard is a
reducer abort waiting to happen. The policy's step 4 applies everywhere a value
crosses a boundary:

| Boundary | Guard form |
|----------|------------|
| Rust reducer reading a row | `note.version.unwrap_or(0)` / `.unwrap_or_default()` |
| Rust reducer building a result row | `version: note.version.unwrap_or(0)` |
| Python SDK mapper | `row.get("tier", "L1")` — never `row["tier"]` |
| TypeScript SDK mapper | `row.tier ?? "L1"` — never bare `row.tier` |

**Forbidden:** bare `.unwrap()` on any table-lookup result or `Option` column in
production reducer code. (`test_schema_evolution_policy.py` greps the source and
fails the build if one slips in.)

---

## The Append-Only Transition Rule

| Transition | Allowed? | Notes |
|------------|----------|-------|
| Add a new field (plain or `Option`) | ✅ Always | This is how the schema grows. |
| `T` → `Option<T>` (required → optional) | ✅ Only permitted type change | Old rows auto-default to `None`. |
| `Option<T>` → `T` (optional → required) | ❌ Forbidden | Impossible without a migration; `None` rows would have no value. |
| Rename / remove / retype a field | ❌ Forbidden | Add a new field instead; the struct only grows. |

The committed baseline (`sdk/python/tests/data/schema_baseline.json`) is the
lower bound: `scripts/update_schema_baseline.py` regenerates it and refuses to
shrink it, and `test_schema_evolution_policy.py` verifies the append-only
contract on every run.

---

## Common Mistakes

1. **`Option<String>` for enum-like strings.** `tier: Option<String>` forces
   every consumer to handle `None` when `"L1"` is a perfectly good base. Use
   `String` with the base default.
2. **`Option<u64>` for counters.** `Some(0)` and `None` are both "no events" in
   practice — you paid the `Option` tax for nothing. Use `u64` + `0`.
3. **Bare `.unwrap()` on an old row.** `note.version.unwrap()` aborts the whole
   reducer on a pre-versioning note. Always `.unwrap_or(...)`.
4. **Treating `""` as "unset" for PII.** An empty email is a value (possibly a
   bug); `None` is a fact about the user. Use `Option<String>`.
5. **`bool` with no explicit insert default.** `is_active` silently defaults to
   `false` on old rows — fine when `false` is right, dangerous when the safe base
   is `true`. State the default explicitly in the reducer and in a comment.
6. **Skipping the read-path guard "because we just added the field".** The
   moment you publish, old rows exist with the zero value. Guard first, publish
   after.

---

## Enforcement

The decision table is codified in `sdk/python/tests/test_schema_evolution_policy.py`
(source-scanning, no STDB required). It asserts, among other things:

- `Note.version` is `Option<u32>` and every read uses `.unwrap_or(0)` — never a bare `.unwrap()`.
- `User.email` / `first_name` / `last_name` are `Option<String>`.
- `Memory` counters/scores/enum-strings (`access_count`, `strength`,
  `feedback_count`, `trust_score`, `tier`, `user_scope`) are plain types with the
  documented defaults.
- SDK read paths COALESCE every additive `Memory` field they touch.
- **Every** `#[table]` struct's insert sites conform to the "SpacetimeDB
  Defaults by Rust Type" table — audited across all 140 tables by
  `scripts/audit_rust_type_defaults.py` (wired into the test suite as
  `TestAllTablesDefaultsByRustType`). Any field of a policy-covered type
  (`String`, `bool`, integer, `f64/f32`, `Option<T>`, `Vec<T>`)
  initialized with a non-conformant default fails CI.
- No migration/backfill reducers, no `ALTER TABLE`, no destructive
  `--delete-data` flags, and `scripts/publish.sh` hardcodes `--delete-data=never`.

If a test in that file (or `scripts/audit_rust_type_defaults.py`'s own self-test)
fails, the schema policy is being violated — **fix the code, not the test.**

---

## Related Documents

- `SCHEMA_EVOLUTION_POLICY.md` — the canonical policy (this document expands its "When to Use `Option<T>` vs Default Value" section)
- `SCHEMA_EVOLUTION_POLICY_EXECUTIVE_SUMMARY.md` — one-page executive summary
- `docs/SCHEMA_EVOLUTION_POLICY_RATIONALE.md` — why the policy exists (evidence-based rationale)
- `AGENTS.md` — agent schema + development guide (see "Data Safety")
- `scripts/publish.sh` — enforces `--delete-data=never`

---

*This reference is binding for all contributors to `server/spacetimedb/`. Deviations require explicit approval in PR review.*
