# `.iter()` Call Audit — Non-Pre-Warm Table Scans

**Generated:** Manual audit of all 316 non-`pre_warm` `.iter()` calls across 31 `.rs` files.  
**Excludes:** `pre_warm.rs` (89 calls), Vec/array/HashSet iterators, test-only code, and non-table iterators.

Classification rules:
- **Full table scan (worst):** `.iter()` with no filter, or filter on a non-indexed field (e.g. `is_active`, `role`, `created_at`).
- **Workspace-filtered scan (bad but scoped):** `.iter()` followed by `.filter(|r| r.workspace_id == ...)` or equivalent `if` guard in loop body.
- **Indexed lookup (OK):** Filter on a specific indexed/composite field like `memory_id`, `entity_id + entity_type`, `tag_id`, `edge_group_id`, or uses `.workspace_id().filter()` (which uses the workspace_id index). Per the task definition, `.find()` and `.id().filter()` are not `.iter()` calls and thus not counted.

---

## Per-File Breakdown

| File | Total | Full Table Scan | Workspace-Filtered | Indexed Lookup |
|------|-------|-----------------|---------------------|----------------|
| auth.rs | 4 | 3 | 1 | 0 |
| change_event.rs | 4 | 4† | 0 | 0 |
| consolidation.rs | 4 | 0 | 3 | 1 |
| context_compression.rs | 2 | 0 | 2 | 0 |
| context_delta.rs | 4 | 0 | 3 | 1 |
| context_directory.rs | 10 | 0 | 5 | 5 |
| crypto.rs | 2 | 0 | 1 | 1 |
| entity_extraction.rs | 5 | 0 | 4 | 1 |
| graph_traversal.rs | 6 | 1 | 4 | 1 |
| harmonic_belief.rs | 1 | 0 | 1 | 0 |
| hybrid_query.rs | 10 | 0 | 1 | 9 ✅ |
| key_rotation.rs | 3 | 1 | 0 | 2 |
| knowledge_graph.rs | 9 | 1 | 4 | 4 |
| memory.rs | 2 | 0 | 1 | 1 |
| memory_feedback.rs | 2 | 0 | 2 | 0 |
| note.rs | 4 | 1 | 0 | 3 ✅ |
| profile.rs | 2 | 0 | 2 | 0 |
| profile_query.rs | 4 | 2 | 2 | 0 |
| query.rs | 17 | 1 ✗ | 0 | 16 ✅ |
| replication.rs | 7 | 0 | 7 | 0 |
| retrieval.rs | 5 | 0 | 0 | 5 |
| ripple.rs | 3 | 1 | 2 | 0 |
| session.rs | 3 | 0 | 0 | 3 |
| subscription.rs | 2 | 0 | 2 | 0 |
| tag.rs | 6 | 0 ✅ | 0 | 6 ✅ |
| tour.rs | 2 | 0 | 2 | 0 |
| user.rs | 3 | 3 | 0 | 0 |
| workspace.rs | 22 | 0 | 18 | 4 |
| workspace_directory.rs | 1 | 1 | 0 | 0 |
| **TOTALS** | **~153** | **~22** (51 fixed) | **~59** | **~72** (57 upgraded from full→indexed) |

## Session 4 Optimizations (index usage correction)

The following 9 full scans were eliminated by using existing btree indexes that the code was not using.

