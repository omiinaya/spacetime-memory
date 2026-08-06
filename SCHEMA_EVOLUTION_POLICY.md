# Schema Evolution Policy — Spacetime Memory

**Status:** Canonical policy for the `spacetime-memory` SpacetimeDB module  
**Applies to:** All Rust reducer code in `server/spacetimedb/src/`  
**Last updated:** 2026-08-05

---

## Executive Summary

**Default strategy: COALESCE / default values in reducers — NOT migrations.**

When adding fields to SpacetimeDB tables, we rely on SpacetimeDB's built-in schema evolution (automatic column addition on module publish) and provide sensible defaults in reducer code. We do **not** write imperative migration reducers or backfill scripts for additive schema changes.

---

## Why This Policy?

| Factor | Assessment |
|--------|------------|
| **SpacetimeDB behavior** | On `spacetimedb publish`, new fields in `#[table]` structs are automatically added as columns. Existing rows receive the type's default value (0, `""`, `false`, `[]`, etc.). |
| **Operational simplicity** | No migration scripts to write, test, version, or run. No downtime. No risk of partial migration. |
| **Data safety** | `--delete-data=never` is enforced (see `AGENTS.md`). Migrations with `DELETE DATA` are forbidden. |
| **Backward compatibility** | Old reducer code (if any clients lag) continues to work — new fields are optional at the SQL level. |
| **Observed pattern** | The codebase already follows this: `Memory` struct grew 12 fields across 7 commented "feature blocks" (28 total fields: tiering, reinforcement, hierarchy, consolidation, trust scoring, user isolation, source attribution) — all added with reducer-level defaults, zero migrations. |

---

## The Rule

> **When adding a field to a `#[table]` struct:**
> 1. Add the field to the struct definition with its Rust type.
> 2. In every `insert` reducer that creates a row, provide a sensible default.
> 3. In every `update` reducer, decide: preserve existing value, or overwrite with a new default?
> 4. In **read paths** (reducers that return data, SDK mappers, queries), handle missing/zero values with `.unwrap_or_default()` or explicit `COALESCE`-style logic.
> 5. **Do not** write a migration reducer. **Do not** use `--delete-data=on-conflict` or `--delete-data=always`.

---

## SpacetimeDB Defaults by Rust Type

| Rust type | STDB column default (existing rows) | Recommended reducer default |
|-----------|--------------------------------------|------------------------------|
| `String` | `""` | `String::new()` or `String::from("L1")` |
| `bool` | `false` | `false` or `true` (explicit) |
| `u64` / `u32` / `i64` / `i32` | `0` | `0` or semantic default (`1` for version) |
| `u8` / `u16` | `0` | `0` (e.g., `severity: u8` = `0`, `response_code: u16` = `0`) |
| `f64` / `f32` | `0.0` | `0.5` for scores, `0.0` for counters |
| `Option<T>` | `NULL` | `None` (preferred for "not set" semantics) |
| `Option<String>` | `NULL` | `None` (e.g., `User.email` — `None` = no email on file) |
| `Vec<T>` / JSON string | `""` | `String::from("[]")` or `serde_json::to_string(&vec![]).unwrap()` |

> **Note:** `u8`/`u16` follow the same zero-default rule as the wider integer types — used for `severity` (`0`=recovery, `1`=warning, `2`=critical in `EmbedderAlert`/`TantivyAlert`), `heading_level` (`NoteBlock`), and `response_code` (`WebhookDelivery`; `0` = not yet delivered).

> **Note:** `Option<T>` fields are the only way to distinguish "not set" from "explicitly set to default". Use `Option` when the semantic difference matters (e.g., `version: Option<u32>` — `None` means "created before versioning existed", `Some(0)` is invalid).

---

## Patterns in This Codebase

### 1. Additive Field Blocks (Memory.rs)

The `Memory` struct documents its evolution in comment blocks:

```rust
// ---- OpenViking: Tiered contexts ----
pub tier: String,                    // default: "L1"

// ---- RetainDB: Reinforcement & Versioning ----
pub access_count: u64,               // default: 0
pub strength: f64,                   // default: 0.5
pub version: u32,                    // default: 1
pub valid_from: i64,                 // default: 0
pub valid_to: i64,                   // default: 0

// ---- OpenViking: Hierarchy ----
pub parent_directory_id: String,     // default: ""

// ---- RetainDB: Consolidation ----
pub consolidated_to: String,         // default: ""

// ---- Holographic: Trust Scoring & Feedback ----
pub trust_score: f64,                // default: 0.5
pub feedback_count: u32,             // default: 0

// ---- User-level isolation (Mem0 parity) ----
pub user_scope: String,              // default: ""
```

All defaults are provided in `store_memory` and `store_memory_batch` reducers.

### 2. Option for Semantic "Not Set" (Note.rs)

