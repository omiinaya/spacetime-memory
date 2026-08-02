# STDB Table Privacy Review

**Date:** 2026-07-21
**Scope:** All `#[table]` annotated structs in `server/spacetimedb/src/`
**Total tables discovered:** 107 tables (57 without `public`, 50 with `public`)

---

## Classification Legend

| Category | Meaning | Risk |
|----------|---------|------|
| **PRIVATE** | World-readable by default, should only be visible to workspace members | 🔴 High |
| **QUERY_RESULT** | Result tables that accumulate per-query output — need cleanup or limited visibility | 🟠 Medium |
| **PUBLIC (intentional)** | Intentionally world-readable for discovery/monitoring purposes | 🟢 Low |
| **INTERNAL** | System tables that shouldn't be exposed at all (auth keys, encryption keys, etc.) | 🔴 Critical |
| **SYSTEM** | Operational tables that store system config / state needed across the app | 🟡 Medium |

---

## Full Table Inventory

### 1. Core Entity Tables (PRIVATE — should be workspace-scoped)

| # | Table | Module | Accessor | Fields (sensitive?) |
|---|-------|--------|----------|---------------------|
| 1 | `Workspace` | `workspace.rs:13` | `workspace` | name, description, settings |
| 2 | `Memory` | `memory.rs:18` | `memory` | content, summary, embedding — **highly sensitive** |
| 3 | `MemoryRevision` | `memory.rs:144` | `memory_revision` | prior memory content — **sensitive** |
| 4 | `Message` | `message.rs:13` | `message` | content (text/tool_call/tool_result) — **sensitive** |
| 5 | `Session` | `session.rs:11` | `session` | workspace context — **sensitive** |
| 6 | `SessionParticipant` | `session.rs:26` | `session_participant` | peer linkage |
| 7 | `AgentStep` | `session.rs:36` | `agent_step` | chain-of-thought, tool calls — **highly sensitive** |
| 8 | `Document` | `document.rs:13` | `document` | document content — **sensitive** |
| 9 | `DocChunk` | `document.rs:33` | `doc_chunk` | chunked content — **sensitive** |
| 10 | `Peer` | `peer.rs:12` | `peer` | user/agent identity — **sensitive (PII)** |
| 11 | `Profile` | `profile.rs:11` | `profile` | peer profile data — **sensitive (PII)** |
| 12 | `Fact` | `profile.rs:161` | `fact` | static/dynamic facts about peers — **sensitive (PII)** |
| 13 | `User` | `user.rs:11` | `user` | user record — **sensitive (PII)** |
| 14 | `Insight` | `insight.rs:12` | `insight` | reasoning results |
| 15 | `MentalModel` | `insight.rs:85` | `mental_model` | higher-level abstractions |
| 16 | `KgNode` | `knowledge_graph.rs:12` | `kg_node` | entity data |
| 17 | `KgEdge` | `knowledge_graph.rs:41` | `kg_edge` | relationships |
| 18 | `KgCommunity` | `knowledge_graph.rs:74` | `kg_community` | graph cluster |
| 19 | `HierarchyCluster` | `knowledge_graph.rs:846` | `hierarchy_cluster` | dendrogram data |
| 20 | `CommunityHierarchy` | `knowledge_graph.rs:858` | `community_hierarchy` | dendrogram relationships |
| 21 | `Citation` | `knowledge_graph.rs:1088` | `citation` | source citations |
| 22 | `Tag` | `tag.rs:11` | `tag` | tag metadata |
| 23 | `MemoryTag` | `tag.rs:24` | `memory_tag` | tag associations |
| 24 | `Note` | `note.rs:13` | `note` | markdown content — **sensitive** |
| 25 | `NoteRevision` | `note.rs:41` | `note_revision` | version history — **sensitive** |
| 26 | `NoteBacklink` | `note.rs:87` | `note_backlink` | wikilink relationships |
| 27 | `NoteBlock` | `note.rs:122` | `note_block` | parsed blocks |
| 28 | `BlockReference` | `note.rs:150` | `block_reference` | block-level references |
| 29 | `SearchIndex` | `retrieval.rs:16` | `search_index` | vector embeddings + content — **highly sensitive** |
| 30 | `TermIndex` | `retrieval.rs:216` | `term_index` | keyword index — **sensitive** |
| 31 | `EntityLink` | `entity_linking.rs:10` | `entity_link` | canonical entity mapping |
| 32 | `SpacePermission` | `workspace.rs:32` | `space_permission` | workspace access control |
| 33 | `ConnectorConfig` | `connector.rs:11` | `connector_config` | external connector config |
| 34 | `Subscription` | `subscription.rs:15` | `subscription` | webhook/callback config |
| 35 | `HarmonicBelief` | `harmonic_belief.rs:13` | `harmonic_belief` | belief state |
| 36 | `ResonanceLog` | `harmonic_belief.rs:156` | `resonance_log` | belief events |
| 37 | `RippleImpact` | `ripple.rs:20` | `ripple_impact` | downstream impact tracking |
| 38 | `MemoryFeedback` | `memory_feedback.rs:12` | `memory_feedback` | user feedback -> PII about who gave what feedback |
| 39 | `WorkspaceConfig` | `memory_feedback.rs:32` | `workspace_config` | trust scoring config |
| 40 | `MergeSuggestion` | `consolidation.rs:155` | `merge_suggestion` | pending merge operations |
| 41 | `ConsolidationLog` | `consolidation.rs:11` | `consolidation_log` | system operations |
| 42 | `Tour` | `tour.rs:9` | `tour` | onboarding tour |
| 43 | `TourStop` | `tour.rs:21` | `tour_stop` | onboarding step |
| 44 | `ChangeEvent` | `change_event.rs:21` | `change_event` | data change tracking |
| 45 | `ContextPack` | `context_compression.rs:13` | `context_pack` | compressed context cache |
| 46 | `Account` | `auth.rs:14` | `account` | user account — **critical PII** |
| 47 | `ApiKey` | `auth.rs:31` | `api_key` | API keys — **critical secrets** |
| 48 | `RateLimitEntry` | `auth.rs:138` | `rate_limit_entry` | rate limiting state |

