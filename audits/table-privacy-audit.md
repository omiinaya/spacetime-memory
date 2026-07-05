# Table Privacy Audit

> **Date:** 2026-07-05
> **Scope:** All SpacetimeDB tables in spacetime-memory server module
> **Total tables:** 89 across all modules
> **Public tables:** 41 (confirmed via `#[table(..., public)]` annotations)

## Summary

This audit examines 41 public tables for data exposure risks. The core vulnerability pattern is: **public result tables that lack `caller_identity` scoping** — allowing any connected client to read another user's query results by iterating the table.

### Three Risk Classes

| Risk | Count | Root Cause |
|------|-------|-----------|
| **CRITICAL** | 1 | Full-entity public table containing raw encryption keys — `workspace_encryption_key` |
| **HIGH** | 5 | Full-entity public tables or result tables with PII / full content + no caller scoping |
| **MEDIUM** | 11 | Result tables with query_id-only scoping — no caller identity enforcement |
| **LOW** | 24 | Aggregate stats, operational metrics, or structural metadata — acceptable |

## CRITICAL Risk Tables

### 0. `workspace_encryption_key` (crypto.rs:20 — `#[table(accessor = workspace_encryption_key, public)]`)

**Fields:** `workspace_id`, `key_hex` (AES-256 raw key), `created_by`, `enabled`, `created_at`

**Problem:** This is a **full entity table** (not a result table) marked public. Any client connected to SpacetimeDB can query every row — getting the raw AES-256 encryption keys for all workspaces. This completely defeats the purpose of at-rest encryption: any connected identity can decrypt any encrypted memory.

**Exposure:** Complete breach of all workspace encryption. Every encrypted memory becomes readable.

**Fix:** Make `workspace_encryption_key` table **private** immediately. The reducers (`init_workspace_encryption`, `rotate_workspace_encryption_key`, `set_workspace_encryption_enabled`) already gate on `require_admin` — the only reason this table needs to be public is if the admin panel queries it directly via SQL. That should be done through an admin-gated result table instead.

## HIGH Risk Tables

### 1. `user` (user.rs:9 — `#[table(accessor = user, public)]`)

**Fields:** `user_id`, `email`, `first_name`, `last_name`, `metadata_json`, `created_at`, `updated_at`

**Problem:** This is a **full entity table** (not a result table) marked `public`. Any client connected to SpacetimeDB can query every row — getting all users' PII (email, names, metadata). The reducer functions (`add_user`, `get_user`, `list_users`) call `require_auth`, but that only gates writes — the table itself is directly queryable via SQL with zero auth.

**Exposure:** Full PII for every user. Email + name combo is GDPR/PII-sensitive.

**Fix:** Make `user` table private. Provide a `user_result` table with `caller_identity` scoping (add only the fields the client needs, never `email` unless caller owns the record).

### 2. `user_session_result` (user.rs:24 — `#[table(accessor = user_session_result, public)]`)

**Fields:** `query_id`, `user_id`, `session_id`, `session_name`, `workspace_id`, `created_at`

**Problem:** Results from `get_user_sessions` are written to a single public table with a deterministic `query_id` (`user_sessions:{user_id}`). No `caller_identity` field — any client can enumerate all users' sessions by iterating rows or guessing query_ids.

**Fix:** Add `caller_identity` field. Clear stale rows at reducer start. SDK filters on caller_identity.

### 3. `profile_context_result` (profile_query.rs:16 — `#[table(accessor = profile_context_result, public)]`)

**Fields:** `peer_id`, `static_facts_json`, `dynamic_context_json`, `preferences_json`, `tags_json`, `query_text`

**Problem:** Full peer profile — facts, preferences, dynamic context — written to a public table with no caller scoping. Any client can read any peer's complete profile.

**Fix:** Add `caller_identity` scoping. Filter on reducer-write and SDK-read.

### 4. `user_memory_result` (memory.rs:354 — `#[table(accessor = user_memory_result, public)]`)

**Fields:** `user_scope`, `workspace_id`, `memory_id`, `content`, `summary`, `memory_type`, `confidence`, `is_active`, `created_at`, `tier`

**Problem:** Full memory content written to a public result table. The `user_scope` field is a data attribute, not an access control mechanism — any client can read any user's memories by iterating the table.

**Fix:** Add `caller_identity` scoping. Clear stale results at reducer start.

### 5. `decrypted_memory_result` (crypto.rs:201 — `#[table(accessor = decrypted_memory_result, public)]`)

**Fields:** `caller`, `memory_id`, `content`, `summary`, `confidence`, `memory_type`, `is_active`, `created_at`, `tier`

**Problem:** Result table for the `get_decrypted_memory` reducer. Contains decrypted memory content and summary. Although the reducer clears stale rows for the caller, any connected client can query any row in the table while it exists.

**Fix:** Add `caller_identity` scoping as the reference pattern. The existing `caller` field is data-only — it must be enforced at the SDK query layer.

## MEDIUM Risk Tables

### 5. `query_result` (query.rs:23 — `#[table(accessor = query_result, public)]`)

