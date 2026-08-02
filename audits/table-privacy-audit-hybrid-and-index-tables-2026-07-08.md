# Table Privacy Audit: Hybrid & Index Tables — 2026-07-08

**Scope**: `hybrid_result`, `workspace_index`, `entity_search_index`, `entity_term_index`, `node_edge_index`
**Task**: `task_880f36288406423f`
**ROADMAP ref**: 1.5 Table privacy audit — 50 public tables is too many

## Methodology

Each table was analyzed for:
1. Does the struct carry `workspace_id` or workspace-scoped data?
2. Does the `content` field (or equivalent) carry text from memory/node records?
3. Is the reducer that populates the table gated by workspace-level access control?
4. Does a malicious subscriber see cross-workspace data?
5. Client-side subscription patterns — what filters (if any) are applied?

## Summary

| Table | Workspace Data Leak | Risk | Verdict |
|-------|---------------------|------|---------|
| `hybrid_result` | YES — full content cross-workspace | HIGH | **Leaks confirmed** |
| `workspace_index` | YES — entity ID enumeration per workspace | MODERATE | **Leaks confirmed** |
| `entity_search_index` | MINIMAL — no workspace_id field, but enables cross-ref | LOW | Acceptable with caveat |
| `entity_term_index` | MINIMAL — no workspace_id field, but enables cross-ref | LOW | Acceptable with caveat |
| `node_edge_index` | MINIMAL — no workspace_id, graph structure only | LOW | Acceptable as-is |

---

## 1. `hybrid_result` — HIGH — WORKSPACE DATA LEAK CONFIRMED

**File**: `server/spacetimedb/src/hybrid_query.rs:23`
**Accessor**: `hybrid_result`
**Annotation**: `#[table(accessor = hybrid_result, public)]`

### Schema
```rust
pub struct HybridResult {
    pub id: String,
    pub workspace_id: String,
    pub query_hash: String,
    pub entity_type: String,  // "memory" | "node" | "peer"
    pub entity_id: String,
    pub content: String,       // <-- FULL MEMORY/NODE CONTENT
    pub score: f64,
    pub strategy: String,
    pub context_json: String,
    pub created_at: i64,
}
```

### What leaks
The `content` field carries **the full text content of memories, KG node summaries, and edge descriptions** from the workspace where the search was performed. The `context_json` field carries workspace context and memory context strings. These are stored in a PUBLIC table and are accessible to any connected client.

### How it leaks
1. **Reducer**: `hybrid_search()` (line 381) is called with a `workspace_id` parameter. It calls `require_auth()` (identity check) but **does NOT call `check_space_access()`** — there is no workspace-level permission check. An authenticated client from workspace A can call `hybrid_search(workspace_id="B")` and get results from workspace B. The documentation on `check_space_access` in workspace.rs says "is available for use but is not yet called from every reducer" — this reducer is one of those not yet guarded.

2. **Client subscriptions**: The web client at `client/src/lib/useReactiveDb.ts:65` subscribes with:
   ```
   SELECT * FROM hybrid_result LIMIT 200
   ```
   This fetches ALL hybrid_result rows across ALL workspaces into the local cache. No workspace filter.

3. **No cross-workspace isolation**: The `query_hash` is deterministic (hash of query string), not unguessable. An attacker who knows another workspace's recent queries can enumerate `query_hash` values.

### Reducer access control gap
The `hybrid_search` reducer (line 381-967):
- Authenticates via `require_auth(ctx)?` (line 392) — verifies the caller has an identity
- Does NOT call `check_space_access(ctx, workspace_id, ...)` — no workspace permission verification
- Cleans up only the current (workspace_id, query_hash) combination (lines 421-429)

### Risk assessment
- **Severity**: HIGH — full memory/node text content leaked across workspaces
- **Likelihood**: CERTAIN — the `useReactiveDb` subscription fetches all rows without filtering
- **Impact**: Any authenticated client can read all search-result content from all workspaces

### Recommendations
1. **Add `check_space_access()` guard** to `hybrid_search` and `temporal_search_with_weight` reducers
2. **Filter by workspace_id in client subscriptions**: change `SELECT * FROM hybrid_result LIMIT 200` to `SELECT * FROM hybrid_result WHERE workspace_id = '<current>' LIMIT 200`
3. **Add caller_identity field** to `HybridResult` for multi-tenant isolation
4. **Aggressive TTL cleanup**: delete stale hybrid_result rows older than a configurable TTL (e.g. 5 minutes), since results are only meaningful immediately after a search call

---

## 2. `workspace_index` — MODERATE — WORKSPACE DATA LEAK CONFIRMED

**File**: `server/spacetimedb/src/hybrid_query.rs:69`
**Accessor**: `workspace_index`
**Annotation**: `#[table(accessor = workspace_index, public)]`

### Schema
```rust
pub struct WorkspaceIndex {
    pub id: String,
    pub workspace_id: String,
    pub entity_type: String,  // "memory" | "node" | "search_index" | "term"
    pub entity_id: String,
    pub search_index_id: String,
}
```

### What leaks
- **Direct mapping** of `workspace_id` → `entity_id` for every entity in every workspace
- An attacker can enumerate all entity IDs in any workspace using a single subscription:
  ```sql
  SELECT * FROM workspace_index
  ```
- Combined with the public `entity_search_index`, can trace search_index PKs for those entities

### How it leaks
1. **Public scan table**: Any client subscribes and gets the complete entity-per-workspace index
2. **No access control**: Populated via `register_workspace_entity()` and `register_indexed_entity()` — these are called from various reducers with no workspace permission check on the registry entry
3. **Pre-filtering exposes structure**: The `workspace_entity_ids()` helper (line 359) is used internally by `hybrid_search` for workspace pre-filtering, but the underlying table is readable by all

