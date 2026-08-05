# Why This Policy? — The Rationale Behind Spacetime Memory's Schema Evolution Policy

**Source document:** [SCHEMA_EVOLUTION_POLICY.md](../SCHEMA_EVOLUTION_POLICY.md)
**Companion doc:** [SCHEMA_EVOLUTION_POLICY_EXECUTIVE_SUMMARY.md](../SCHEMA_EVOLUTION_POLICY_EXECUTIVE_SUMMARY.md)
**Written / verified:** 2026-08-05
**Scope:** All Rust reducer code in `server/spacetimedb/src/`

---

## The Policy In One Sentence

> **Add fields with reducer-level defaults. Never write migrations.**

Every factor below was re-verified against the live codebase while writing this
document (git `dev`, `Memory` struct in `memory.rs`, `publish.sh`, reducer
surveys). None of the rationale is hypothetical — it is how the module already
works.

---

## 1. The Root Problem This Policy Solves

`spacetime-memory` is a **production SpacetimeDB module serving real,
multi-tenant data** (workspaces, notes, memory graphs, veracity evidence). Its
tables hold rows that were created weeks or months ago and must survive every
release.

A schema is a contract between every released version of the module and every
row already on disk. The hard part of schema evolution is the same everywhere:

- Brand-new installs must get the new schema.
- Existing installs must be brought from the old schema to the new one **without
  losing data, without downtime, and without a partial/failed transition.**

Classic SQL databases solve this with imperative migration scripts
(`ALTER TABLE ... ADD COLUMN`, backfill `UPDATE`s) run in a controlled upgrade
window. This policy exists because — as detailed below — **that machinery is
either unavailable, dangerous, or strictly worse than the alternative in the
SpacetimeDB WASM model.**

---

## 2. What SpacetimeDB Already Gives Us For Free

The single most important fact: **SpacetimeDB auto-adds columns on publish.**

On `spacetimedb publish`, every new field in a `#[table]` Rust struct is
automatically added as a column to the live table. Existing rows are not
deleted or rewritten — they simply receive the Rust type's default value for
the new column:

| Rust type | Existing-row default |
|-----------|----------------------|
| `String`  | `""` |
| `bool`    | `false` |
| integers  | `0` |
| floats    | `0.0` |
| `Option<T>` | `NULL` |

This is the "additive field" case that this policy is fundamentally about.
Because STDB does the column addition itself, **there is nothing for us to
write** for the *structural* half of the change. The platform closes the
"existing installs get the new schema" requirement automatically, atomically,
and with zero downtime.

> This is the crux of the whole policy. The most error-prone half of schema
> evolution — restructuring stored rows — is handled by the database engine,
> not by us.

---

## 3. Why The Obvious Alternative (Migrations) Is The Wrong Tool Here

If CLI migrations worked well, we'd write them. In this environment they are
each blocked for a concrete reason:

### 3.1 `ALTER TABLE` SQL is not supported in the WASM module

The schema is defined **only** by Rust `#[table]` structs compiled to WASM.
There is no SQL `ALTER TABLE` path inside a reducer — reducers run in a
constrained WASM sandbox over STDB's table API. You cannot "ALTER" a table
from a reducer; you can only `insert`/`update`/`delete` rows of the schema the
module was compiled with. So the imperative-SQL migration toolbox does not
exist here at all.

### 3.2 `--delete-data` flags are destructive and forbidden

When a publish *does* need destructive changes, the CLI asks for
`--delete-data=on-conflict` (wipe tables whose schema conflicts) or
`--delete-data=always` (wipe everything). This codebase treats production data
as sacred:

- `scripts/publish.sh` **hardcodes** `--delete-data=never` (verified, line 128)
  and even blocks the `DELETE_DATA` environment variable at startup
  (verified, lines 29–36).
- `AGENTS.md` repeats the same rule and documents `--delete-data=never` as the
  only sanctioned mode.

So the "easy" escape hatch for non-additive changes is explicitly engineered
out of the repo. A migration that *requires* data deletion cannot be run by any
tool the project permits.

### 3.3 Backfill `UPDATE` reducers add failure surface with no benefit

The other "migration-ish" pattern is a reducer that iterates existing rows and
backfills the new field. This is **unnecessary** — STDB already defaults the
field on column add — and it only adds risk:

- It's new reducer surface area to write, test, and version.
- It runs as one big state-changing operation; if it errors partway, you have a
  **partial migration** (some rows backfilled, some not), and nothing tracks
  which rows were touched.
- It touches every row in the table on every release, which does not scale.

The COALESCE/defaults approach needs **no** sweeps: read paths treat the zero
value as "use the default" via `.unwrap_or_default()` / `??`, so old and new
rows behave identically without ever being rewritten.

---

## 4. The Resulting Economics (Why This Is Strictly Better Here)

| Concern | Migration approach | COALESCE / defaults approach |
|---------|--------------------|------------------------------|
| **Structural schema change** | Needs `ALTER` (unavailable) or delete-data (forbidden) | Free — STDB auto-adds the column |
| **Backfilling old rows** | Backfill reducer (partial-failure risk) | None — read paths default on zero |
| **Downtime** | Upgrade window to run scripts | None — publish is the only step |
| **Versioning / testing the migration** | Must version, test, run, rollback | Nothing to version; defaults live in normal reducer code |
| **Data loss risk** | Real (`--delete-data`, partial backfill) | Zero for additive changes |
| **Compatibility with lagging clients** | Old clients break if schema is rewritten | New fields optional — old code keeps working |