**Fields:** `query_id`, `table_name`, `row_json`, `created_at`

**Problem:** The generic query transport table. Carries JSON-serialized rows from private tables to clients. Scoped only by `query_id` (a client-generated token) — no server-enforced caller isolation. Query IDs generated with predictable UUID v4 seeds (STDB RNG) could be guessed.

**Fix:** Add `caller_identity` field. Filter all reads to match calling identity.

### 6. `session_step_result` (session.rs:51 — `#[table(accessor = session_step_result, public)]`)

**Fields:** `query_hash`, `session_id`, `workspace_id`, `step_type`, `content`, `summary`, `parent_step_id`, `created_at`

**Problem:** Agent reasoning steps (thoughts, actions, observations) written to a public table with only `query_hash` scoping. Contains full agent reasoning traces.

**Fix:** Add `caller_identity` scoping.

### 7. `hybrid_result` (hybrid_query.rs:22 — `#[table(accessor = hybrid_result, public)]`)

**Fields:** `workspace_id`, `query_hash`, `entity_type`, `entity_id`, `content`, `score`, `strategy`, `context_json`

**Problem:** Search results containing memory/node/peer content + context JSON. Only `query_hash` scoping — no caller isolation.

**Fix:** Add `caller_identity` scoping.

### 8. `session_search_result` (hybrid_query.rs:59 — `#[table(accessor = session_search_result, public)]`)

**Fields:** `query_hash`, `workspace_id`, `session_name`, `score`, `top_memory_id`, `top_memory_content`, `memory_count`

**Problem:** Cross-workspace session search results with full memory content. Only `query_hash` scoping.

**Fix:** Add `caller_identity` scoping.

### 9. `fact_result` (profile.rs:179 — `#[table(accessor = fact_result, public)]`)

**Fields:** `workspace_id`, `query_hash`, `json_data`

**Problem:** Fact query results with `json_data` containing facts about peers. Only `query_hash` scoping.

**Fix:** Add `caller_identity` scoping.

### 10. `change_event_result` (change_event.rs:41 — `#[table(accessor = change_event_result, public)]`)

**Fields:** `since_cursor`, `events_json`, `next_cursor`

**Problem:** `events_json` is a JSON array of ChangeEvent objects — these contain table_name, row JSON, and mutation details for every write in the system. No caller scoping — any client can watch all data changes.

**Fix:** Add `caller_identity` scoping based on workspace membership.

### 11. `tracing_span` (tracing.rs:77 — `#[table(accessor = tracing_span, public)]`)

**Fields:** `operation`, `kind`, `workspace_id`, `duration_micros`, `success`, `error_message`, `caller` (identity hex), `created_at`

**Problem:** Exposes caller identity hex strings and error messages (which can contain sensitive data like internal state, query params, or data excerpts). The `caller` field maps to SpacetimeDB identity — revealing who is calling what. Error messages could leak internal state.

**Fix:** Remove `caller` field from public exposure or obfuscate identity. Sanitize error messages.

### 12. `replication_result` (replication.rs:66 — `#[table(accessor = replication_result, public)]`)

**Fields:** `workspace_id`, `query_type`, `json_data`

**Problem:** Contains replication state in `json_data`. Query type "unsynced" could expose which data hasn't synced. "peers" type lists replication endpoints.

**Fix:** Add `caller_identity` scoping or restrict to admin-only.

### 13. `jwt_signing_key_result` (key_rotation.rs:70 — `#[table(accessor = jwt_signing_key_result, public)]`)

**Fields:** `key_version`, `name`, `key_id`, `is_current`, `is_trusted`, `created_at`, `retired_at`, `expires_at`

**Problem:** Public result table for signing key metadata. Reducers are admin-gated (`require_admin`), but the table itself is public — any client can query all rows directly via SQL. Exposes key rotation state, key IDs, and versioning information.

**Fix:** Make table private, or add `caller_identity` scoping so only the admin caller sees their own query results.

### 14. `key_rotation_event` (key_rotation.rs:364 — `#[table(accessor = key_rotation_event, public)]`)

**Fields:** `event_type`, `detail`, `created_at`

**Problem:** Event log for key rotation actions. `detail` field contains human-readable descriptions of key registration, revocation, and purge operations — could leak internal state and operational patterns.

**Fix:** Add `caller_identity` scoping or restrict via admin-only result table.

### 15. `jwk_set_result` (key_rotation.rs:377 — `#[table(accessor = jwk_set_result, public)]`)

**Fields:** `payload` (full JWK Set JSON), `created_at`

**Problem:** Public result table containing the full JWK Set of trusted signing keys. The reducer is admin-gated but the table is directly queryable by any client.

**Fix:** Although JWK public keys are inherently non-secret, the table should still be admin-scoped for consistency. Make private or add caller identity enforcement.

## LOW Risk Tables (acceptable as-is or minor concerns)

These tables expose aggregate, operational, workspace-scoped, or structural data. They are safe in their current form.

