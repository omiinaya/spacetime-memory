# Table Privacy Audit

> **Date:** 2026-07-05
> **Scope:** All SpacetimeDB tables in spacetime-memory server module
> **Total tables:** 84 (49 private + 35 public)

## Summary

| Risk Level | Count | Tables |
|-----------|-------|--------|
| **HIGH** | 4 | `user`, `user_session_result`, `profile_context_result`, `user_memory_result` |
| **MEDIUM** | 5 | `query_result`, `fact_result`, `session_step_result`, `hybrid_result`, `session_search_result` |
| **LOW** | 26 | All others — acceptable as-is or minor concerns |

## HIGH Risk Tables

### 1. `user` (user.rs:9 — `#[table(accessor = user, public)]`)

**Fields exposed:** `user_id`, `email`, `first_name`, `last_name`, `metadata_json`, `created_at`, `updated_at`

**Problem:** This is a **full entity table** marked `public` — not a result table. Any authenticated client that connects to SpacetimeDB can query every row via the STDB client SDK, getting all users' PII. The reducers (`add_user`, `get_user`, `list_users`) all call `require_auth` but that doesn't matter — the table itself is public and can be queried directly.

**Recommendation:** Make `user` private and use the `query_table` generic endpoint (which enforces auth + workspace access) instead. Or add a scoped result table (like `api_key_result` with `caller_identity`).

### 2. `user_session_result` (user.rs:24 — `#[table(accessor = user_session_result, public)]`)

**Fields exposed:** `query_id`, `user_id`, `session_id`, `session_name`, `workspace_id`, `created_at`

**Problem:** The `get_user_sessions` reducer writes all results for **any user** into a single public table keyed by `query_id`. Any client can query the table directly and enumerate all users' sessions by iterating rows. The `query_id` is deterministic (`user_sessions:{user_id}`) and easily guessable — there is no caller_identity filter.

**Recommendation:** Add `caller_identity` field (from `ctx.sender().to_hex()`) and filter queries in the SDK to only return rows matching the caller. Clear stale result rows at the start of the reducer.

### 3. `profile_context_result` (profile_query.rs:16 — `#[table(accessor = profile_context_result, public)]`)

**Fields exposed:** `id`, `peer_id`, `static_facts_json`, `dynamic_context_json`, `preferences_json`, `tags_json`, `query_text`, `created_at`

**Problem:** Full peer profile data — static facts, dynamic context, preferences, tags — written to a public table with **no caller_identity scoping**. Any client can read any peer's complete profile. The associated reducers do call `require_auth`, but the result table has no access control.

**Recommendation:** Add `caller_identity` field and filter in the SDK. Clear stale results at reducer start.

### 4. `user_memory_result` (memory.rs:348 — `#[table(accessor = user_memory_result, public)]`)

**Fields exposed:** `id`, `user_scope`, `workspace_id`, `memory_id`, `content`, `summary`, `memory_type`, `confidence`, `is_active`, `created_at`, `tier`

**Problem:** Memory content written to a public result table. The `user_scope` field is meant for per-user isolation, but **any client can read any user's memories** by querying the result table directly. The `user_scope` is just a data field, not an access control mechanism.

**Recommendation:** Add `caller_identity` field and filter in the SDK. Clear stale results at reducer start.

## MEDIUM Risk Tables

### 5. `query_result` (query.rs:23 — `#[table(accessor = query_result, public)]`)

**Fields exposed:** `id`, `query_id`, `table_name`, `row_json`, `created_at`

**Problem:** This is the **generic query result table** that transports data from private tables to clients. The `query_id` token scoping mechanism relies on clients generating unpredictable tokens. If one client can guess (or brute-force) another client's `query_id`, they can read their query results. The `query_id` is generated client-side, not server-enforced as a secret.

**Recommendation:** add `caller_identity` (`ctx.sender().to_hex()`) to `GenericQueryResult` and filter all reads to match the calling identity. This provides server-enforced isolation regardless of query_id randomness.

### 6. `fact_result` (profile.rs:171 — `#[table(accessor = fact_result, public)]`)

**Fields exposed:** `id`, `workspace_id`, `query_hash`, `json_data`, `created_at`