### Risk assessment
- **Severity**: MODERATE — metadata leak (entity existence), not content
- **Likelihood**: CERTAIN — table is public with no filter
- **Impact**: Attacker can enumerate which entity IDs exist in each workspace and what type they are

### Recommendations
1. **Make private** — only reducer code needs to read workspace_index (the `workspace_entity_ids()` helper runs inside reducers). No client subscription should directly access this table.
2. If keeping public, **remove workspace_id** from the struct (or hash it) so cross-workspace enumeration is not possible

---

## 3. `entity_search_index` — LOW — ACCEPTABLE WITH CAVEAT

**File**: `server/spacetimedb/src/hybrid_query.rs:90`
**Accessor**: `entity_search_index`
**Annotation**: `#[table(accessor = entity_search_index, public)]`

### Schema
```rust
pub struct EntitySearchIndex {
    pub id: String,
    pub entity_id: String,
    pub search_index_id: String,
}
```

### What leaks
- Maps `entity_id` → `search_index_id` (PK reference into the `search_index` table)
- **No `workspace_id`** field — by itself does not reveal which workspace an entity belongs to
- The `entity_id` values are UUIDs, not descriptive text — no direct content leak

### Cross-reference concern
- Since `workspace_index` is also public and contains both `workspace_id` and `entity_id`, combining the two tables reveals: `workspace_id → entity_id → search_index_id`
- This cross-reference chain lets an attacker trace from workspace → search_index rows

### Risk assessment
- **Severity**: LOW — no content, no workspace_id directly, only PK references
- **Likelihood**: LOW — entity IDs are UUIDs, not descriptive
- **Impact**: Enables cross-referencing if `workspace_index` is also compromised

### Recommendations
1. If `workspace_index` is made private, `entity_search_index` is safe as-is
2. If keeping all public, consider hashing `entity_id` values

---

## 4. `entity_term_index` — LOW — ACCEPTABLE WITH CAVEAT

**File**: `server/spacetimedb/src/hybrid_query.rs:109`
**Accessor**: `entity_term_index`
**Annotation**: `#[table(accessor = entity_term_index, public)]`

### Schema
```rust
pub struct EntityTermIndex {
    pub id: String,
    pub entity_id: String,
    pub term_index_id: String,
}
```

### What leaks
- Maps `entity_id` → `term_index_id` (PK reference into `term_index`)
- **No `workspace_id`** — same pattern as `entity_search_index`
- Only used internally by the keyword strategy in `hybrid_search` for O(1) PK lookups

### Risk assessment
- **Severity**: LOW — same pattern as entity_search_index
- **Likelihood**: LOW — entity IDs are UUIDs
- **Impact**: Cross-referencing only

### Recommendations
Same as `entity_search_index` — safe if `workspace_index` access is restricted.

---

## 5. `node_edge_index` — LOW — ACCEPTABLE AS-IS

**File**: `server/spacetimedb/src/hybrid_query.rs:128`
**Accessor**: `node_edge_index`
**Annotation**: `#[table(accessor = node_edge_index, public)]`

### Schema
```rust
pub struct NodeEdgeIndex {
    pub id: String,
    pub node_id: String,
    pub edge_id: String,
}
```

### What leaks
- Maps `node_id` → `edge_id` (PK reference into `kg_edge` table)
- **No `workspace_id`** — no workspace affiliation
- Only used internally by the graph strategy in `hybrid_search` for O(1) edge lookups
- The values are UUIDs/PKs — no descriptive content or workspace mapping

### Risk assessment
- **Severity**: LOW — graph structure only, no workspace metadata
- **Likelihood**: VERY LOW — UUID references only
- **Impact**: Reveals which nodes connect to which edges, but without kg_edge content or workspace context

### Recommendations
Acceptable as-is. Could be made private as a defense-in-depth measure.

---

## Cross-Table Risk: The Chain

The real risk is the **combination** of these public tables:

```
workspace_index (public)      → entity_id, workspace_id — entity existence per workspace
entity_search_index (public)  → entity_id → search_index_id — enables PK lookup into search_index
entity_term_index (public)    → entity_id → term_index_id — enables PK lookup into term_index
node_edge_index (public)      → node_id → edge_id — enables PK lookup into kg_edge
```

A malicious client can:
1. Read `workspace_index` → enumerate all `entity_id` values for any `workspace_id`
2. Read `entity_search_index` → find `search_index_id` for those entities
3. Read `search_index` (if public) → get `content` and `embedding_json` for those entities

**Breaking any single link** in this chain prevents the full exploit. Making `workspace_index` private would be the highest-impact single fix.

## Overall Assessment

| Table | Leaks Workspace Data? | Risk | Action Needed |
|-------|----------------------|------|--------------|
| `hybrid_result` | **YES** — full content | HIGH | Immediate: add workspace access guard + client-side workspace filter |
| `workspace_index` | **YES** — entity existence per workspace | MODERATE | Make private or remove workspace_id from public struct |
| `entity_search_index` | Indirect | LOW | Acceptable if workspace_index is restricted |
| `entity_term_index` | Indirect | LOW | Acceptable if workspace_index is restricted |
| `node_edge_index` | No | LOW | Acceptable as-is |

These findings have been cross-referenced against the existing audit at `audits/table-privacy-audit-2026-07-07.md` and the ROADMAP.md section 1.5 entry.

---
*Generated by task worker task_880f36288406423f on 2026-07-08.*