| Table | File | Purpose | Notes |
|-------|------|---------|-------|
| `api_key_result` | auth.rs:46 | API key metadata | Has `caller_identity` — **reference pattern** |
| `admin_list_result` | auth.rs:567 | Admin list | Admin-only reducer, acceptable |
| `space_member_result` | workspace.rs:456 | Space membership | Workspace-scoped |
| `workspace_context_result` | workspace.rs:126 | Workspace context string | Scoped to workspace |
| `workspace_memory_stats_result` | workspace.rs:471 | Memory usage stats | Aggregate |
| `context_directory` | context_directory.rs:14 | Directory tree structure | Workspace-scoped |
| `directory_result` | context_directory.rs:32 | Directory query results | Workspace-scoped |
| `directory_memory_link` | context_directory.rs:51 | Dir→memory links | Workspace-scoped |
| `directory_content_result` | profile_query.rs:45 | Directory content listing | Workspace-scoped |
| `peer_summary_result` | profile_query.rs:32 | Peer activity aggregates | Aggregate counts only |
| `memory_tag_result` | tag.rs:185 | Memory→tag mappings | Tag metadata |
| `delta_pack` | context_delta.rs:18 | Context delta patches | Workspace-scoped |
| `pagerank_result` | knowledge_graph.rs:642 | PageRank centrality | Computational |
| `edge_history_result` | knowledge_graph.rs:387 | Edge change history | Workspace-scoped |
| `citation_result` | knowledge_graph.rs:1072 | Memory citations | Cross-reference metadata |
| `graph_traversal_result` | graph_traversal.rs:9 | BFS/DFS traversal | Workspace-scoped |
| `shortest_path_result` | graph_traversal.rs:26 | Shortest path | Workspace-scoped |
| `bridge_result` | graph_traversal.rs:279 | Bridge detection | Workspace-scoped |
| `kg_stats_result` | graph_traversal.rs:442 | KG aggregate stats | Aggregate |
| `peer_reputation` | memory_feedback.rs:54 | Peer reputation scores | Intentional public |
| `memory_recommendation` | memory_feedback.rs:391 | Memory quality recs | Workspace-scoped |
| `god_node` | hybrid_query.rs:45 | Hub nodes by degree | Workspace-scoped computational |
| `maintenance_schedule` | consolidation.rs:639 | Scheduled maintenance | Required by scheduled reducer |
| `proxy_metrics_snapshot` | proxy_metrics.rs:16 | Proxy usage metrics | Operational data |

## Reference Pattern: `api_key_result`

The `api_key_result` table (auth.rs:46) demonstrates the correct pattern for public result tables:

```rust
pub struct ApiKeyResult {
    pub id: String,
    pub api_key_id: String,
    pub workspace_id: String,
    pub name: String,
    pub permissions: String,
    pub is_active: bool,
    pub created_at: i64,
    pub last_used_at: i64,
    pub caller_identity: String,  // ctx.sender().to_hex()
    pub operation: String,
    pub request_id: String,
}
```

The SDK filters queries by `caller_identity` to enforce per-caller isolation. **All HIGH and MEDIUM risk result tables should follow this pattern.**

## The `caller_identity` Fix Pattern

For each high/medium risk result table, the fix is:
1. Add `caller_identity: String` field to the struct
2. In the reducer, set `caller_identity = ctx.sender().to_hex()`
3. Clear stale rows for the caller at reducer start
4. In the SDK, filter queries by both query_id and caller_identity

This is a low-risk, non-breaking schema addition — it adds granular access control without changing the public contract. Stale-row cleanup at reducer start prevents unbounded growth.

## Priority Remediation

| Priority | Table | Effort | Impact |
|----------|-------|--------|--------|
| **P0** | `workspace_encryption_key` | Make private | **Prevents total encryption bypass** |
| **P0** | `user` | Make private + create caller-scoped result table | Prevents PII exposure |
| **P1** | `query_result` | Add caller_identity | Closes the generic data leak |
| **P1** | `change_event_result` | Add caller_identity | Prevents change-watching |
| **P1** | `decrypted_memory_result` | Add caller_identity | Protects decrypted memory content |
| **P2** | `profile_context_result` | Add caller_identity | Protects peer profiles |
| **P2** | `user_memory_result` | Add caller_identity | Protects user-scoped memories |
| **P3** | `tracing_span` | Remove/obfuscate `caller` field | Reduces identity leakage |
| **P3** | `session_step_result` | Add caller_identity | Protects agent reasoning |
| **P3** | `hybrid_result` | Add caller_identity | Protects search results |
| **P3** | `jwt_signing_key_result` | Make private or add caller_identity | Protects key rotation metadata |
| **P3** | `jwk_set_result` | Make private or add caller_identity | Scopes JWK set to admin |
| **P4** | `fact_result` | Add caller_identity | Protects fact data |
| **P4** | `session_search_result` | Add caller_identity | Protects session search |
| **P4** | `replication_result` | Add caller_identity | Protects replication state |
| **P4** | `user_session_result` | Add caller_identity | Protects session enumeration |
| **P4** | `key_rotation_event` | Add caller_identity or admin-scope | Protects rotation event details |