**Problem:** All fact query results (from list_facts/search_facts reducers) are written to a single public table with only `query_hash` for scoping. No caller_identity means any client can iterate results.

**Recommendation:** Add `caller_identity` scoping.

### 7. `session_step_result` (session.rs:51 — `#[table(accessor = session_step_result, public)]`)

**Fields exposed:** `id`, `query_id`, `session_id`, `workspace_id`, `agent_action`, `observation`, `thought`, `step_number`, `created_at`

**Problem:** Agent actions, observations, and thoughts written to a public table with only `query_id` scoping. Contains the full agent reasoning trace.

**Recommendation:** Add `caller_identity` scoping.

### 8. `hybrid_result` (hybrid_query.rs:22 — `#[table(accessor = hybrid_result, public)]`)

**Fields exposed:** `id`, `query_id`, `workspace_id`, `json_data`, `created_at`

**Problem:** Hybrid search results containing memory/note/KG data in `json_data`. Only `query_id` scoping.

**Recommendation:** Add `caller_identity` scoping.

### 9. `session_search_result` (hybrid_query.rs:59 — `#[table(accessor = session_search_result, public)]`)

**Fields exposed:** `id`, `query_id`, `workspace_id`, `json_data`, `created_at`

**Problem:** Session search results with only `query_id` scoping.

**Recommendation:** Add `caller_identity` scoping.

## LOW Risk Tables (acceptable as-is)

These tables expose operational/aggregate/workspace-scoped data and are safe:

| Table | Purpose | Notes |
|-------|---------|-------|
| `api_key_result` | API key metadata (caller-scoped) | Has `caller_identity` — **good design, reference pattern** |
| `admin_list_result` | Admin list | Admin-only reducer, acceptable |
| `tracing_span` | Performance tracing | Operational data |
| `pagerank_result` | PageRank scores | Computational |
| `citation_result` | Memory citations | Cross-references |
| `kg_stats_result` | KG statistics | Aggregate |
| `workspace_context_result` | Workspace context | Workspace-scoped |
| `workspace_memory_stats_result` | Memory stats | Aggregate |
| `peer_summary_result` | Peer activity counts | Aggregate |
| `directory_content_result` | Directory listing | Workspace-scoped |
| `directory_result` | Directory query results | Workspace-scoped |
| `directory_memory_link` | Dir→memory links | Workspace-scoped |
| `memory_tag_result` | Tag→memory mapping | Tag metadata |
| `context_directory` | Directory structure | Workspace-scoped |
| `delta_pack` | Context delta patches | Workspace-scoped |
| `maintenance_schedule` | Scheduled maintenance | Required by scheduled reducer |
| `peer_reputation` | Reputation scores | Intentional public share |
| `memory_recommendation` | Memory quality recs | Workspace-scoped |
| `god_node` | Central KG node | Single node |
| `change_event_result` | Change event logs | Workspace-scoped |
| `proxy_metrics_snapshot` | Proxy metrics | Operational |
| `replication_result` | Replication status | Workspace-scoped |
| `space_member_result` | Space membership | Workspace-scoped (add caller_identity recommended) |
| `edge_history_result` | Edge change history | Workspace-scoped |
| `graph_traversal_result` | Graph traversal | Workspace-scoped |
| `shortest_path_result` | Shortest path | Workspace-scoped |
| `bridge_result` | Bridge detection | Workspace-scoped |

## Reference Pattern: `api_key_result`

The `api_key_result` table (auth.rs:44) demonstrates the correct pattern for public result tables:

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
}
```

The SDK filters queries by `caller_identity` to enforce per-caller isolation. **All high and medium risk result tables should follow this pattern.**

## Pattern: The `caller_identity` Fix

For each high/medium risk result table, the fix is:

1. Add `caller_identity: String` field to the struct
2. In the reducer, set `caller_identity = ctx.sender().to_hex()`
3. Clear stale rows for the caller's previous query_id at the start of the reducer
4. In the SDK, filter queries by both `query_id` and `caller_identity`

This is a low-risk, non-breaking change — it only adds granularity to what was always possible (the table was already public). It prevents cross-tenant leakage without changing the public schema contract.
