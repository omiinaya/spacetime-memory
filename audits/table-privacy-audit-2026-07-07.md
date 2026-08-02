# Table Privacy Audit — 2026-07-07

**Scope**: All SpacetimeDB tables marked `public` in the spacetime-memory module.
**Claim**: 25 public tables — **Actual count: 50 public tables**.
**Auditor**: Task worker da4da85bc9ca4e77

## Methodology

Each `#[table(accessor = X, public)]` annotation in `server/spacetimedb/src/` was reviewed for:
1. What data the struct fields expose
2. Whether the data is sensitive (PII, secrets, internal structure)
3. Whether the `public` designation is architecturally necessary (result-table pattern with correlation-key auth) vs genuinely unprotected
4. The risk of data leakage through subscription-based access

## Summary

| Risk Level | Count | Tables |
|------------|-------|--------|
| CRITICAL   | 1     | workspace_encryption_key |
| HIGH       | 12    | user, query_result, decrypted_memory_result, user_memory_result, hybrid_result, session_search_result, memory_recommendation, delta_pack, fact_result, change_event_result, replication_result, profile_context_result |
| MODERATE   | 14    | session_step_result, api_key_result, api_key_verification_result, admin_list_result, space_member_result, user_session_result, peer_reputation, tracing_span, directory_memory_link, entity_extraction_result, backlink_result, workspace_index, entity_search_index, entity_term_index, node_edge_index |
| LOW         | 11    | context_directory, directory_result, workspace_directory, workspace_context_result, workspace_memory_stats_result, peer_summary_result, directory_content_result, god_node, edge_history_result, pagerank_result, citation_result, bridge_result, kg_stats_result, memory_tag_result, graph_traversal_result, shortest_path_result, peer_reputation_result, proxy_metrics_snapshot, jwt_signing_key_result, jwk_set_result, key_rotation_event, maintenance_schedule |

## Complete List of Public Tables (50 total)

### Legend
- **PII**: Personal identifiable information (email, name, identity hex)
- **Secrets**: Cryptographic material (keys, hashes, tokens)
- **Content**: Full memory/note/step content (the core data store)
- **Index**: Entity IDs, workspace mappings, structural lookups
- **Meta**: Non-sensitive operational metadata