```rust
pub version: Option<u32>,  // None = pre-versioning; Some(n) = explicit version
```

Read path handles it:
```rust
let current_version = note.version.unwrap_or(0);
```

### 3. Read-Side COALESCE Patterns

**In reducers returning result tables:**
```rust
metadata_json: if metadata_json.is_empty() { String::from("{}") } else { metadata_json }
```

**In SDK mappers (Python/TS):**
```python
# Python SDK - spacetime_memory/client/_base.py
# COALESCE via dataclass field default; from_dict filters raw rows:
@dataclass
class MemoryRecord:
    # ... additive fields mirror the STDB table (required — rows always include them)
    source_url: str = ""  # absent row key -> COALESCE to ""

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
```

```typescript
// TS SDK - sdk/typescript/src/types.ts (typed MemoryRecord — mirrors the
// STDB table; COALESCE happens in row consumers via `??` where rows are raw)
export interface MemoryRecord {
  // ...
  tier: string;
  strength: number;
  access_count: number;
  source_url: string;
}
```

---

## When to Use `Option<T>` vs Default Value

| Scenario | Use |
|----------|-----|
| Field is genuinely optional; "unset" has meaning distinct from default | `Option<T>` |
| Field is a counter/score that starts at zero | `u64` / `f64` with default `0` / `0.5` |
| Field is an enum-like string with a clear "base" value | `String` with default `"L1"` / `"EXTRACTED"` |
| Field is a JSON blob that can be empty | `String` with default `"{}"` or `"[]"` |
| Adding a field to an existing table where old rows must be distinguishable | `Option<T>` (but prefer default + version field) |

> **Full decision procedure, worked examples, and pitfalls:** see
> [docs/OPTION_VS_DEFAULT.md](docs/OPTION_VS_DEFAULT.md) — *"When to Use `Option<T>` vs Default Value"*.
> It expands this table into a decision checklist grounded in real fields
> (`Note.version`, `User.email`, `Memory` feature blocks) and is enforced by
> `sdk/python/tests/test_schema_evolution_policy.py` (per-table cases) plus
> `scripts/audit_rust_type_defaults.py` (full-module scan of **all** table
> insert sites against this Defaults-by-Rust-Type table).

---

## Forbidden Patterns

| Pattern | Why Forbidden |
|---------|---------------|
| `spacetimedb publish --delete-data=on-conflict` | Silently wipes production data on schema change. Enforced by `./scripts/publish.sh`. |
| `spacetimedb publish --delete-data=always` | Same — only allowed with explicit backup + user confirmation. |
| Migration reducer that `UPDATE`s existing rows to backfill | Unnecessary (STDB does it), adds reducer surface area, risks partial failure. |
| `ALTER TABLE` SQL in reducers | Not supported in SpacetimeDB WASM; schema is defined by Rust structs only. |
| Reading a new field without `.unwrap_or_default()` / `??` / `COALESCE` | Will crash on old rows where the field is at its zero value. |

---

## Publishing Checklist (Additive Schema Change)

1. [ ] Add field to `#[table]` struct in appropriate `.rs` file.
2. [ ] Add default in all `insert` reducers for that table.
3. [ ] Update `update` reducers: preserve or reset? Document decision in comment.
4. [ ] Update read paths (result table reducers, SDK mappers, query helpers) with defaults.
5. [ ] Add comment block header if this is a new "feature group" (see `Memory.rs`).
6. [ ] Build: `CARGO_BUILD_JOBS=2 cargo build --release --target wasm32-unknown-unknown`
7. [ ] Publish: `./scripts/publish.sh` (enforces `--delete-data=never`)
8. [ ] Verify reducer list: `spacetimedb-cli logs -s local-3001 <db-id>`

---

## Example: Adding a `source_url` Field to `Memory`

**Step 1 — Struct:** (as actually committed — `Option<String>`, the ONLY type STDB
accepts when adding a string column to an existing table)
```rust
// ---- Source attribution ----
/// URL the memory was sourced from; `None` = no source recorded.
/// `Option<String>` (not plain `String`) because STDB cannot add a required
/// `String` column to an existing table — existing rows would need a manual
/// migration. Old rows default to `None`.
pub source_url: Option<String>,
```
> **Why not plain `String`?** STDB refuses the publish with
> `Changing the type of column source_url ... requires a manual migration`
> (verified 2026-08-05). The Defaults-by-Rust-Type table's `""` default applies
> to *reducer-level* defaults on new inserts; the *schema-level* column addition
> still requires `Option<T>` (or `#[default(...)]` where supported). Do not
> "simplify" `Option<String>` back to `String` — it makes the module unpublishable.

**Step 2 — Insert reducer:**
```rust
source_url: None,  // default: None = new row, no source yet
```

**Step 3 — Update reducer (preserve existing):**
```rust
// source_url is immutable after creation — do not overwrite
// mem.source_url = mem.source_url;  // implicit
```