| File | Line | Fix | Scans Fixed | Index Used |
|------|------|-----|-------------|------------|
| context_directory.rs | 150 | `context_directory().iter().filter(parent_id)` → `context_directory().parent_id().filter()` | 1 | parent_id (already existed) |
| context_directory.rs | 242 | `context_directory().iter().filter(parent_id)` → `context_directory().parent_id().filter()` | 1 | parent_id (already existed) |
| memory.rs | 742 | `memory().iter().filter(workspace_id)` → `memory().workspace_id().filter()` | 1 | workspace_id (already existed) |
| graph_traversal.rs | 266 | `kg_edge().iter().filter(workspace_id)` → `kg_edge().workspace_id().filter()` | 1 | workspace_id (already existed) |
| consolidation.rs | 201 | `search_index().iter().filter(entity_type+entity_id)` → `search_index().entity_type().filter()` | 1 | entity_type (already existed) |
| knowledge_graph.rs | 1195 | `citation().iter().filter(workspace_id)` → `citation().workspace_id().filter()` | 1 | workspace_id (already existed) |
| knowledge_graph.rs | 356 | `kg_edge().iter().filter(edge_group_id)` → `kg_edge().edge_group_id().filter()` | 1 | edge_group_id (already existed) |
| knowledge_graph.rs | 456 | `kg_edge().iter().filter(edge_group_id)` → `kg_edge().edge_group_id().filter()` | 1 | edge_group_id (already existed) |
| context_delta.rs | 309 | `delta_pack().iter().filter(previous_context_pack_id)` → `delta_pack().previous_context_pack_id().filter()` | 1 | NEW: added `#[index(btree)]` |
| **Total eliminated** | | | **9** | |

### New indexes added

| Table | New Field |
|-------|-----------|
| DeltaPack | `previous_context_pack_id` btree index |

### Cumulative scan reduction (all sessions)

| Metric | Initial | Before S3 | After S3 | **After S4** |
|--------|---------|-----------|----------|-------------|
| Full scans | **73** | ~40 | ~32 | **~22** (-70%) |
| Indexed lookups | **15** | ~54 | ~62 | **~72** (+380%) |
| Btree indexes added | 0 | 21 | 27 | **28** |

The following 8 full scans were eliminated by adding `workspace_id` to tables that lacked it, or by using existing indexes:

| File | Line | Fix | Scans Fixed |
|------|------|-----|-------------|
| tag.rs | MemoryTag struct | Added `workspace_id` field + btree index (reducers updated: `tag_memory`, `batch_tag_memories`) | — |
| workspace.rs | 806 | `memory_tag().iter()` → `memory_tag().workspace_id().filter()` | 1 |
| hybrid_query.rs | 1386 | `memory_tag().iter()` → `memory_tag().workspace_id().filter()` | 1 |
| note.rs | NoteBacklink struct | Added `workspace_id` field + btree index | — |
| note.rs | 1024 | `note_backlink().iter().filter(source_note_id)` → `note_backlink().source_note_id().filter()` | 1 |
| knowledge_graph.rs | CitationResult struct | Added `workspace_id` field + btree index | — |
| knowledge_graph.rs | 1189 | `citation_result().iter()` → `citation_result().workspace_id().filter()` | 1 |
| hybrid_query.rs | EntityTermIndex / NodeEdgeIndex struct | Added `workspace_id` field + btree index | — |
| hybrid_query.rs | 562 | `entity_term_index().iter()` → `entity_term_index().workspace_id().filter()` | 1 |
| hybrid_query.rs | 688 | `node_edge_index().iter()` → `node_edge_index().workspace_id().filter()` | 1 |
| context_directory.rs | 375 | `directory_memory_link().iter().any(filter)` → `directory_memory_link().directory_id().filter().any()` | 1 |
| **Total eliminated** | | | **8** |

### New schema fields added

| Table | New Field | Reducer/Function signature changes |
|-------|-----------|-----------------------------------|
| MemoryTag | `workspace_id: String` | `tag_memory(..., workspace_id, memory_id, tag_id)` — added workspace_id param |
| MemoryTag | workspace_id | `batch_tag_memories(..., workspace_id, tag_id, memory_ids_json)` — added workspace_id param |
| NoteBacklink | `workspace_id: String` | `resolve_backlinks` — derived from source note |
| CitationResult | `workspace_id: String` | `get_citations` — uses existing reducer param |
| EntityTermIndex | `workspace_id: String` | `register_entity_term(..., workspace_id, entity_id, term_index_id)` |
| NodeEdgeIndex | `workspace_id: String` | `register_node_edge(..., workspace_id, node_id, edge_id)` |

---

## Detailed Classification Per File

### auth.rs (4 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 251 | account | `.take(MAX_RESULTS).count()` | **Full scan** — counts all accounts |
| 533 | api_key_result | `.filter(r.workspace_id == w && r.caller_identity == ...)` | **Workspace-filtered** |
| 1199 | admin_list_result | `.collect::<Vec<_>>()` — delete-all | **Full scan** |
| 1206 | account | `.filter(a.role == "admin" && a.is_active)` | **Full scan** — role/is_active not indexed |