| # | Table | File:Line | Fields Exposed | Risk | Notes |
|---|-------|-----------|----------------|------|-------|
| 1 | `user` | user.rs:9 | email, first_name, last_name, metadata_json | **HIGH** | No correlation-key protection. Any client can enumerate all users. |
| 2 | `user_session_result` | user.rs:24 | user_id, session_id, workspace_id | MODERATE | query_id-scoped. |
| 3 | `session_step_result` | session.rs:51 | content (agent reasoning), summary, step_type | MODERATE | query_hash-scoped, but content is sensitive. |
| 4 | `context_directory` | context_directory.rs:14 | name, path, parent_id, description | LOW | Directory structure — intentional. |
| 5 | `directory_result` | context_directory.rs:32 | entity_id, name, path, depth | LOW | Query results for directory operations. |
| 6 | `directory_memory_link` | context_directory.rs:51 | memory_id ↔ directory_id mapping | MODERATE | Reveals which memory is in which directory. |
| 7 | `tracing_span` | tracing.rs:77 | caller (identity hex), operation, error_message | MODERATE | Leaks caller identity per operation. Error messages may contain stack traces. |
| 8 | `fact_result` | profile.rs:179 | json_data (profile fact content) | **HIGH** | query_hash-scoped, but full fact data in json_data. |
| 9 | `workspace_directory` | workspace_directory.rs:29 | entity_id, workspace_id, entity_type | LOW | Entity index — meta only. |
| 10 | `edge_history_result` | knowledge_graph.rs:393 | edge metadata, version history | LOW | Graph history — low sensitivity. |
| 11 | `pagerank_result` | knowledge_graph.rs:648 | node_label, rank, iteration | LOW | Graph analysis output. |
| 12 | `citation_result` | knowledge_graph.rs:1078 | entity_id, source_memory_id | LOW | Citation mapping. |
| 13 | `entity_extraction_result` | entity_extraction.rs:311 | entities_json (extracted entity names) | MODERATE | Exposes what entities were found. |
| 14 | `graph_traversal_result` | graph_traversal.rs:9 | node_label, depth, path_json | LOW | Graph traversal output. |
| 15 | `shortest_path_result` | graph_traversal.rs:26 | node_label, step_order | LOW | Shortest-path output. |
| 16 | `bridge_result` | graph_traversal.rs:279 | node_label, bridge_score, community_ids | LOW | Bridge analysis. |
| 17 | `kg_stats_result` | graph_traversal.rs:442 | node_count, edge_count, stats | LOW | Aggregate statistics. |
| 18 | `memory_tag_result` | tag.rs:185 | memory_id, tag_name, tag_color | LOW | Memory-to-tag mapping. |
| 19 | `workspace_context_result` | workspace.rs:126 | context (workspace context string) | LOW | Workspace metadata. |
| 20 | `space_member_result` | workspace.rs:470 | peer_id, permission, granted_by | **MODERATE** | Exposes workspace membership. No correlation key. |
| 21 | `workspace_memory_stats_result` | workspace.rs:485 | stat_key, stat_value | LOW | Aggregate stats. |
| 22 | `query_result` | query.rs:23 | row_json (ALL table data across ALL workspaces) | **HIGH** | Master escape hatch. query_id scoping is obscurity — any subscriber can see all rows. |
| 23 | `profile_context_result` | profile_query.rs:16 | static_facts_json, dynamic_context_json, preferences_json, tags_json | **HIGH** | Full peer profile data. query_text-scoped. |
| 24 | `peer_summary_result` | profile_query.rs:32 | peer_id, memory_count, insight_count | LOW | Aggregate. |
| 25 | `directory_content_result` | profile_query.rs:45 | directory_path, memory_ids_json | LOW | Directory listing. |
| 26 | `api_key_result` | auth.rs:47 | api_key_id, name, permissions, scope, caller_identity | MODERATE | Key metadata exposed (not key_hash). |
| 27 | `api_key_verification_result` | auth.rs:75 | api_key_id, permissions, scope, caller_identity | MODERATE | Same as api_key_result. |
| 28 | `admin_list_result` | auth.rs:900 | identity, username, display_name | MODERATE | Exposes admin identities. Any client can enumerate admins. |
| 29 | `change_event_result` | change_event.rs:41 | events_json (full data snapshots of all changes) | **HIGH** | Contains JSON-encoded snapshots of changed records across all tables. |
| 30 | `maintenance_schedule` | consolidation.rs:639 | scheduled_id, scheduled_at | LOW | Scheduler rows. |
| 31 | `delta_pack` | context_delta.rs:18 | new_memories_json (full memory objects) | **HIGH** | Contains complete memory object JSON in delta packs. |
| 32 | `workspace_encryption_key` | crypto.rs:21 | key_hex (64-char hex = 32 bytes raw AES-256 key) | **CRITICAL** | Contains the actual encryption key per workspace. Any client can read ALL encryption keys. |
| 33 | `decrypted_memory_result` | crypto.rs:380 | content, summary, confidence, memory_type | **HIGH** | Literally decrypted memory content. caller-scoped. |
| 34 | `hybrid_result` | hybrid_query.rs:22 | content (full memory/node/peer content), score, context_json | **HIGH** | Search results with full content. query_hash-scoped but public table. |
| 35 | `god_node` | hybrid_query.rs:45 | node_id, edge_count | LOW | Graph analysis. |
| 36 | `workspace_index` | hybrid_query.rs:68 | entity_id, workspace_id, entity_type | MODERATE | Entity-to-workspace mapping — can be used to enumerate workspace contents. |
| 37 | `entity_search_index` | hybrid_query.rs:89 | entity_id, search_index_id | MODERATE | Index mapping. |
| 38 | `entity_term_index` | hybrid_query.rs:108 | entity_id, term_index_id | MODERATE | Index mapping. |
| 39 | `node_edge_index` | hybrid_query.rs:127 | node_id, edge_id | MODERATE | Index mapping. |
| 40 | `session_search_result` | hybrid_query.rs:140 | top_memory_content (full content), session_name, workspace_id | **HIGH** | Cross-workspace session search results with memory content. query_hash-scoped. |
| 41 | `jwt_signing_key_result` | key_rotation.rs:147 | key_version, key_id (fingerprint), is_current, is_trusted | LOW | Signing key metadata (no private key). Intentionally public. |
| 42 | `key_rotation_event` | key_rotation.rs:441 | event_type, detail | LOW | Audit log. |
| 43 | `jwk_set_result` | key_rotation.rs:454 | payload (JWK Set JSON) | LOW | Public keys — intentionally public. |
| 44 | `user_memory_result` | memory.rs:370 | content, summary, memory_type, confidence | **HIGH** | Full memory content. user_scope + caller-scoped, but public table. |
| 45 | `peer_reputation` | memory_feedback.rs:54 | peer_id, reputation_score, feedback counts | MODERATE | PRIMARY table (not a result) — peer identities with reputation scores. |
| 46 | `memory_recommendation` | memory_feedback.rs:391 | content (memory content), trust_score, action | **HIGH** | Memory content exposed with recommendation metadata. |
| 47 | `peer_reputation_result` | memory_feedback.rs:508 | peer_id, reputation_score | LOW | Reputation query results. |
| 48 | `backlink_result` | note.rs:97 | source_note_id, target_note_id, display_text | MODERATE | Note wikilink structure. |
| 49 | `proxy_metrics_snapshot` | proxy_metrics.rs:16 | requests_total, tokens_total, error counts | LOW | Operational metrics. Intentionally public. |
| 50 | `replication_result` | replication.rs:66 | json_data (replication payloads) | **HIGH** | Contains JSON snapshots of replicated data. |