### 2. Result / Query Output Tables (QUERY_RESULT — transient, should be cleaned up)

| # | Table | Module | Fields | Risk |
|---|-------|--------|--------|------|
| 1 | **`query_result`** *(GenericQueryResult)* | `query.rs:25` | Per-query output with `query_token` isolation. Doc explicitly mentions this prevents cross-tenant leaks. | 🟡 OK |
| 2 | **`hybrid_result`** *(HybridResult)* | `hybrid_query.rs:25` | Fused multi-strategy search results — contains memory content snippets | 🔴 **High** |
| 3 | **`entity_extraction_result`** *(EntityExtractionResult)* | `entity_extraction.rs:347` | Extracted entities from a query — may contain raw data | 🔴 **High** |
| 4 | **`decrypted_memory_result`** *(DecryptedMemoryResult)* | `crypto.rs:418` | **Decrypted plaintext memory content** — extremely sensitive | 🔴 **Critical** |
| 5 | **`session_step_result`** *(SessionStepResult)* | `session.rs:54` | Agent step results — contains chain-of-thought | 🔴 **High** |
| 6 | **`user_session_result`** *(UserSessionResult)* | `user.rs:26` | User session list | 🟠 Medium |
| 7 | **`user_get_result`** *(UserGetResult)* | `user.rs:43` | Single/multi user lookup results — **PII** | 🔴 **High** |
| 8 | **`user_memory_result`** *(UserMemoryResult)* | `memory.rs:507` | User-scoped memory content — Mem0 parity, contains `content` field | 🔴 **High** |
| 9 | **`fact_result`** *(FactResult)* | `profile.rs:181` | Profile facts | 🟠 Medium |
| 10 | **`directory_result`** *(DirectoryResult)* | `context_directory.rs:36` | Directory query results | 🟡 Low |
| 11 | **`directory_memory_link`** *(DirectoryMemoryLink)* | `context_directory.rs:55` | Memory-to-directory links | 🟡 Low |
| 12 | **`context_directory`** *(ContextDirectory)* | `context_directory.rs:18` | Directory tree itself | 🟡 Low |
| 13 | **`directory_content_result`** *(DirectoryContentResult)* | `profile_query.rs:47` | Recursive directory content | 🟠 Medium |
| 14 | **`edge_history_result`** *(EdgeHistoryResult)* | `knowledge_graph.rs:417` | Edge version history | 🟡 Low |
| 15 | **`pagerank_result`** *(PagerankResult)* | `knowledge_graph.rs:672` | Graph ranking - safe | 🟢 Low |
| 16 | **`citation_result`** *(CitationResult)* | `knowledge_graph.rs:1102` | Citation query results | 🟡 Low |
| 17 | **`graph_traversal_result`** *(GraphTraversalResult)* | `graph_traversal.rs:11` | BFS/DFS traversal | 🟡 Low |
| 18 | **`shortest_path_result`** *(ShortestPathResult)* | `graph_traversal.rs:28` | Pathfinding | 🟡 Low |
| 19 | **`bridge_result`** *(BridgeResult)* | `graph_traversal.rs:281` | Bridge score results | 🟡 Low |
| 20 | **`kg_stats_result`** *(KgStatsResult)* | `graph_traversal.rs:444` | KG statistics - safe | 🟢 Low |
| 21 | **`subscription_list_result`** *(SubscriptionListResult)* | `subscription.rs:34` | Subscription listing | 🟡 Low |
| 22 | **`workspace_context_result`** *(WorkspaceContextResult)* | `workspace.rs:129` | Workspace context — may contain sensitive content | 🟠 Medium |
| 23 | **`space_member_result`** *(SpaceMemberResult)* | `workspace.rs:707` | Member list — **exposes who is in workspace** | 🔴 **High** |
| 24 | **`workspace_memory_stats_result`** *(WorkspaceMemoryStatsResult)* | `workspace.rs:722` | Memory stats — aggregate, low risk | 🟢 Low |
| 25 | **`profile_context_result`** *(ProfileContextResult)* | `profile_query.rs:18` | Profile query context | 🟠 Medium |
| 26 | **`peer_summary_result`** *(PeerSummaryResult)* | `profile_query.rs:34` | Peer aggregated summary — **PII aggregation** | 🔴 **High** |
| 27 | **`memory_tag_result`** *(MemoryTagResult)* | `tag.rs:187` | Tag query results | 🟡 Low |
| 28 | **`memory_insert_result`** *(MemoryInsertResult)* | `memory.rs:215` | Insert confirmation token | 🟢 Low |
| 29 | **`ripple_impact_result`** *(RippleImpactResult)* | `ripple.rs:43` | Ripple impact query | 🟡 Low |
| 30 | **`stale_nodes_result`** *(StaleNodesResult)* | `ripple.rs:374` | Stale KG nodes | 🟡 Low |
| 31 | **`backlink_result`** *(BacklinkResult)* | `note.rs:104` | Wikilink backlink query | 🟡 Low |
| 32 | **`delta_pack`** *(DeltaPack)* | `context_delta.rs:21` | Delta compressed context | 🟠 Medium |
| 33 | **`change_event_result`** *(ChangeEventResult)* | `change_event.rs:41` | Change event listing | 🟡 Low |
| 34 | **`replication_result`** *(?)* | `replication.rs:66` | Replication query result | 🟠 Medium |
| 35 | **`admin_list_result`** *(AdminListResult)* | `auth.rs:1219` | Admin listing — **highly sensitive (exposes privileged users)** | 🔴 **High** |
| 36 | **`api_key_result`** *(ApiKeyResult)* | `auth.rs:48` | API key query — **critical secrets exposure** | 🔴 **Critical** |
| 37 | **`api_key_verification_result`** *(ApiKeyVerificationResult)* | `auth.rs:76` | API key verification — **critical** | 🔴 **Critical** |
| 38 | **`jwt_signing_key_result`** *(?)* | `key_rotation.rs:148` | JWT keys — **critical** | 🔴 **Critical** |
| 39 | **`key_rotation_event`** *(?)* | `key_rotation.rs:665` | Key rotation events | 🟠 Medium |
| 40 | **`jwk_set_result`** *(?)* | `key_rotation.rs:678` | JWK set | 🔴 **Critical** |
| 41 | **`peer_reputation`** *(PeerReputation)* | `memory_feedback.rs:57` | Peer reputation scores | 🟠 Medium |
| 42 | **`peer_reputation_result`** *(PeerReputationResult)* | `memory_feedback.rs:511` | Reputation query result | 🟠 Medium |
| 43 | **`memory_recommendation`** *(MemoryRecommendation)* | `memory_feedback.rs:394` | Memory recommendations | 🟠 Medium |
| 44 | **`workspace_directory`** *(DirectoryEntry)* | `workspace_directory.rs:31` | Entity directory index — exposes what entities exist in a workspace | 🟠 Medium |