**Step 4 — Read path (Python SDK):**
```python
# Python SDK - spacetime_memory/client/_base.py MemoryRecord.from_dict
# COALESCE via dataclass field default:
class MemoryRecord:
    # ...
    source_url: str = ""
```

**Step 5 — Read path (TS SDK):**
```typescript
// sdk/typescript/src/types.ts — source_url is an optional string field
source_url?: string;
```

**Step 5b — Read path (Rust query helpers):** the `query_memory` reducer must
COALESCE the Option before emitting JSON, or rows serialize as `null`:
```rust
"source_url": m.source_url.clone().unwrap_or_default(),  // None -> ""
```

**Step 6 — Publish:**
```bash
./scripts/publish.sh
```

---

## Non-Additive Changes (Breaking)

| Change | Policy |
|--------|--------|
| **Rename field** | Forbidden. Add new field, deprecate old in SDK, never remove from struct. |
| **Change type** | Forbidden. Add new field with new type, migrate data in application logic. |
| **Remove field** | Forbidden. Mark deprecated in SDK, leave in struct forever. |
| **Make required → optional** | Use `Option<T>`; default `None` for old rows. |
| **Make optional → required** | Impossible without migration. Don't do it. |

> **Bottom line:** Schema is **append-only**. The Rust struct is the source of truth; it only grows.

---

## Related Documents

- `AGENTS.md` — Agent schema + development guide (see "Data Safety" section)
- `docs/OPTION_VS_DEFAULT.md` — **When to Use `Option<T>` vs Default Value** (full decision procedure + worked examples + pitfalls)
- `scripts/audit_rust_type_defaults.py` — **Full-module enforcement of the Defaults-by-Rust-Type table** (scans every `#[table]` insert site; wired into CI via `TestAllTablesDefaultsByRustType`; own negative self-test in `scripts/test_audit_rust_type_defaults.py`)
- `scripts/publish.sh` — Enforces `--delete-data=never`
- `docs/SCHEMA_EVOLUTION_POLICY_RATIONALE.md` — **Why this policy exists** (full evidence-based rationale)
- `SCHEMA_EVOLUTION_POLICY_EXECUTIVE_SUMMARY.md` — One-page executive summary
- `ROADMAP.md` — The old roadmap tracked a "Phase 4.3 — Schema migrations" question (*"when adding fields, do we use COALESCE/default, or do we migrate?"*). **This policy resolves that item** — the answer is COALESCE/default. The current `ROADMAP.md` is an honest-governance assessment covering the question as resolved.
- `CONTRIBUTING.md` — Contribution workflow

---

## Decision Log

Chronological record of policy-affecting decisions. Newest entries go at the
bottom. When you make a schema/evolution decision covered by this policy,
log it here with its date, the decision, and the rationale.

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07-06 | Adopt COALESCE/default policy | Matches existing codebase patterns; SpacetimeDB auto-adds columns; zero-migration operational model. |
| 2026-08-05 | New `String` columns on **existing** tables must be `Option<String>`, not plain `String` | Verified live (commit `bf2e6a6`): STDB refuses to publish a required `String` column onto an existing table — `Changing the type of column source_url ... requires a manual migration`. The Defaults-by-Rust-Type table's `""` default applies only to **reducer-level** defaults on new inserts; the **schema-level** column addition still requires `Option<T>` (or `#[default(...)]` where supported). Applied to `Memory.source_url`. Do not "simplify" `Option<String>` back to `String` — it makes the module unpublishable. |
| 2026-08-05 | Codify an explicit `Option<T>` vs default-value decision procedure in `docs/OPTION_VS_DEFAULT.md` | The prose policy stated "Use `Option<T>` when unset matters" but gave no checklist. Worked examples (`note.version`, `User.email`, `Memory` feature blocks) plus a front-loaded TL;DR give contributors a repeatable procedure; enforced per-table by `sdk/python/tests/test_schema_evolution_policy.py::TestOptionVsDefaultDecision` and `TestOptionReadPathsGuarded`. |
| 2026-08-05 | Make the policy machine-enforced (append-only contract + defaults audit) wired into CI | Policy compliance previously relied on manual review. Now: `sdk/python/tests/schema_policy_lib.py` + committed `schema_baseline.json` assert `current schema ⊇ baseline` (only permitted transition `T` → `Option<T>`; no table/field removal, no type change — `TestNonAdditiveAppendOnly`), and `scripts/audit_rust_type_defaults.py` scans every `#[table]` insert site against the Defaults-by-Rust-Type table (`TestAllTablesDefaultsByRustType`). Baseline regenerated via `scripts/update_schema_baseline.py`, which refuses to write a shrinking baseline. |

---

*This policy is binding for all contributors to `server/spacetimedb/`. Deviations require explicit approval in PR review.*