## Detailed Findings

### CRITICAL: `workspace_encryption_key` — Encryption Keys in the Open

**Location**: `server/spacetimedb/src/crypto.rs:21`
**Risk**: Catastrophic
**Detail**: The `WorkspaceEncryptionKey` struct has exactly one important field: `key_hex: String`, which is a 64-character lowercase hex string representing 32 bytes = 256 bits of AES-256-GCM key material. The table's PK is `workspace_id`, so there's one key per workspace. **Any client connected to the SpacetimeDB module can subscribe to this table and obtain the raw encryption key for every workspace.**

This means:

```sql
-- Any client can do this:
SELECT * FROM workspace_encryption_key;
-- Now they have every workspace's AES-256 key.
```

This completely defeats the encryption system. The only protection is that an unauthenticated client can't connect (they need an identity), but ANY authenticated user or API key can read all keys.

**Mitigation**: This table MUST be private. Only the encryption/decryption reducers should access it. Consider using SpacetimeDB's ability to keep tables private and expose key material only through `decrypt_memory` reducers.

### HIGH: `user` — PII Without Any Protection

**Location**: `server/spacetimedb/src/user.rs:9`
**Risk**: High
**Detail**: The `User` struct contains `email`, `first_name`, `last_name`, and `metadata_json`. The table has NO correlation key or access token. **Every connected client sees every user's full PII.**

The comment says `"Public table — clients can query directly"` which suggests this was intentional, but it's a data privacy issue. In systems like Zep (which this appears to be inspired by), the user table should NOT be public.

### HIGH: `query_result` — Universal Data Exfiltration Channel

**Location**: `server/spacetimedb/src/query.rs:23`
**Risk**: High
**Detail**: This is the master proxy for all `query_table` reducer calls. The `row_json` field contains JSON-serialized row data from memory, sessions, profiles, workspaces, notes — essentially every table in the system. The protection is a `query_id` token that the SDK generates and uses as a filter.

However:
1. The table is public — any client can subscribe to `SELECT * FROM query_result` and see ALL rows
2. The `query_id` is a UUID — if the UUID generation is deterministic (as `ctx.rng()` is per-module deterministic), or if query_ids are predictable, an attacker can enumerate them
3. Even with random UUIDs, a determined attacker can collect all rows and extract data by watching the table

**Mitigation**: If the SDK needs to read query results, consider using per-identity result tables or a cleaner approach. At minimum, add a `caller_identity` field and actively filter or clear old rows frequently.

### HIGH: `decrypted_memory_result` — Decrypted Content in the Open

**Location**: `server/spacetimedb/src/crypto.rs:380`
**Risk**: High
**Detail**: The `DecryptedMemoryResult` struct exposes `content` (decrypted memory text), `summary`, `confidence`, `memory_type`, `is_active`, `tier`. The `caller` field is meant to scope results, but the table is public.

### HIGH: Content-Exposing Result Tables (5 tables)

Tables like `hybrid_result`, `session_search_result`, `user_memory_result`, `memory_recommendation`, `delta_pack`, `change_event_result`, `replication_result`, `fact_result`, and `session_step_result` all contain full content strings from memories, profiles, or workspaces. Each relies on a `query_id`/`query_hash`/`caller` correlation key for isolation, but the underlying table is public.

### MODERATE: `space_member_result` — Workspace Membership Exposure

**Location**: `server/spacetimedb/src/workspace.rs:470`
**Risk**: Moderate
**Detail**: Exposes `peer_id`, `permission`, `granted_by` for every workspace member. Any client can enumerate who has access to which workspace and at what permission level.