### 3. Public Infrastructure / Monitoring Tables (PUBLIC — intentionally world-readable)

| # | Table | Module | Purpose |
|---|-------|--------|---------|
| 1 | `tracing_span` *(TracingSpan)* | `tracing.rs:79` | Operation traces for dashboard |
| 2 | `embedder_metrics_snapshot` | `embedder_metrics.rs:18` | Embedder health metrics |
| 3 | `proxy_metrics_snapshot` | `proxy_metrics.rs:18` | Proxy health metrics |
| 4 | `embedder_alert` | `embedder_alert.rs:30` | Embedder alert events |
| 5 | `tantivy_alert` | `tantivy_alert.rs:28` | Tantivy alert events |
| 6 | `god_node` | `hybrid_query.rs:48` | Hub nodes (entity IDs only) |

### 4. Internal Index Tables (PUBLIC but should be PRIVATE)

| # | Table | Module | Why |
|---|-------|--------|-----|
| 1 | `entity_search_index` | `hybrid_query.rs:92` | Performance index exposing entity↔search_index mapping — exposes which entities have embeddings |
| 2 | `entity_term_index` | `hybrid_query.rs:111` | Performance index exposing entity↔term mapping — exposes entity keyword associations |
| 3 | `node_edge_index` | `hybrid_query.rs:130` | Performance index exposing node↔edge mapping — exposes graph connectivity |
| 4 | `session_search_result` | `hybrid_query.rs:143` | Cross-workspace session search results — **exposes session data across boundaries** |
| 5 | `workspace_index` | `hybrid_query.rs:69` | Workspace-level search index status |
| 6 | `workspace_encryption_key` | `crypto.rs:26` | AES keys — doc literally says "was public until the 2026-07-17 audit: any client could read every workspace's AES key via SQL" — **was recently fixed** |
| 7 | `jwt_signing_key` | `key_rotation.rs:116` | JWT signing key — **should never be public** |

