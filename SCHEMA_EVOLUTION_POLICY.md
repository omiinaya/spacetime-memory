# Schema Evolution Policy — Spacetime Memory

**Status:** Canonical policy for the `spacetime-memory` SpacetimeDB module  
**Applies to:** All Rust reducer code in `server/spacetimedb/src/`  
**Last updated:** 2026-07-06

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
| **Observed pattern** | The codebase already follows this: `Memory` struct grew 15+ fields across 6 commented "feature blocks" — all added with reducer-level defaults, zero migrations. |

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
| `f64` / `f32` | `0.0` | `0.5` for scores, `0.0` for counters |
| `Option<T>` | `NULL` | `None` (preferred for "not set" semantics) |
| `Vec<T>` / JSON string | `""` | `String::from("[]")` or `serde_json::to_string(&vec![]).unwrap()` |

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
# Python SDK - client.py
Memory(
    tier=row.get("tier", "L1"),
    access_count=row.get("access_count", 0),
    strength=row.get("strength", 0.5),
    ...
)
```

```typescript
// TS SDK - client.ts
tier: row.tier ?? "L1",
accessCount: row.access_count ?? 0,
strength: row.strength ?? 0.5,
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
6. [ ] Build: `CARGO_BUILD_JOBS=2 cargo build --release --target wasm32-wasip1`
7. [ ] Publish: `./scripts/publish.sh` (enforces `--delete-data=never`)
8. [ ] Verify reducer list: `spacetimedb-cli logs -s local-3001 <db-id>`

---

## Example: Adding a `source_url` Field to `Memory`

**Step 1 — Struct:**
```rust
pub struct Memory {
    // ... existing fields ...
    pub source_url: String,  // NEW
}
```

**Step 2 — Insert reducer:**
```rust
let mem = Memory {
    // ... existing fields ...
    source_url: String::new(),  // default: empty string
};
```

**Step 3 — Update reducer (preserve existing):**
```rust
// source_url is immutable after creation — do not overwrite
// mem.source_url = mem.source_url;  // implicit
```

**Step 4 — Read path (Python SDK):**
```python
Memory(
    # ...
    source_url=row.get("source_url", ""),
)
```

**Step 5 — Read path (TS SDK):**
```typescript
sourceUrl: row.source_url ?? "",
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
- `scripts/publish.sh` — Enforces `--delete-data=never`
- `ROADMAP.md` — Phase 4.3 "Schema migrations" (this policy resolves that item)
- `CONTRIBUTING.md` — Contribution workflow

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07-06 | Adopt COALESCE/default policy | Matches existing codebase patterns; SpacetimeDB auto-adds columns; zero-migration operational model. |

---

*This policy is binding for all contributors to `server/spacetimedb/`. Deviations require explicit approval in PR review.*