Every row of the table favors the policy. The migration approach offers **no
advantage** for additive changes and several concrete risks. When one option
is strictly safer and simpler, choosing it is not a compromise — it's the
rational optimum.

---

## 5. Evidence: This Is Already How The Module Evolved

The policy did not come from theory; it codifies what `spacetime-memory` has
been doing successfully across many releases. Three verified examples:

### 5.1 The `Memory` struct grew 15+ fields across 6 feature groups — zero migrations

`server/spacetimedb/src/memory.rs` (lines 41–74) documents its own evolution
in commented feature blocks, each appended onto an existing production table
with nothing but struct fields + reducer defaults:

```
// ---- OpenViking: Tiered contexts ----      -> tier: String            (default "L1")
// ---- RetainDB: Reinforcement & Versioning -> access_count, strength, version,
//                                               valid_from, valid_to
// ---- OpenViking: Hierarchy ----            -> parent_directory_id      (default "")
// ---- RetainDB: Consolidation ----          -> consolidated_to          (default "")
// ---- Holographic: Trust Scoring & Feedback-> trust_score, feedback_count
// ---- User-level isolation (Mem0 parity) -- -> user_scope               (default "")
```

None of these required a migration, an `ALTER`, or a data wipe. Each was a
struct edit + a default in `store_memory`/`store_memory_batch` + a guard in
read paths. **This is the empirical proof that the approach scales.**

### 5.2 `memory_meta.rs` explicitly avoids migrations on purpose

The `MemoryMeta` design comment (verified, lines 11–15) states it stores
extensible metadata **in a separate table specifically "so we don't need
schema migrations** on the core memory table." The codebase is not merely
tolerant of the policy — it is *architected* around avoiding migrations.

### 5.3 `veracity.rs` handles pre-existing data with reducer defaults, not a backfill

When veracity was added, rows created before it existed have no evidence. The
code handles this inline (`// ... migration from pre-veracity data`, verified
line 188) by treating "no evidence row" as a valid default state —
`.ok_or_else(...)` / create-on-miss — rather than shipping a separate
migration reducer. Old memories keep working immediately.

---

## 6. The Cost Honestly Stated (Trade-offs We Accept)

The policy is not free of downsides; we accept them knowingly because they are
cheap relative to the benefits:

1. **Append-only bloat.** Fields are never removed, so the struct accumulates
   deprecated columns (`consolidated_to`, `user_scope` edge cases, etc.). Cost:
   cosmetic noise + a little storage. Benefit: never breaks old clients or old
   rows. The schema grows monotonically by design.
2. **Zero vs. "unset" ambiguity.** Non-`Option` fields cannot distinguish
   "created before this field existed" from "explicitly set to the zero value."
   Mitigation: use `Option<T>` when that semantic distinction actually matters
   (e.g. `note.version: Option<u32>` — `None` = pre-versioning), and document
   the chosen default on every field.
3. **No built-in breaking-change path.** This policy explicitly answers "what do
   we do for a true breaking change?" with **"we don't make breaking changes"**.
   Renames, type changes, and removals are all forbidden (see the policy's
   "Non-Additive Changes" table). When data genuinely must move shape — e.g. the
   `ITER_AUDIT.md` note that adding `workspace_id` to `peer_reputation` /
   `entity_link` / `kg_node` "would fix remaining cross-workspace scans but
   requires schema migration" — the policy's answer is: **add a new
   field/table and migrate in application logic**, not a destructive rewrite.

The first two are trivial day-to-day costs. The third is a deliberate
architectural stance: **the schema is append-only and the Rust struct is the
source of truth; it only grows.**

---

## 7. When This Policy Would Change

The COALESCE/defaults policy is the right call *because* the module is
append-only and additive changes dominate. It would deserve a rethink only in a
scenario the project has explicitly ruled out — genuine schema rewrites that
cannot be expressed as additive columns (e.g. a required cross-table key on
exhaustively existing rows). Even then the revivers' bar is high: it would
require a real migration tool + a documented, backup-verified data-preserving
path, both gated behind the same `--delete-data=never` safety culture — not the
destructive wipe the CLI default tempts you with.

---

## 8. Bottom Line

**This policy exists because SpacetimeDB makes additive schema evolution free
and makes the alternatives (SQL `ALTER`, delete-data publishes, backfill
sweeps) either unavailable, forbidden, or strictly riskier — and because the
module's own history proves the free path works for many releases.** The rule
"add a field, give it a default, guard the read paths, publish with
`--delete-data=never`" costs almost nothing, risks nothing, and has carried a
15+-field, 6-feature-group `Memory` table from v2-era through to multi-feature
parity without a single migration.

It is not a workaround. It is the optimal strategy for this platform.

---

*Cross-referenced from [SCHEMA_EVOLUTION_POLICY.md](../SCHEMA_EVOLUTION_POLICY.md). Keep in sync with the policy and its executive summary when the policy changes.*