---

## 🔴 Priority-Ranked Risk Assessment

### **IMMEDIATE (P0) — Fix within days**

| Priority | Table | Risk | Why |
|----------|-------|------|-----|
| **P0** | `decrypted_memory_result` | 🔴🔴 | Exposes **decrypted plaintext** memory content to any SQL reader. This completely defeats encryption-at-rest. |
| **P0** | `user_memory_result` | 🔴🔴 | User-scoped memory content is world-readable — the entire "user isolation" feature is nullified if any client can `SELECT * FROM user_memory_result`. |
| **P0** | `entity_extraction_result` | 🔴🔴 | Raw entity extraction output is world-readable. Could leak everything extracted from a session. |
| **P0** | `hybrid_result` | 🔴🔴 | Contains fused search results with memory content snippets across workspaces. |
| **P0** | `api_key_result` / `api_key_verification_result` | 🔴🔴 | Exposes API key data to any unauthenticated SQL reader. |
| **P0** | `jwt_signing_key_result` / `jwk_set_result` | 🔴🔴 | Exposes JWT signing material. |

### **HIGH (P1) — Fix within a week**

| Priority | Table | Risk | Why |
|----------|-------|------|-----|
| **P1** | `session_step_result` | 🔴 | Agent chain-of-thought + tool calls world-readable |
| **P1** | `user_get_result` | 🔴 | User PII exposed |
| **P1** | `user_session_result` | 🔴 | User-session mapping exposed |
| **P1** | `session_search_result` | 🔴 | Cross-workspace session search leaks data across boundaries |
| **P1** | `peer_summary_result` | 🔴 | Aggregated PII from profiles/insights/sessions |
| **P1** | `space_member_result` | 🔴 | Exposes workspace membership |
| **P1** | `admin_list_result` | 🔴 | Exposes privileged users |
| **P1** | `workspace_directory` | 🟠 | Exposes complete entity inventory per workspace |

### **MEDIUM (P2) — Fix within a sprint**