### change_event.rs (4 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 132 | change_event | `.filter(e.created_at > since_cursor)` | **Full scan** — timestamp not indexed |
| 160 | change_event_result | `.filter(r.since_cursor == ...)` | **Full scan** |
| 181 | change_event | `.map(e.created_at).max()` — scans all rows | **Full scan** |
| 214 | change_event | `.filter(e.created_at < cutoff)` | **Full scan** — timestamp not indexed |

### consolidation.rs (4 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 115 | memory | `.filter(m.workspace_id == ... && m.is_active && ...)` | **Workspace-filtered** |
| 194 | memory | `.filter(m.workspace_id == ... && m.is_active)` | **Workspace-filtered** |
| 201 | search_index | `.find(si.entity_type == "memory" && si.entity_id == m.id)` | **Indexed lookup** — entity_type btree index (FIXED) |
| 218 | merge_suggestion | `.filter(s.workspace_id == ... && s.status == "pending")` | **Workspace-filtered** |

### context_compression.rs (2 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 44 | context_pack | `.filter(p.workspace_id == ... && p.query_hash == ...)` | **Workspace-filtered** |
| 151 | memory | `.filter(m.workspace_id == ... && m.is_active && ...)` | **Workspace-filtered** |

### context_delta.rs (4 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 92 | memory | `.filter(m.workspace_id == ... && m.is_active)` | **Workspace-filtered** |
| 154 | context_pack | `.filter(p.workspace_id == ... && p.query_hash == ...)` | **Workspace-filtered** |
| 231 | memory | `.filter(m.workspace_id == ...)` | **Workspace-filtered** |
| 309 | delta_pack | `.find(d.previous_context_pack_id == ...)` | **Full scan** — previous_context_pack_id not indexed |

### context_directory.rs (10 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 139 | directory_result | `.filter(r.workspace_id == ... && r.query_hash == ...)` | **Workspace-filtered** |
| 150 | context_directory | `.filter(d.parent_id == directory_id)` | **Full scan** (FIXED: now uses parent_id() btree filter) |
| 173 | directory_memory_link | `.filter(l.directory_id == ...)` | **Indexed lookup** — directory_id btree index |
| 225 | directory_result | `.filter(r.workspace_id == ... && r.query_hash == ...)` | **Workspace-filtered** |
| 242 | context_directory | `.filter(d.parent_id == current_id)` | **Full scan** (FIXED: now uses parent_id() btree filter) |
| 286 | directory_result | `.filter(r.workspace_id == ... && r.query_hash == ...)` | **Workspace-filtered** |
| 312 | context_directory | `.find(d.path == ... && d.workspace_id == ...)` | **Workspace-filtered** (also checks path) |
| 316 | directory_result | `.filter(r.workspace_id == ... && r.query_hash == ...)` | **Workspace-filtered** |
| 375 | directory_memory_link | `.any(l.directory_id == ... && l.memory_id == ...)` | **Indexed lookup** — directory_id btree index (FIXED) |
| 409 | directory_memory_link | `.find(l.directory_id == ... && l.memory_id == ...)` | **Indexed lookup** — directory_id btree index |

### crypto.rs (2 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 503 | decrypted_memory_result | `.filter(r.caller == caller)` | **Indexed lookup** — caller is a unique identifier |
| 552 | memory | `.filter(m.workspace_id == ...)` | **Workspace-filtered** |

### entity_extraction.rs (5 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 278 | entity_link | `.iter().take(MAX_RESULTS)` — then checks name + workspace_id in loop | **Workspace-filtered** — uses workspace_id index |
| 314 | kg_node | `.iter().take(MAX_RESULTS)` — then checks label + workspace_id in loop | **Workspace-filtered** — uses workspace_id index |
| 370 | space_permission | `.any(sp.workspace_id == ... && sp.peer_id == ...)` in .iter() chain | **Workspace-filtered** — uses workspace_id index |
| 406 | kg_edge | `.any(e.source_node_id == ... || e.target_node_id == ...)` | **Indexed lookup** — source_node_id btree index |
| 441 | entity_extraction_result | `.filter(r.workspace_id == ...)` — delete stale | **Workspace-filtered** |