### MODERATE: `peer_reputation` — Primary Table Public

**Location**: `server/spacetimedb/src/memory_feedback.rs:54`
**Risk**: Moderate
**Detail**: Unlike most public result tables which use the "write-to-public-table-after-reducer" pattern, `peer_reputation` is a **primary data table** that's public. It stores per-peer reputation scores across all workspaces.

### MODERATE: `tracing_span` — Caller Identity Log

**Location**: `server/spacetimedb/src/tracing.rs:77`
**Risk**: Moderate
**Detail**: The `caller` field records the sender identity hex for every traced operation. This provides a complete audit trail of who did what — but accessible to any client. Error messages in `error_message` may also leak internal details.

## Design Pattern Assessment

The project uses a common SpacetimeDB pattern:

1. **Reducer** performs auth-checked work
2. **Reducer** writes results to a public table with a correlation key (query_id, query_hash, caller, etc.)
3. **Client** reads from the public table filtered by that correlation key

This works well when:
- The correlation key is truly random and unguessable
- The client calls a reducer, gets the correlation key, and subscribes with a filtered query

The weakness is:
- The table is still PUBLIC — any client can ignore the correlation key and read everything
- If the correlation key is deterministic (like a username-based hash), enumeration is trivial
- Accumulation: many result tables never clean old rows, so data builds up
- Some tables (`user`, `workspace_encryption_key`, `space_member_result`, `admin_list_result`) have NO correlation key at all

## Recommendations

### Immediate (Critical)

1. **`workspace_encryption_key`**: Make private. No client needs direct access to raw encryption keys. The `encrypt`/`decrypt` reducers mediate access.
   - Approx effort: 2 hours (change `public` to private, update any subscribers)
   
2. **`user`**: Remove PII fields from public exposure, or make the table private with a `get_user` reducer that returns sanitized data.
   - Approx effort: 4 hours (change to private, update SDK clients)

### High Priority

3. **`query_result`**: Add `caller_identity` field, implement cleanup sweeper, or make private and expose through a dedicated reducer. Currently the biggest single-channel data leak.
   - Approx effort: 8 hours

4. **`decrypted_memory_result`**: Make private or add more restrictive cleanup. The entire point is to avoid the overhead of repeated decryption, but having decrypted content sitting in a public table defeats the purpose.

### Medium Priority

5. **`change_event_result`**, **`replication_result`**: These accumulate full data snapshots over time. Add TTL cleanup or make private.

6. **`peer_reputation`**: This is a primary table that shouldn't be public. Make private and expose through a query reducer.

7. **`space_member_result`**, **`admin_list_result`**: Make private or add stricter correlation-key scoping.

### Low Priority (Acceptable as-is)

8. **`jwt_signing_key_result`**, **`jwk_set_result`**: Intentionally public for JWT verification. No action needed.

9. **`proxy_metrics_snapshot`**: Intentionally public for dashboard. No action needed.

10. **Index tables** (`workspace_index`, `entity_search_index`, `entity_term_index`, `node_edge_index`): These expose only entity IDs and index keys, no content. Acceptable.

## Risk Score Overview

| Table | Severity | Likelihood | Overall |
|-------|----------|------------|---------|
| workspace_encryption_key | Critical | Certain (any client can query) | **CRITICAL** |
| user (PII fields) | High | Certain | **HIGH** |
| query_result | High | High (any client can sniff all query traffic) | **HIGH** |
| decrypted_memory_result | High | High | **HIGH** |
| hybrid_result | High | High | **HIGH** |
| session_search_result | High | Medium | **HIGH** |
| user_memory_result | High | High | **HIGH** |
| memory_recommendation | High | Medium | **HIGH** |
| delta_pack | High | Medium | **HIGH** |
| profile_context_result | High | Medium | **HIGH** |
| change_event_result | High | Medium | **HIGH** |
| replication_result | High | Medium | **HIGH** |
| fact_result | High | Medium | **HIGH** |
| space_member_result | Moderate | High | **MODERATE** |
| admin_list_result | Moderate | High | **MODERATE** |
| peer_reputation | Moderate | High | **MODERATE** |
| tracing_span | Moderate | High | **MODERATE** |
| session_step_result | Moderate | Medium | **MODERATE** |
| api_key_result | Moderate | Medium | **MODERATE** |

---

*Generated by task worker da4da85bc9ca4e77 on 2026-07-07.*