| Priority | Table | Risk | Why |
|----------|-------|------|-----|
| **P2** | `entity_search_index` | 🟠 | Exposes entity↔embedding mapping |
| **P2** | `entity_term_index` | 🟠 | Exposes entity↔keyword mapping |
| **P2** | `node_edge_index` | 🟠 | Exposes graph structure |
| **P2** | `workspace_index` | 🟠 | Exposes workspace search state |
| **P2** | `profile_context_result` | 🟠 | Profile context — may contain PII |
| **P2** | `delta_pack` | 🟠 | Delta compressed context |
| **P2** | `peer_reputation` / `peer_reputation_result` | 🟠 | Reputation scores expose feedback patterns |
| **P2** | `memory_recommendation` | 🟠 | Recommendations based on memory content |
| **P2** | `replication_result` | 🟠 | Replication details |
| **P2** | `fact_result` | 🟠 | Profile facts — potentially PII |

### **LOW (P3) — Low risk, stable**

| Priority | Table | Risk | Why |
|----------|-------|------|-----|
| **P3** | `directory_result` | 🟡 | Directory tree structure — low sensitivity |
| **P3** | `directory_memory_link` | 🟡 | File→memory links |
| **P3** | `context_directory` | 🟡 | Directory tree itself |
| **P3** | `pagerank_result` | 🟢 | Aggregate graph stats |
| **P3** | `kg_stats_result` | 🟢 | Aggregate |
| **P3** | `memory_insert_result` | 🟢 | Just a token |
| **P3** | `god_node` | 🟢 | Just entity IDs |
| **P3** | All `_result` tables not listed above | 🟢 | Already transient or low-sensitivity |

---

## Key Vulnerability Patterns

### Pattern 1: `public` + sensitive fields = data leaks
Almost every table marked `public` has **zero per-table access control**. Any client that can connect to SpacetimeDB can `SELECT * FROM any_public_table`. The `query_token` pattern used in `query_result` is good — it isolates per-query output — but most result tables don't use it.

### Pattern 2: Result tables that never get cleaned up
Result tables like `hybrid_result`, `entity_extraction_result`, and `session_step_result` accumulate data. If the reducer that writes them doesn't also **clear** previous results (or scope them by session/workspace), stale sensitive data persists indefinitely.

### Pattern 3: Crypto keys exposed (recently fixed but worth verifying)
`workspace_encryption_key` was public until <3 days ago. `decrypted_memory_result` is still public. The crypto layer may still be leaky.

### Pattern 4: Index tables that reconstruct entity data
`entity_search_index`, `entity_term_index`, `node_edge_index` are performance indexes that an attacker could use to reconstruct relationships between entities without querying the actual entity tables.

---

## Recommended Actions (ordered by impact)

1. **Immediately audit all `#[table(accessor = ..., public)]` annotations** — every table with `public` needs a documented justification. The default for new tables should be **private** (no `public` keyword).

2. **Implement query_token isolation on all result tables** — the pattern used by `query_result` (per-caller filter token) should be the standard for all `*_result` tables.

3. **Add cleanup to result-table reducers** — every reducer that writes to a result table should also delete stale rows (old results for the same query hash, or rows older than TTL).

4. **Remove `public` from crypto-adjacent tables** — `decrypted_memory_result`, `api_key_result`, `api_key_verification_result`, `jwt_signing_key_result`, `jwk_set_result` should never be public.

5. **Make workspace-scoped entity tables private by default** — `memory`, `message`, `session`, `agent_step`, `note`, `document`, `peer`, `profile`, `user`, `insight`, `mental_model` should all emit a warning if found to be public (most are already private, verified good).

6. **Future: investigate SpacetimeDB per-table row-level security** — if STDB supports filter predicates per-connection, that's the ideal solution for workspace-scoped views.

---

## Tables Already Private (explicitly marked without `public`) ✅

These are already correct:
`session`, `session_participant`, `agent_step`, `peer`, `user`, `profile`, `fact`, `insight`, `mental_model`, `workspace`, `space_permission`, `subscription`, `connector_config`, `message`, `memory`, `memory_revision`, `kg_node`, `kg_edge`, `kg_community`, `hierarchy_cluster`, `community_hierarchy`, `citation`, `tag`, `memory_tag`, `entity_link`, `search_index`, `term_index`, `note`, `note_revision`, `note_backlink`, `note_block`, `block_reference`, `account`, `api_key`, `rate_limit_entry`, `ripple_impact`, `context_pack`, `consolidation_log`, `merge_suggestion`, `memory_feedback`, `workspace_config`, `harmonic_belief`, `resonance_log`, `tour`, `tour_stop`, `change_event`, `workspace_encryption_key`, `jwt_signing_key`, `document`, `doc_chunk`

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Total tables | 107 |
| Private (no `public` keyword) | 57 |
| Public (`public` keyword) | 50 |
| — Core entity tables **should be private** | ~45 |
| — Query result tables **need TTL/cleanup** | ~44 |
| — Intentionally public (monitoring) | 6 |
| — **Critical risk (P0)** | 7 |
| — **High risk (P1)** | 5 |
| — **Medium risk (P2)** | 11 |
| — **Low risk (P3)** | ~21 |