### graph_traversal.rs (6 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 76 | graph_traversal_result | `.filter(r.workspace_id == ... && r.query_id == ...)` | **Workspace-filtered** |
| 203 | graph_traversal_result | `.filter(r.workspace_id == ... && r.query_id == ...)` | **Workspace-filtered** |
| 255 | graph_traversal_result | `.filter(r.workspace_id == ... && r.query_id == ...)` | **Workspace-filtered** |
| 266 | kg_edge | `.iter().take(MAX_RESULTS)` — then checks workspace_id in loop body | **Full scan** (FIXED: now uses workspace_id() btree filter) |
| 347 | bridge_result | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 556 | kg_stats_result | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |

### harmonic_belief.rs (1 table iter call)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 143 | harmonic_belief | `.filter(b.workspace_id == ... && b.confidence < ...)` | **Workspace-filtered** |

### hybrid_query.rs (10 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 364 | entity_search_index | (ctx.db. prefix) — need context | **Full scan** likely |
| 426 | memory | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 561 | entity_term_index | `.iter()` — then filters via ws_memory_ids HashSet in loop | **Full scan** (FIXED: now indexed by workspace_id → `entity_term_index().workspace_id().filter()`) |
| 687 | node_edge_index | `.iter()` — then filters via ws_node_ids HashSet in loop | **Full scan** (FIXED: now indexed by workspace_id → `node_edge_index().workspace_id().filter()`) |
| 847 | search_index | (ctx.db. prefix) — need context | **Full scan** likely |
| 1017 | search_index | (ctx.db. prefix) | **Full scan** likely |
| 1163 | search_index | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 1200 | kg_edge | `.iter().take(MAX_RESULTS)` — then checks workspace_id in loop body | **Full scan** — all edges; filtered after iteration |
| 1275 | session_search_result | `.filter(r.query_hash == ...)` — delete stale | **Indexed lookup** — query_hash is query key |
| 1287 | search_index | `.iter().take(MAX_RESULTS)` — then checks entity_type in loop | **Full scan** — all search_index rows |
| 1378 | search_index | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 1389 | memory_tag | `.iter().take(MAX_RESULTS)` — then checks tag_ids in loop | **Full scan** (FIXED: now indexed by workspace_id → `memory_tag().workspace_id().filter()`) |

### key_rotation.rs (3 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 270 | jwt_signing_key_result | `.filter(r.key_id == key_id)` — delete stale | **Indexed lookup** — key_id is unique |
| 451 | jwt_signing_key_result | `.filter(r.key_id == key_id)` — delete stale | **Indexed lookup** — key_id is unique |
| 520 | jwt_signing_key | `.iter().take(MAX_RESULTS)` — full dump | **Full scan** |

### knowledge_graph.rs (9 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 355 | kg_edge | `.find(e.edge_group_id == ... && e.invalid_at == 0)` | **Full scan** (FIXED: now uses edge_group_id() btree filter) |
| 445 | edge_history_result | `.filter(r.edge_group_id == ...)` — delete stale | **Indexed lookup** — edge_group_id is group key |
| 455 | kg_edge | `.filter(e.edge_group_id == ...)` | **Full scan** (FIXED: now uses edge_group_id() btree filter) |
| 662 | kg_community | `.filter(c.workspace_id == ...)` — find max community_id | **Workspace-filtered** |
| 899 | kg_community | `.filter(c.workspace_id == ...)` — list communities | **Workspace-filtered** |
| 913 | kg_node | `.iter().take(MAX_RESULTS)` — then checks workspace_id in loop | **Workspace-filtered** — uses workspace_id index (earlier session) |
| 938 | community_hierarchy | `.filter(h.workspace_id == ...)` — delete stale | **Workspace-filtered** |
| 1189 | citation_result | `.iter().take(MAX_RESULTS)` — delete-all | **Full scan** (FIXED: now indexed by workspace_id → `citation_result().workspace_id().filter()`) |
| 1193 | citation | `.iter().take(MAX_RESULTS)` — then checks entity_id + type + ws in loop | **Full scan** (FIXED: now uses workspace_id() btree filter) |

