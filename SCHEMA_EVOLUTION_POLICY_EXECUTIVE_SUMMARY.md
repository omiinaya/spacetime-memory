# Schema Evolution Policy — Executive Summary

**Source document:** [SCHEMA_EVOLUTION_POLICY.md](./SCHEMA_EVOLUTION_POLICY.md)
**Scope:** All Rust reducer code in `server/spacetimedb/src/`
**Prepared:** 2026-08-05
**Audience:** Engineering leadership, reviewers, new contributors

---

## The One-Line Summary

**Spacetime Memory evolves its database schema by *adding fields with reducer-level defaults* — never by writing migrations.** When a new column is needed, we extend the Rust `#[table]` struct, publish, and let SpacetimeDB auto-add the column; existing rows pick up sensible defaults automatically. Zero migration scripts, zero downtime, zero risk of wiping data.

---

## Why This Policy Exists

| Factor | What it means in practice |
|--------|---------------------------|
| **SpacetimeDB behavior** | On `spacetimedb publish`, new struct fields become new columns automatically; existing rows get the Rust type's default (`0`, `""`, `false`, `[]`). |
| **Operational simplicity** | No migration scripts to write, test, version, or run. No downtime. No partial-migration failures. |
| **Data safety** | `--delete-data=never` is enforced repo-wide. Anything resembling a destructive migration is forbidden by policy. |
| **Backward compatibility** | Lagging clients keep working — new fields are optional at the SQL level. |
| **Proven in the codebase** | The `Memory` table grew 15+ fields across 6 commented "feature blocks" (tiering, reinforcement, hierarchy, consolidation, trust scoring, user isolation) with zero migrations. |

---

## The Rule (5 Steps)

When adding a field to a `#[table]` struct:

1. Add the field to the struct definition with its Rust type.
2. Give every `insert` reducer that creates a row a sensible default.
3. In every `update` reducer, decide explicitly: preserve the existing value, or overwrite with a new default — document the decision in a comment.
4. In every **read path** (result reducers, SDK mappers, queries), handle missing/zero values with `.unwrap_or_default()` / `??` / explicit COALESCE-style logic.
5. **Do not** write a migration reducer. **Do not** use `--delete-data=on-conflict` or `--delete-data=always`.

---

## Defaults at a Glance

| Rust type | STDB auto-default for old rows | Recommended reducer default |
|-----------|-------------------------------|------------------------------|
| `String` | `""` | `String::new()` / semantic base (`"L1"`, `"EXTRACTED"`) |
| `bool` | `false` | explicit `false` or `true` |
| `u64`/`u32`/`i64`/`i32` | `0` | `0`, or semantic (`1` for versions) |
| `f64`/`f32` | `0.0` | `0.5` for scores, `0.0` for counters |
| `Option<T>` | `NULL` | `None` — preferred when "not set" is meaningfully different |
| `Vec<T>` / JSON string | `""` | `"[]"` or `serde_json::to_string(&vec![])` |

**Key nuance:** `Option<T>` is the only way to distinguish "created before this field existed" from "explicitly set to the default". Use it when that distinction matters (e.g. `version: Option<u32>` — `None` = pre-versioning).

---

## Forbidden Patterns

- `--delete-data=on-conflict` or `--delete-data=always` on publish — silently wipes production data.
- Migration reducers that `UPDATE` existing rows to backfill — unnecessary, adds surface area, risks partial failure.
- `ALTER TABLE` SQL inside reducers — unsupported in SpacetimeDB WASM; the Rust struct is the only schema source.
- Reading a new field without a default/COALESCE guard — crashes on old rows at zero values.

---

## Non-Additive (Breaking) Changes: Not Allowed

The schema is **append-only**. The Rust struct only grows.

| Change | Policy |
|--------|--------|
| Rename field | Forbidden — add new field, deprecate old in SDK, never remove |
| Change type | Forbidden — add a new field with the new type, migrate in application logic |
| Remove field | Forbidden — mark deprecated in SDK, leave in struct forever |
| Required → optional | Allowed via `Option<T>`; old rows default to `None` |
| Optional → required | Impossible without migration — don't do it |

---

## What a Contributor Actually Does (Checklist)

1. Add field to the struct (+ comment block header for a new feature group).
2. Add defaults in all insert reducers.
3. Update/decide update reducers, with a comment.
4. Update read paths (reducers, SDK mappers, query helpers).
5. Build: `CARGO_BUILD_JOBS=2 cargo build --release --target wasm32-wasip1`.
6. Publish: `./scripts/publish.sh` (enforces `--delete-data=never`).
7. Verify: `spacetimedb-cli logs -s local-3001 <db-id>`.

---

## Bottom Line for Reviewers

- Schema additions should arrive as **struct field + defaults + read-path guards**, with no migration code anywhere.
- Any PR touching `#[table]` structs should be checked against the five steps above and the forbidden list.
- Deviations require explicit approval in PR review — the policy is binding for all `server/spacetimedb/` contributors.

---

*Generated from [SCHEMA_EVOLUTION_POLICY.md](./SCHEMA_EVOLUTION_POLICY.md) (last updated 2026-07-06). If the policy changes, update this summary.*