---


---

## Update (July 21, 2026) — Privacy Enforcement Implemented ✅

All 8 P0-critical result tables have had `public` removed and their names added
to the `ALLOWED_TABLES` whitelist in `query.rs`. The SDKs now use `_query()` to
access them through the `query_table` reducer, which enforces auth + workspace
access scoping.

### Changes made:
- **Rust**: Removed `public` from `decrypted_memory_result`, `user_memory_result`,
  `hybrid_result`, `entity_extraction_result`, `api_key_result`,
  `api_key_verification_result`, `jwt_signing_key_result`, `jwk_set_result`
- **Rust**: Added all 8 table names to `ALLOWED_TABLES` in `query.rs`
- **Python SDK**: Switched 6 `_sql()` calls to `_query()` across search, memories,
  workspace-keys, and admin modules
- **TypeScript SDK**: Switched 7 `_sqlExec()` calls to `_query()` in client.ts
- **Bug fix**: Python `get_decrypted_memory()` now actually reads the result table
  (previously called the reducer but returned only the status dict)
- **Test fix**: Zep adapter test mock now handles `query_table` → `query_result`
  pipeline

## Update (July 21, 2026) — P1 Table Privacy Enforced ✅

All 8 P1-critical result tables have had `public` removed and their names added
to the `ALLOWED_TABLES` whitelist in `query.rs`. This extends the P0 enforcement
pattern to cover the next tier of sensitive tables.

### P1 tables enforced:
| Table | Module | Risk | SDK changes |
|-------|--------|------|-------------|
| `session_step_result` | `session.rs` | Agent CoT + tool calls | 2 × Python, 0 × TS |
| `user_session_result` | `user.rs` | User-session mapping | 3 × Python, 1 × TS |
| `user_get_result` | `user.rs` | User PII | 4 × Python, 2 × TS |
| `session_search_result` | `hybrid_query.rs` | Cross-workspace session leaks | 2 × Python, 1 × TS |
| `peer_summary_result` | `profile_query.rs` | Aggregated PII | No SDK refs (just Rust) |
| `space_member_result` | `workspace.rs` | Workspace membership | 1 × Python, 0 × TS |
| `admin_list_result` | `auth.rs` | Privileged user exposure | 1 × Python, 0 × TS |
| `workspace_directory` | `workspace_directory.rs` | Entity inventory | No SDK refs (just Rust) |

### Changes made:
- **Rust**: Removed `public` from all 8 P1 table definitions
- **Rust**: Added all 8 names to `ALLOWED_TABLES` in `query.rs`
- **Python SDK**: Converted 13 `_sql()` calls to `_query()` across 6 files
  (agent_orchestrator.py, cli.py, sdks/zep.py, client.py, _workspaces.py,
  _memories_search.py)
- **TypeScript SDK**: Converted 4 `_sqlExec()` calls to `_query()` in client.ts

### Remaining public tables (P2+):
- Internal index tables: `entity_search_index`, `entity_term_index`,
  `node_edge_index`, `workspace_index` — P2 (less sensitive, performance trade-offs)
- `session_search_result` already done (see above)
- `space_member_result` already done (see above)
- Intentional monitoring tables (6): `tracing_span`, `embedder_metrics_snapshot`,
  `proxy_metrics_snapshot`, `embedder_alert`, `tantivy_alert`, `god_node` — P3

### Remaining risk:
- **hybrid_result** uses `query_hash` as a filter, not a primary key — linear scan
  of the table on every search. Acceptable for now; a dedicated reducer with
  btree-indexed lookup would perform better.
- **decrypted_memory_result** still stores plaintext content. The best fix (STDB
  response-bearing reducers) is not yet available.