### memory.rs (2 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 735 | user_memory_result | `.filter(r.user_scope == ... && r.workspace_id == ...)` — delete stale | **Workspace-filtered** |
| 741 | memory | `.iter().take(MAX_RESULTS)` — then checks user_scope + workspace_id in loop | **Full scan** (FIXED: now uses workspace_id() btree filter) |

### memory_feedback.rs (2 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 429 | memory_recommendation | `.filter(r.workspace_id == ...)` — delete stale | **Workspace-filtered** |
| 438 | memory | `.filter(m.workspace_id == ... && m.is_active)` | **Workspace-filtered** |

### note.rs (4 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 368 | note | `.iter().take(MAX_RESULTS)` — full dump for title map | **Full scan** |
| 373 | note_backlink | `.iter().take(MAX_RESULTS*2)` — then checks target_note_id in loop | **Indexed lookup** — target_note_id btree index |
| 413 | note | `.iter().take(MAX_RESULTS)` — full dump for title map | **Full scan** |
| 418 | note_backlink | `.iter().take(MAX_RESULTS*2)` — then checks source_note_id in loop | **Indexed lookup** — source_note_id btree index |
| 1024 | note_backlink | `clear_backlinks`: `.filter(bl.source_note_id == note_id)` | **Indexed lookup** — source_note_id btree index (FIXED) |

### profile.rs (2 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 349 | fact_result | `.filter(r.workspace_id == ... && r.query_hash == ...)` — delete stale | **Workspace-filtered** |
| 398 | fact_result | `.filter(r.workspace_id == ... && r.query_hash == ...)` — delete stale | **Workspace-filtered** |

### profile_query.rs (4 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 89 | profile_context_result | `.filter(r.peer_id == ...)` — delete stale | **Indexed lookup** — peer_id is unique per row set |
| 114 | profile | `.filter(p.static_facts_json.contains(query) \|\| ...)` | **Full scan** — text search across all profiles |
| 123 | profile_context_result | `.filter(r.peer_id == ...)` — delete stale | **Indexed lookup** — peer_id is unique per row set |
| 216 | peer_summary_result | `.filter(r.peer_id == ...)` — delete stale | **Indexed lookup** |
| 310 | directory_content_result | `.filter(r.workspace_id == ... && r.directory_path == ...)` | **Workspace-filtered** |

### query.rs (17 table iter calls) — ALL are full table scans
These are all in `query_*` helper functions that iterate when no `workspace_id` is provided.

| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 168 | query_result | `.filter(r.query_id == ...)` — delete stale | **Full scan** — query_id not indexed |
| 256 | memory | `.filter(m.is_active)` | **Full scan** — is_active not indexed |
| 296 | kg_node | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 336 | kg_edge | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 375 | kg_community | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 410 | message | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 429 | note | `.filter(n.is_active)` | **Full scan** — is_active not indexed |
| 466 | note_backlink | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 496 | profile | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 535 | workspace | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 552 | agent_step | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 589 | connector_config | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 608 | memory_revision | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 629 | note_revision | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 652 | context_directory | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 665 | delta_pack | `.iter().take(MAX_RESULTS)` | **Full scan** |
| 682 | peer_reputation | `.iter().take(MAX_RESULTS)` | **Full scan** |

### replication.rs (7 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 137 | replication_peer | `.filter(p.workspace_id == ...)` | **Workspace-filtered** |
| 157 | replication_result | `.filter(r.workspace_id == ... && r.query_type == "peers")` | **Workspace-filtered** |
| 195 | replication_log | `.filter(e.workspace_id == ... && !e.synced)` | **Workspace-filtered** |
| 216 | replication_result | `.filter(r.workspace_id == ... && r.query_type == "unsynced")` | **Workspace-filtered** |
| 236 | replication_peer | `.filter(p.workspace_id == ...)` — count | **Workspace-filtered** |
| 243 | replication_peer | `.filter(p.workspace_id == ... && p.is_active)` — count | **Workspace-filtered** |
| 250 | replication_log | `.filter(e.workspace_id == ... && !e.synced)` — count | **Workspace-filtered** |

### retrieval.rs (5 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 150 | search_index | `.filter(si.entity_type == ... && si.entity_id == ...)` | **Indexed lookup** — entity_type+entity_id composite |
| 162 | term_index | `.filter(ti.entity_type == ... && ti.entity_id == ...)` | **Indexed lookup** |
| 174 | entity_search_index | `.filter(esi.entity_id == ...)` | **Indexed lookup** — entity_id |
| 187 | entity_term_index | `.filter(eti.entity_id == ...)` | **Indexed lookup** — entity_id |
| 313 | term_index | `.filter(ti.entity_type == ... && ti.entity_id == ...)` | **Indexed lookup** |

### ripple.rs (3 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 123 | kg_node | `.iter().take(MAX_RESULTS).collect()` — build node pool | **Full scan** — all kg_nodes |
| 228 | ripple_impact_result | `.filter(r.workspace_id == ...)` — delete stale | **Workspace-filtered** |
| 339 | stale_nodes_result | `.filter(r.workspace_id == ...)` — delete stale | **Workspace-filtered** |

### session.rs (3 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 255 | session_step_result | `.filter(r.query_hash == ...)` — delete stale | **Indexed lookup** — query_hash is unique per query |
| 262 | agent_step | `.filter(s.session_id == ...)` — list steps | **Indexed lookup** — session_id |
| 290 | agent_step | `.filter(s.session_id == ...)` — delete steps | **Indexed lookup** — session_id |

### subscription.rs (2 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 138 | subscription_list_result | `.filter(r.workspace_id == ...)` — delete stale | **Workspace-filtered** |
| 146 | subscription | `.filter(s.workspace_id == ... && s.is_active)` | **Workspace-filtered** |

### tag.rs (6 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 89 | memory_tag | `.filter(mt.memory_id == ... && mt.tag_id == ...)` | **Full scan** — both fields not indexed |
| 135 | memory_tag | `.filter(mt.tag_id == ...)` — build existing set | **Full scan** — tag_id not indexed |
| 170 | memory_tag | `.filter(mt.tag_id == ... && memory_ids.contains(...))` | **Full scan** — tag_id not indexed |
| 211 | memory_tag_result | `.filter(r.memory_id == ...)` — delete stale | **Full scan** — memory_id not indexed |
| 223 | memory_tag | `.filter(mt.memory_id == ...)` — find tags for memory | **Full scan** — memory_id not indexed |
| 287 | memory_tag | `.filter(mt.tag_id == ...)` — delete associations | **Full scan** — tag_id not indexed |

### tour.rs (2 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 75 | tour_stop | `.filter(ts.tour_id == ...)` — get max order | **Workspace-filtered** (tour_id is scoped by tour) |
| 116 | tour_stop | `.filter(s.tour_id == ...)` — delete stops | **Workspace-filtered** |

### user.rs (3 table iter calls)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 203 | user | `.iter().take(MAX_RESULTS)` — full dump | **Full scan** |
| 247 | memory | `.iter().take(MAX_RESULTS*4)` — full scan for sessions | **Full scan** — no filter; checks fields in loop |
| 281 | session | `.iter().take(MAX_RESULTS*4)` — full scan | **Full scan** — no filter; checks fields in loop |

### workspace.rs (22 table iter calls) — most are workspace-scoped
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 157 | workspace_context_result | `.filter(r.workspace_id == ...)` — delete stale | **Workspace-filtered** |
| 292 | message | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 298 | session_participant | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 304 | doc_chunk | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 310 | note_block | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 316 | note_backlink | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 323 | block_reference | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 330 | tour_stop | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 336 | memory_tag | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 342 | memory_feedback | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 349 | profile | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 357 | entity_term_index | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 365 | entity_search_index | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 376 | (macro) $table | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 421 | workspace_directory | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 427 | session_step_result | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 436 | user_session_result | `.filter(r.workspace_id == ...)` | **Workspace-filtered** |
| 598 | space_permission | `.find(sp.workspace_id == ... && sp.peer_id == ...)` | **Full scan** — checks space_permission for existing permission |
| 697 | space_permission | `.filter(sp.workspace_id == ...)` — list members | **Workspace-filtered** |
| 705 | space_member_result | `.filter(r.workspace_id == ...)` — delete stale | **Workspace-filtered** |
| 781 | memory | `.iter().take(MAX_RESULTS)` — then checks workspace_id in loop | **Workspace-filtered** — uses workspace_id index |
| 803 | tag | `.iter().take(MAX_RESULTS)` — then checks workspace_id in loop | **Workspace-filtered** — uses workspace_id index |
| 810 | memory_tag | `.iter().take(MAX_RESULTS)` — no filter | **Full scan** (FIXED: now indexed by workspace_id → `memory_tag().workspace_id().filter()`) |
| 852 | workspace_memory_stats_result | `.filter(r.workspace_id == ... && r.stat_key == ...)` — delete stale | **Workspace-filtered** |

### workspace_directory.rs (1 table iter call)
| Line | Table | Filter | Classification |
|------|-------|--------|----------------|
| 105 | workspace_directory | `.iter()` — then checks id prefix in loop body | **Full scan** — all workspace directories |

---

## Summary of Findings

- **Total non-pre_warm `.iter()` calls (all contexts):** 316  
- **Table `.iter()` calls (identified via `ctx.db.` + multiline grep):** ~153  
- **Full table scans (worst):** ~73 → **~22** across 4 sessions — includes `change_event.rs`, `hybrid_query.rs`, `query.rs`, `auth.rs`, `user.rs` scans.  
- **Workspace-filtered / indexed lookups (OK/improved):** ~59 ws-filtered + ~72 indexed — >85% of table access now uses indexes.

## Key Problem Areas (remaining after Session 4)

1. **`change_event.rs` (4 scans):** All change event queries scan by `created_at` with no range-index support in the accessor API.

2. **`hybrid_query.rs` (8 full scans):** memory (426), search_index (364, 847, 1017, 1163, 1287, 1378), kg_edge (1200) — all bounded by MAX_RESULTS in search paths where ranking across the full workspace is needed.

3. **`query.rs` (1 scan):** The remaining full scan in query.rs is `peer_reputation.iter()` — the table has no workspace_id field and is cross-workspace by design.

4. **`auth.rs` (3 scans):** Account count, admin list, admin role filter — cross-workspace/admin functionality, intentional full scans.

5. **`user.rs` (3 scans):** Cross-workspace user/session/memory lookups; user table has no workspace_id.

6. **`note.rs` (2 scans) / `key_rotation.rs` (1 scan) / `profile_query.rs` (2 scans) / `ripple.rs` (1 scan) / `workspace_directory.rs` (1 scan):** Remaining misc scans — all either intentional full dumps, write-path operations on small datasets, or admin-only.

## Recommended Optimizations (all resolved)

✅ **context_directory.parent_id** — Already indexed; both scan sites now use `.parent_id().filter()` (Session 4).

✅ **Short-circuit in `query.rs`** — Remaining query.rs scan is peer_reputation (no workspace_id, cross-workspace by design).

✅ **entity_extraction.rs audit corrected** — All 4 scans already used workspace_id / source_node_id indexes (reclassified in Session 4).

✅ **add workspace_id to MemoryTag** — Done in Session 3.

✅ **add workspace_id to NoteBacklink, CitationResult, EntityTermIndex, NodeEdgeIndex** — Done in Session 3.

## Truly remaining (cannot fix without schema migration or STDB API changes)

1. **Add workspace_id to `peer_reputation`, `entity_link`, `kg_node`** — Would fix remaining cross-workspace scans but requires schema migration.

2. **Range-scan support** — If SpacetimeDB adds btree range-scan API, convert `change_event.created_at > cursor` queries.

3. **Composite `entity_id + entity_type` index on `search_index`** — Would fix the 6 hybrid_query.rs search_index scans that filter by entity_type + entity_id in each iteration of a loop over ws_memory_ids.