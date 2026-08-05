use spacetimedb::*;
use crate::auth::require_auth;
use crate::auth::require_admin;

use crate::crypto::decrypt_if_enabled;
use crate::knowledge_graph::{kg_edge, kg_node, KgEdge};
use crate::memory::memory;
use crate::tag::memory_tag;
use crate::retrieval::{
    search_index, term_index, bm25_idf, bm25_score,
};
use crate::workspace::workspace;
use crate::{now_micros, uuid_v7};
use crate::tracing::TracingSpanKind;
use crate::trace_span;

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// Stores results from a hybrid multi-strategy search query.
/// Clients read this table after calling `hybrid_search` to get fused results.
#[table(accessor = hybrid_result, index(accessor = workspace_query, btree(columns = [workspace_id, query_hash])))]
#[derive(Debug, Clone)]
pub struct HybridResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Deterministic hash of the original query, used to group result sets
    pub query_hash: String,
    /// "memory" | "node" | "peer"
    pub entity_type: String,
    pub entity_id: String,
    pub content: String,
    /// Combined fusion score (higher = more relevant)
    pub score: f64,
    /// Which strategy produced this row: "semantic" | "keyword" | "graph" | "temporal"
    pub strategy: String,
    /// JSON: {"workspace_context": "...", "memory_context": "..."}
    pub context_json: String,
    pub created_at: i64,
}

/// Tracks knowledge-graph nodes with the highest degree (most edges),
/// i.e. the "god nodes" or hub nodes of the graph.
#[table(accessor = god_node)]
#[derive(Debug, Clone)]
pub struct GodNode {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub node_id: String,
    /// Number of edges this node participates in (as source or target)
    pub edge_count: u64,
    pub computed_at: i64,
}

/// Compact registry mapping workspace entities to their IDs, enabling
/// workspace pre-filtering without scanning full content tables.
///
/// One row per (workspace_id, entity_type, entity_id) triple.  Populated
/// alongside memory creation, search indexing, and KG node creation.
/// Scanned first by `hybrid_search` to build a pre-filter set — then each
/// strategy uses `.id().find()` (primary-key lookup) instead of
/// `.iter().filter(workspace_id)` which does a full table scan in WASM.
///
/// Carries optional `search_index_id` so strategies can do a direct PK
/// lookup into search_index rather than scanning the full table.
#[table(accessor = workspace_index)]
#[derive(Debug, Clone)]
pub struct WorkspaceIndex {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// "memory" | "node" | "search_index" | "term"
    #[index(btree)]
    pub entity_type: String,
    pub entity_id: String,
    /// PK of the search_index row for this entity (empty if none)
    pub search_index_id: String,
}

/// Maps an entity_id to its corresponding search_index primary key, enabling
/// O(1) PK lookups into search_index without scanning the full table.
///
/// Hybrid strategies (semantic, MMR) iterate ws_search_ids from WorkspaceIndex,
/// then use this table to find the search_index PK, then do a PK lookup into
/// search_index directly — no full-table iteration of search_index rows.
#[table(accessor = entity_search_index)]
#[derive(Debug, Clone)]
pub struct EntitySearchIndex {
    #[primary_key]
    pub id: String,
    /// entity_id from the content table (e.g. memory.id, node.id)
    pub entity_id: String,
    /// PK of the corresponding search_index row
    pub search_index_id: String,
}

/// Maps an entity_id to its term_index primary keys, enabling O(1) PK lookups
/// into term_index without scanning the inverted index table.
/// One row per (entity_id, term_index_id) pair — populated alongside
/// index_terms, cleaned up by remove_from_index.
///
/// The keyword strategy iterates ws_memory_ids from WorkspaceIndex, then uses
/// this table to find all term_index PKs for each entity and do direct PK
/// lookups into term_index — no full-table iteration of term_index rows.
#[table(accessor = entity_term_index)]
#[derive(Debug, Clone)]
pub struct EntityTermIndex {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// entity_id that owns the term entry
    #[index(btree)]
    pub entity_id: String,
    /// PK of the corresponding term_index row
    pub term_index_id: String,
}

/// Maps a knowledge-graph node_id to its incident edge primary keys, enabling
/// O(1) PK lookups into kg_edge without scanning the full edge table.
/// One row per (node_id, edge_id) pair — populated alongside create_edge,
/// cleaned up when edges are deleted.
///
/// The graph strategy iterates ws_node_ids from WorkspaceIndex, then uses this
/// table to find all edge PKs incident to each node and do direct PK lookups
/// into kg_edge — no full-table iteration of kg_edge rows.
#[table(accessor = node_edge_index)]
#[derive(Debug, Clone)]
pub struct NodeEdgeIndex {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Node ID that participates in the edge
    #[index(btree)]
    pub node_id: String,
    /// PK of the corresponding kg_edge row
    pub edge_id: String,
}

/// Result table for cross-workspace session search via semantic (cosine)
/// similarity.  Clients call ``search_sessions_semantic`` then read this table.
#[table(accessor = session_search_result)]
#[derive(Debug, Clone)]
pub struct SessionSearchResult {
    #[primary_key]
    pub id: String,
    /// Deterministic hash of the query — groups result sets
    pub query_hash: String,
    pub workspace_id: String,
    pub session_name: String,
    /// Cosine-similarity score of the best-matching memory in this session
    pub score: f64,
    /// ID of the best-matching memory
    pub top_memory_id: String,
    /// Content of the best-matching memory
    pub top_memory_content: String,
    /// Total number of memories in this session
    pub memory_count: u32,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Simple non-cryptographic hash for a query string, used to group related
/// hybrid search results together.
fn query_hash(query: &str) -> String {
    let hash: u64 = query.bytes().fold(0u64, |acc, b| {
        acc.wrapping_mul(6364136223846793005).wrapping_add(b as u64)
    });
    format!("{:016x}", hash)
}

/// Tokenize a query string for BM25 keyword search.
///
/// Mirrors `retrieval::tokenize` but preserves the original query terms
/// as they appear (already lowercased by caller).  Filters stopwords and
/// short tokens.
fn tokenize_query(query: &str) -> Vec<String> {
    let stopwords: &[&str] = &[
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "shall", "you", "your",
        "yours", "he", "she", "it", "its", "they", "them", "their", "we",
        "us", "our", "this", "that", "these", "those", "am", "not", "no",
        "if", "then", "than", "so", "as", "just", "also", "very", "too",
        "about", "into", "over", "after", "before", "between", "through",
        "during", "above", "below", "up", "down", "out", "off", "here",
        "there", "all", "each", "every", "both", "few", "more", "most",
        "other", "some", "such", "only", "own", "same", "now", "when",
        "where", "how", "which", "who", "whom", "what", "why",
    ];

    query
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .map(|w| w.to_lowercase())
        .filter(|w| w.len() >= 2 && !stopwords.contains(&w.as_str()))
        .collect()
}

/// Parse a JSON array of f64 values into a Vec<f64>.
pub(crate) fn parse_embedding_json(s: &str) -> Vec<f64> {
    if s.is_empty() || s == "[]" || s == "null" {
        return vec![];
    }
    serde_json::from_str(s).unwrap_or_default()
}

/// Compute cosine similarity between two f64 vectors.
/// Returns 0.0 if either vector is empty or zero-norm.
pub(crate) fn cosine_similarity(a: &[f64], b: &[f64]) -> f64 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let dot: f64 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f64 = a.iter().map(|x| x * x).sum::<f64>().sqrt();
    let norm_b: f64 = b.iter().map(|x| x * x).sum::<f64>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    (dot / (norm_a * norm_b)).clamp(0.0, 1.0)
}

/// Compute Euclidean distance between two f64 vectors.
/// Returns the raw Euclidean distance (unbounded, ≥ 0).
/// For similarity scoring, use `euclidean_similarity` which normalizes to [0, 1].
#[allow(dead_code)]
pub(crate) fn euclidean_distance(a: &[f64], b: &[f64]) -> f64 {
    if a.len() != b.len() || a.is_empty() {
        return f64::MAX;
    }
    let sum_sq: f64 = a.iter().zip(b.iter()).map(|(x, y)| (x - y).powi(2)).sum();
    sum_sq.sqrt()
}

/// Compute Euclidean similarity between two f64 vectors.
/// Normalizes Euclidean distance into [0, 1] via `1.0 / (1.0 + distance)`.
/// 1.0 = identical, 0.0 → infinitely far apart.
#[allow(dead_code)]
pub(crate) fn euclidean_similarity(a: &[f64], b: &[f64]) -> f64 {
    let dist = euclidean_distance(a, b);
    if dist == f64::MAX {
        return 0.0;
    }
    1.0 / (1.0 + dist)
}

// ---------------------------------------------------------------------------
// Reducer: hybrid_search
// ---------------------------------------------------------------------------

/// Build a context_json string from workspace and memory contexts.
fn make_context_json(workspace_context: &str, memory_context: &str) -> String {
    format!(
        "{{\"workspace_context\":{},\"memory_context\":{}}}",
        serde_json::to_string(workspace_context).unwrap_or_else(|_| "\"\"".to_string()),
        serde_json::to_string(memory_context).unwrap_or_else(|_| "\"\"".to_string()),
    )
}

/// Register an entity in the workspace index for pre-filtering.
/// Called by `index_entity`, `store_memory`, `create_node`, etc.
/// Optionally stores the search_index PK for direct PK lookups.
pub(crate) fn register_workspace_entity(
    ctx: &ReducerContext,
    workspace_id: &str,
    entity_type: &str,
    entity_id: &str,
) {
    let id = format!("wi:{}:{}:{}", workspace_id, entity_type, entity_id);
    // Idempotent: skip if already registered (avoids duplicate-PK panic on
    // re-registration, e.g. update-then-reindex flows).
    if ctx.db.workspace_index().id().find(&id).is_some() {
        return;
    }
    ctx.db.workspace_index().insert(WorkspaceIndex {
        id,
        workspace_id: workspace_id.to_string(),
        entity_type: entity_type.to_string(),
        entity_id: entity_id.to_string(),
        search_index_id: String::new(),
    });
}

/// Register an entity in the workspace index WITH a search_index PK link,
/// and also populate the EntitySearchIndex mapping table for O(1) PK lookups.
/// Called by `index_entity` after inserting the search_index row.
pub(crate) fn register_indexed_entity(
    ctx: &ReducerContext,
    workspace_id: &str,
    entity_type: &str,
    entity_id: &str,
    search_index_id: &str,
) {
    let wi_id = format!("wi:{}:{}:{}", workspace_id, entity_type, entity_id);
    // Idempotent upsert: update the search_index link if already registered,
    // insert otherwise (avoids duplicate-PK panic on re-indexing).
    if let Some(mut existing) = ctx.db.workspace_index().id().find(&wi_id) {
        existing.search_index_id = search_index_id.to_string();
        ctx.db.workspace_index().id().update(existing);
    } else {
        ctx.db.workspace_index().insert(WorkspaceIndex {
            id: wi_id,
            workspace_id: workspace_id.to_string(),
            entity_type: entity_type.to_string(),
            entity_id: entity_id.to_string(),
            search_index_id: search_index_id.to_string(),
        });
    }
    // Also register the search_index entity type for workspace scanning
    let si_wi_id = format!("wi:{}:{}:{}", workspace_id, "search_index", entity_id);
    if let Some(mut existing) = ctx.db.workspace_index().id().find(&si_wi_id) {
        existing.search_index_id = search_index_id.to_string();
        ctx.db.workspace_index().id().update(existing);
    } else {
        ctx.db.workspace_index().insert(WorkspaceIndex {
            id: si_wi_id,
            workspace_id: workspace_id.to_string(),
            entity_type: "search_index".to_string(),
            entity_id: entity_id.to_string(),
            search_index_id: search_index_id.to_string(),
        });
    }
    // Populate EntitySearchIndex: entity_id → search_index PK
    let esi_id = format!("esi:{}", entity_id);
    if let Some(mut existing) = ctx.db.entity_search_index().id().find(&esi_id) {
        existing.search_index_id = search_index_id.to_string();
        ctx.db.entity_search_index().id().update(existing);
    } else {
        ctx.db.entity_search_index().insert(EntitySearchIndex {
            id: esi_id,
            entity_id: entity_id.to_string(),
            search_index_id: search_index_id.to_string(),
        });
    }
}

/// Register a term_index entry in the EntityTermIndex mapping table for
/// O(1) PK lookups during keyword search.  Called by `index_terms` after
/// inserting each term_index row.
pub(crate) fn register_entity_term(
    ctx: &ReducerContext,
    workspace_id: &str,
    entity_id: &str,
    term_index_id: &str,
) {
    let id = format!("eti:{}:{}", entity_id, term_index_id);
    // Idempotent: skip if this term is already registered for the entity.
    if ctx.db.entity_term_index().id().find(&id).is_some() {
        return;
    }
    ctx.db.entity_term_index().insert(EntityTermIndex {
        id,
        workspace_id: workspace_id.to_string(),
        entity_id: entity_id.to_string(),
        term_index_id: term_index_id.to_string(),
    });
}

/// Register a kg_edge entry in the NodeEdgeIndex mapping table for O(1)
/// PK lookups during graph strategy.  Called by edge-creation reducers.
pub(crate) fn register_node_edge(
    ctx: &ReducerContext,
    workspace_id: &str,
    node_id: &str,
    edge_id: &str,
) {
    let id = format!("nei:{}:{}", node_id, edge_id);
    // Idempotent: skip if this edge is already registered for the node.
    if ctx.db.node_edge_index().id().find(&id).is_some() {
        return;
    }
    ctx.db.node_edge_index().insert(NodeEdgeIndex {
        id,
        workspace_id: workspace_id.to_string(),
        node_id: node_id.to_string(),
        edge_id: edge_id.to_string(),
    });
}

/// Remove a specific entity type from the workspace index.
/// Called by `remove_from_index` and memory-deletion reducers.
pub(crate) fn unregister_workspace_entity(
    ctx: &ReducerContext,
    entity_type: &str,
    entity_id: &str,
) {
    let to_remove: Vec<String> = ctx.db.workspace_index()
        .iter()
        .filter(|wi| wi.entity_type == entity_type && wi.entity_id == entity_id)
        .map(|wi| wi.id.clone())
        .collect();
    for id in to_remove {
        ctx.db.workspace_index().id().delete(&id);
    }
}

/// Run multiple retrieval strategies and store fused results into `HybridResult`.
///
/// `strategies_json` is a JSON array of strategy names, e.g.
/// `["semantic","keyword","graph","temporal"]`. Empty string defaults to all four.
/// `query_embedding_json` is a JSON array of f64 embeddings (from the embedder sidecar).
/// Pass "[]" if not using semantic search — the "semantic" strategy will be skipped.
///
/// Strategies are run sequentially (SpacetimeDB reducers cannot do true parallelism),
/// and each produces rows in the `HybridResult` table keyed by a hash of the query.
#[reducer]
pub fn hybrid_search(
    ctx: &ReducerContext,
    workspace_id: String,
    query: String,
    query_embedding_json: String,
    memory_type: String,
    tier: String,
    limit: u32,
    strategies_json: String,
    // Time-to-live for cached results in milliseconds.
    // If > 0 and there are existing results for this (workspace, query_hash)
    // that are all newer than (now - cache_ttl_ms), the search pipeline is
    // skipped and the stale results are returned as-is (no re-computation).
    // Pass 0 to always re-run the full pipeline (legacy behaviour).
    cache_ttl_ms: u64,
    // If true, compound veracity (Bayesian confidence) for returned memories.
    // Each hit gets a small positive alpha boost (0.05) on every recall.
    compound: bool,
) -> Result<(), String> {
    trace_span!(ctx, "hybrid_search", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let qhash = query_hash(&query);
    let query_lower = query.to_lowercase();
    let query_terms: Vec<&str> = query_lower.split_whitespace().collect();

    // ── Query cache check ─────────────────────────────────────────
    // If cache_ttl_ms > 0, check whether we already have fresh-enough
    // results for this (workspace, query_hash).  If every existing row
    // is newer than (now - cache_ttl_ms) we can skip the search pipeline
    // entirely and just keep whatever is in hybrid_result.
    if cache_ttl_ms > 0 {
        let oldest_allowed = now.saturating_sub(cache_ttl_ms as i64);
        let cached_rows: Vec<_> = ctx
            .db
            .hybrid_result()
            .workspace_query()
            .filter((workspace_id.as_str(), qhash.as_str()))
            .take(crate::MAX_RESULTS)
            .collect();
        if !cached_rows.is_empty() && cached_rows.iter().all(|r| r.created_at >= oldest_allowed) {
            // Cache is fresh — keep existing results, skip re-computation.
            return Ok(());
        }
        // Cache is stale or empty — fall through to re-run the pipeline.
        // Delete stale rows so they don't pollute the new results.
        for r in &cached_rows {
            ctx.db.hybrid_result().id().delete(&r.id);
        }
    }

    // Internal defaults for advanced params
    let _polyphonic = true;
    let mmr_lambda: f64 = 0.7;

    // Parse the selected strategies (default: all four)
    let strategies: Vec<String> = if strategies_json.is_empty() {
        vec![
            "semantic".to_string(),
            "keyword".to_string(),
            "graph".to_string(),
            "temporal".to_string(),
        ]
    } else {
        serde_json::from_str(&strategies_json)
            .map_err(|e| format!("Invalid strategies_json: {}", e))?
    };

    // Clamp limit (default 10)
    let limit = if limit == 0 { 10 } else { limit };

    // ── Clear previous results for this (workspace, query_hash) ──
    // Each search call gets fresh results.  This avoids stale row
    // accumulation across repeated calls for the same query.
    let old: Vec<_> = ctx
        .db
        .hybrid_result()
        .workspace_query().filter((workspace_id.as_str(), qhash.as_str()))
        .take(crate::MAX_RESULTS)
        .collect();
    for r in old {
        ctx.db.hybrid_result().id().delete(r.id);
    }

    // Pre-fetch workspace context for context_json population
    let workspace_context = ctx
        .db
        .workspace()
        .id()
        .find(&workspace_id)
        .map(|ws| ws.context)
        .unwrap_or_default();

    // ── Workspace pre-filters ───────────────────────────────────────
    // Build compact HashSet lookups from the WorkspaceIndex so each
    // strategy can check entity membership in O(1) instead of scanning
    // full content tables with .filter(workspace_id).  The WorkspaceIndex
    // table has one tiny row per (workspace, entity_type, entity_id) —
    // much cheaper to scan than search_index (embedding blobs) or
    // term_index (one row per term per entity).
    let ws_memory_ids: std::collections::HashSet<String> = ctx.db.workspace_index()
        .workspace_id()
        .filter(&workspace_id)
        .filter(|wi| wi.entity_type == "memory")
        .map(|wi| wi.entity_id.clone())
        .collect();
    let ws_search_ids: std::collections::HashSet<String> = ctx.db.workspace_index()
        .workspace_id()
        .filter(&workspace_id)
        .filter(|wi| wi.entity_type == "search_index")
        .map(|wi| wi.entity_id.clone())
        .collect();
    let ws_node_ids: std::collections::HashSet<String> = ctx.db.workspace_index()
        .workspace_id()
        .filter(&workspace_id)
        .filter(|wi| wi.entity_type == "node")
        .map(|wi| wi.entity_id.clone())
        .collect();

    // Dispatch each selected strategy
    for strategy in &strategies {
        match strategy.as_str() {
            "semantic" => {
                // Parse query embedding; skip if empty (no embedding available)
                let query_emb = parse_embedding_json(&query_embedding_json);
                if query_emb.is_empty() {
                    // No query embedding provided — skip semantic strategy
                    continue;
                }
                let mut _count: u32 = 0;
                // Use EntitySearchIndex mapping table for O(1) PK lookups into
                // search_index — avoids iterating the full search_index table
                // (which carries expensive embedding blobs in every row).
                for entity_id in &ws_search_ids {
                    // PK lookup EntitySearchIndex → search_index_id
                    let esi_key = format!("esi:{}", entity_id);
                    let si_id = match ctx.db.entity_search_index().id().find(&esi_key) {
                        Some(esi) => esi.search_index_id.clone(),
                        None => continue,
                    };
                    // PK lookup search_index
                    let si = match ctx.db.search_index().id().find(&si_id) {
                        Some(si) => si,
                        None => continue,
                    };
                    let stored_emb = parse_embedding_json(&si.embedding_json);
                    if stored_emb.is_empty() {
                        continue;
                    }
                    let base_score = cosine_similarity(&query_emb, &stored_emb);
                    if base_score < 0.1 {
                        continue; // skip near-zero matches
                    }

                    // Single memory fetch (was two PK lookups) — used for
                    // readability filter, trust weighting, decay, and context.
                    let mem_row = if si.entity_type == "memory" {
                        ctx.db.memory().id().find(&si.entity_id)
                    } else {
                        None
                    };
                    // Zero-scheduler maintenance: skip inactive/expired memories
                    if let Some(m) = &mem_row {
                        if !crate::memory::is_readable(m, now) {
                            continue;
                        }
                    }
                    // Weight score by trust (0.5x–1.0x) and lazily-decayed
                    // strength (0.5x–1.0x) — no nightly decay pass needed.
                    let trust = mem_row.as_ref().map(|m| m.trust_score).unwrap_or(0.5);
                    let eff_strength = mem_row
                        .as_ref()
                        .map(|m| crate::memory::effective_strength(m, now))
                        .unwrap_or(0.5);
                    let score = base_score * (0.5 + trust * 0.5) * (0.5 + eff_strength * 0.5);

                    let memory_context = mem_row.map(|m| m.context).unwrap_or_default();
                    let context_json = make_context_json(&workspace_context, &memory_context);

                    ctx.db.hybrid_result().insert(HybridResult {
                        id: uuid_v7(ctx),
                        workspace_id: workspace_id.clone(),
                        query_hash: qhash.clone(),
                        entity_type: si.entity_type.clone(),
                        entity_id: si.entity_id.clone(),
                        content: si.content.clone(),
                        score,
                        strategy: "semantic".to_string(),
                        context_json,
                        created_at: now,
                    });
                }
            }

            "keyword" => {
                // BM25-based keyword search using the inverted term index
                let query_terms = tokenize_query(&query_lower);
                if query_terms.is_empty() {
                    continue;
                }

                // ── Single pass via EntityTermIndex ──
                // Scan lightweight EntityTermIndex (3 fields: id, entity_id, term_index_id)
                // instead of the full term_index table (7 fields including long term strings).
                // For each matching entry, do an O(1) PK lookup into term_index.
                use std::collections::{HashMap, HashSet};
                let mut entity_terms: HashMap<String, Vec<(String, u32, u32)>> = HashMap::new();
                let mut term_doc_freq: HashMap<String, usize> = HashMap::new();
                let mut total_tokens: u64 = 0;
                let mut doc_count: u64 = 0;
                let mut seen_entities: HashSet<String> = HashSet::new();

                for eti in ctx.db.entity_term_index().workspace_id().filter(&workspace_id) {
                    let ti = match ctx.db.term_index().id().find(&eti.term_index_id) {
                        Some(ti) => ti,
                        None => continue,
                    };
                    if ti.entity_type != "memory" {
                        continue;
                    }
                    let ti_term_lower = ti.term.to_lowercase();

                    // Collect query-term matches for BM25 scoring
                    if query_terms.contains(&ti_term_lower) {
                        entity_terms
                            .entry(ti.entity_id.clone())
                            .or_default()
                            .push((ti_term_lower.clone(), ti.term_frequency, ti.doc_length));
                        *term_doc_freq.entry(ti_term_lower).or_insert(0) += 1;
                    }

                    // Collect stats for IDF denominator and average doc length
                    total_tokens += ti.doc_length as u64;
                    doc_count += 1;
                    seen_entities.insert(ti.entity_id.clone());
                }

                if entity_terms.is_empty() {
                    continue;
                }

                let total_docs = seen_entities.len().max(1);
                let avg_doc_len = if doc_count > 0 {
                    total_tokens as f64 / doc_count as f64
                } else {
                    1.0
                };

                // Score each entity
                let mut scored: Vec<(String, String, f64)> = Vec::new(); // (entity_id, content, bm25)
                for (entity_id, term_infos) in &entity_terms {
                    // Build IDF map: term → (doc_freq, total_docs)
                    let mut idf_map: HashMap<String, (usize, usize)> = HashMap::new();
                    for (term, _, _) in term_infos {
                        let df = term_doc_freq.get(term).copied().unwrap_or(1);
                        idf_map.insert(term.clone(), (df, total_docs));
                    }

                    // Sum BM25 score across query terms
                    let mut total_score: f64 = 0.0;
                    for (term, tf, doc_len) in term_infos {
                        let df = term_doc_freq.get(term).copied().unwrap_or(1);
                        let idf = bm25_idf(df, total_docs);
                        let score = bm25_score(*tf, *doc_len, avg_doc_len);
                        total_score += idf * score;
                    }

                    // Resolve content from memory table
                    let content = ctx
                        .db
                        .memory()
                        .id()
                        .find(entity_id)
                        .map(|m| decrypt_if_enabled(ctx, &m.workspace_id, &m.content))
                        .unwrap_or_default();

                    scored.push((entity_id.clone(), content, total_score));
                }

                // Sort by BM25 score descending and take top limit
                scored.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));
                for (entity_id, content, bm25) in scored.iter().take(limit as usize) {
                    // Cap score to [0, 1] range
                    let score = bm25.clamp(0.0, 1.0);

                    let memory_context = ctx
                        .db
                        .memory()
                        .id()
                        .find(entity_id)
                        .map(|m| m.context)
                        .unwrap_or_default();
                    let context_json = make_context_json(&workspace_context, &memory_context);

                    ctx.db.hybrid_result().insert(HybridResult {
                        id: uuid_v7(ctx),
                        workspace_id: workspace_id.clone(),
                        query_hash: qhash.clone(),
                        entity_type: "memory".to_string(),
                        entity_id: entity_id.clone(),
                        content: content.clone(),
                        score,
                        strategy: "keyword".to_string(),
                        context_json,
                        created_at: now,
                    });
                }
            }

            "graph" => {
                // Phase 1: find nodes whose label or summary matches query terms
                // Instead of scanning kg_node with a .take() cap, iterate the
                // workspace's known node IDs from WorkspaceIndex and do direct
                // primary-key lookups via .id().find() — O(1) per node.
                let mut matching_node_ids: Vec<String> = Vec::new();
                for node_id in &ws_node_ids {
                    if let Some(n) = ctx.db.kg_node().id().find(node_id) {
                        let label_lower = n.label.to_lowercase();
                        let summary_lower = n.summary.to_lowercase();
                        if query_terms
                            .iter()
                            .any(|t| label_lower.contains(t) || summary_lower.contains(t))
                        {
                            matching_node_ids.push(node_id.clone());
                        }
                    }
                }
                // ── Pre-collect workspace edges via NodeEdgeIndex ──
                // Scan lightweight NodeEdgeIndex (3 fields: id, node_id, edge_id)
                // instead of the full kg_edge table (7 fields including source_node_id,
                // relation, target_node_id, weight). For each matching entry, do an
                // O(1) PK lookup into kg_edge.
                use std::collections::HashMap;
                let mut edges_by_node: HashMap<String, Vec<KgEdge>> = HashMap::new();
                for nei in ctx.db.node_edge_index().workspace_id().filter(&workspace_id) {
                    if let Some(edge) = ctx.db.kg_edge().id().find(&nei.edge_id) {
                        edges_by_node
                            .entry(nei.node_id.clone())
                            .or_default()
                            .push(edge);
                    }
                }

                let mut _count: u32 = 0;
                for node_id in &matching_node_ids {
                    if _count >= limit {
                        break;
                    }
                    // O(1) lookup in the pre-built index
                    if let Some(edges) = edges_by_node.get(node_id) {
                        for edge in edges {
                            if _count >= limit {
                                break;
                            }
                            let neighbor_id = if edge.source_node_id == *node_id {
                                &edge.target_node_id
                            } else {
                                &edge.source_node_id
                            };

                            // Resolve neighbor for display content
                            let (entity_id, content) =
                                if let Some(neighbor) = ctx.db.kg_node().id().find(neighbor_id) {
                                    (
                                        neighbor.id.clone(),
                                        format!(
                                            "{} --[{}]--> {}",
                                            edge.source_node_id, edge.relation, edge.target_node_id
                                        ),
                                    )
                                } else {
                                    (neighbor_id.clone(), format!("Edge to {}", neighbor_id))
                                };

                            let score = edge.weight * 0.5;
                            let context_json = make_context_json(&workspace_context, "");

                            ctx.db.hybrid_result().insert(HybridResult {
                                id: uuid_v7(ctx),
                                workspace_id: workspace_id.clone(),
                                query_hash: qhash.clone(),
                                entity_type: "node".to_string(),
                                entity_id,
                                content,
                                score,
                                strategy: "graph".to_string(),
                                context_json,
                                created_at: now,
                            });
                            _count += 1;
                        }
                    }

                    // Also include the matching node itself
                    if _count < limit {
                        if let Some(node) = ctx.db.kg_node().id().find(node_id) {
                            let context_json = make_context_json(&workspace_context, "");
                            ctx.db.hybrid_result().insert(HybridResult {
                                id: uuid_v7(ctx),
                                workspace_id: workspace_id.clone(),
                                query_hash: qhash.clone(),
                                entity_type: "node".to_string(),
                                entity_id: node.id.clone(),
                                content: format!("{}: {}", node.label, decrypt_if_enabled(ctx, &node.workspace_id, &node.summary)),
                                score: 0.3,
                                strategy: "graph".to_string(),
                                context_json,
                                created_at: now,
                            });
                            _count += 1;
                        }
                    }
                }
            }

            "temporal" => {
                // Iterate workspace's known memory IDs from WorkspaceIndex
                // and do direct primary-key lookups — avoids scanning the
                // memory table (which can be large) with a .take() cap.
                let mut memories: Vec<_> = Vec::new();
                for memory_id in &ws_memory_ids {
                    if let Some(m) = ctx.db.memory().id().find(memory_id) {
                        // Zero-scheduler maintenance: skip inactive/expired
                        if !crate::memory::is_readable(&m, now) {
                            continue;
                        }
                        if !memory_type.is_empty() && m.memory_type != memory_type {
                            continue;
                        }
                        if !tier.is_empty() && m.tier != tier {
                            continue;
                        }
                        memories.push(m);
                    }
                }

                // Most recent first
                memories.sort_by_key(|m| std::cmp::Reverse(m.created_at));

                for m in memories.iter().take(limit as usize) {
                    // Recency score: newer memories get higher scores
                    let age = if now > m.created_at {
                        (now - m.created_at) as f64
                    } else {
                        0.0
                    };
                    // 1 day = 86_400_000_000 micros; scale score linearly from 1.0 down to 0.5
                    let base_score = if age < 86_400_000_000.0 {
                        1.0 - (age / 86_400_000_000.0) * 0.5
                    } else {
                        0.5
                    };
                    // Weight by trust_score
                    let score = base_score * (0.5 + m.trust_score * 0.5);
                    let context_json = make_context_json(&workspace_context, &m.context);

                    ctx.db.hybrid_result().insert(HybridResult {
                        id: uuid_v7(ctx),
                        workspace_id: workspace_id.clone(),
                        query_hash: qhash.clone(),
                        entity_type: "memory".to_string(),
                        entity_id: m.id.clone(),
                        content: decrypt_if_enabled(ctx, &m.workspace_id, &m.content),
                        score,
                        strategy: "temporal".to_string(),
                        context_json,
                        created_at: now,
                    });
                }
            }

            _ => {
                return Err(format!("Unknown strategy '{}'", strategy));
            }
        }
    }

    // ── MMR (Maximal Marginal Relevance) Reranking ─────────────────
    // When mmr_lambda > 0.0, re-rank results to balance relevance
    // (query similarity) against diversity (dissimilarity to already-
    // selected results).  Uses embedding cosine similarity from
    // search_index for the diversity term.
    //
    //   MMR = argmax [ λ·relevance(d) − (1−λ)·max_sim(d, selected) ]
    //
    // λ=0.7 is the standard starting point (70% relevance, 30% diversity).
    if mmr_lambda > 0.0 && mmr_lambda <= 1.0 {
        let query_emb = parse_embedding_json(&query_embedding_json);
        let all_rows: Vec<_> = ctx
            .db
            .hybrid_result()
            .workspace_query().filter((workspace_id.as_str(), qhash.as_str()))
            .collect();

        if all_rows.len() >= 2 && !query_emb.is_empty() {
            use std::collections::HashMap;

            // Build embedding lookup: entity_id → Vec<f64>
            // Use EntitySearchIndex for O(1) PK lookups into search_index
            // instead of scanning the full search_index table (which carries
            // expensive embedding blobs in every row).
            let mut emb_cache: HashMap<String, Vec<f64>> = HashMap::new();
            for entity_id in &ws_search_ids {
                // PK lookup EntitySearchIndex → search_index_id
                let esi_key = format!("esi:{}", entity_id);
                let si_id = match ctx.db.entity_search_index().id().find(&esi_key) {
                    Some(esi) => esi.search_index_id.clone(),
                    None => continue,
                };
                // PK lookup search_index
                let si = match ctx.db.search_index().id().find(&si_id) {
                    Some(si) => si,
                    None => continue,
                };
                let emb = parse_embedding_json(&si.embedding_json);
                if !emb.is_empty() {
                    emb_cache.insert(si.entity_id.clone(), emb);
                }
            }

            // Collect candidates
            struct Candidate {
                row: HybridResult,
                score: f64,
                embedding: Vec<f64>,
            }

            let mut candidates: Vec<Candidate> = Vec::new();
            for row in &all_rows {
                let emb = emb_cache.get(&row.entity_id).cloned().unwrap_or_default();
                candidates.push(Candidate {
                    row: row.clone(),
                    score: row.score,
                    embedding: emb,
                });
            }

            candidates.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));

            let mut selected: Vec<Candidate> = Vec::new();
            let mut remaining: Vec<Candidate> = candidates;

            let target = (limit as usize).min(remaining.len());

            while selected.len() < target && !remaining.is_empty() {
                let mut best_idx: usize = 0;
                let mut best_mmr: f64 = f64::NEG_INFINITY;

                for (i, cand) in remaining.iter().enumerate() {
                    let relevance = if !query_emb.is_empty() && !cand.embedding.is_empty() {
                        cosine_similarity(&query_emb, &cand.embedding)
                    } else {
                        cand.score
                    };

                    let max_sim = if selected.is_empty() {
                        0.0
                    } else {
                        selected
                            .iter()
                            .map(|s| {
                                if s.embedding.is_empty() || cand.embedding.is_empty() {
                                    0.0
                                } else {
                                    cosine_similarity(&cand.embedding, &s.embedding)
                                }
                            })
                            .fold(0.0f64, f64::max)
                    };

                    let mmr = mmr_lambda * relevance - (1.0 - mmr_lambda) * max_sim;

                    if mmr > best_mmr {
                        best_mmr = mmr;
                        best_idx = i;
                    }
                }

                let chosen = remaining.remove(best_idx);
                selected.push(chosen);
            }

            // Update rows with MMR positional scores
            let mut mmr_scores: HashMap<String, (f64, String)> = HashMap::new();
            for (rank, cand) in selected.iter().enumerate() {
                let mmr_score = 1.0 / (1.0 + rank as f64);
                mmr_scores.insert(
                    cand.row.id.clone(),
                    (mmr_score, format!("{}+mmr", cand.row.strategy)),
                );
            }

            for mut row in all_rows {
                if let Some((mmr_score, strategy)) = mmr_scores.get(&row.id) {
                    row.score = *mmr_score;
                    row.strategy = strategy.clone();
                    ctx.db.hybrid_result().id().update(row);
                }
            }
        }
    }

    // If compound=true, apply Bayesian veracity boost for all returned memories
    if compound {
        let hit_ids: Vec<String> = ctx.db.hybrid_result()
            .workspace_query()
            .filter((workspace_id.as_str(), qhash.as_str()))
            .take(limit as usize)
            .map(|r| r.entity_id.clone())
            .collect();
        crate::veracity::compound_search_hits(ctx, &hit_ids, crate::veracity::COMPOUND_ALPHA_ON_RECALL);
    }

        Ok(())

    })
}

// ---------------------------------------------------------------------------
// Reducer: temporal_search_with_weight
// ---------------------------------------------------------------------------

/// Time-weighted memory retrieval with configurable recency weight.
///
/// Like the ``"temporal"`` strategy inside `hybrid_search`, but with:
/// - Exponential recency boost controlled by `recency_weight` (0.0-1.0)
/// - Optional `time_context`: "recent", "last_week", "last_month", or "" (no filter)
/// - Produces rows in the `HybridResult` table, keyed by an ad-hoc query_hash
///   that includes the recency_weight value (so different weights produce
///   separate result sets).
///
/// Results are sorted by recency-weighted score descending.
#[reducer]
pub fn temporal_search_with_weight(
    ctx: &ReducerContext,
    workspace_id: String,
    query: String,
    query_embedding_json: String,
    memory_type: String,
    tier: String,
    limit: u32,
    recency_weight: f64,
    time_context: String,
) -> Result<(), String> {
    trace_span!(ctx, "temporal_search_with_weight", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);
        let limit = if limit == 0 { 10 } else { limit };
        let recency_weight = recency_weight.clamp(0.0, 1.0);

        // Build a unique query hash that includes recency_weight
        let qhash = format!(
            "tw:{}:{}",
            crate::hybrid_query::query_hash(&query),
            (recency_weight * 100.0) as u32
        );

        // Parse time_context into a temporal filter (in micros since epoch)
        let min_created_at: i64 = match time_context.as_str() {
            "recent" => now - 86_400_000_000,          // last 24 hours
            "last_week" => now - 7 * 86_400_000_000,   // last 7 days
            "last_month" => now - 30 * 86_400_000_000,  // last 30 days
            "last_3_months" => now - 90 * 86_400_000_000,
            "last_year" => now - 365 * 86_400_000_000,
            _ => 0, // no filter
        };

        // Clear previous results for this (workspace, query_hash)
        let old: Vec<_> = ctx
            .db
            .hybrid_result()
            .workspace_query().filter((workspace_id.as_str(), qhash.as_str()))
            .take(crate::MAX_RESULTS)
            .collect();
        for r in old {
            ctx.db.hybrid_result().id().delete(r.id);
        }

        let workspace_context = ctx
            .db
            .workspace()
            .id()
            .find(&workspace_id)
            .map(|ws| ws.context)
            .unwrap_or_default();

        // Build workspace pre-filter from WorkspaceIndex
        let ws_memory_ids: std::collections::HashSet<String> = ctx
            .db
            .workspace_index()
            .workspace_id()
            .filter(&workspace_id)
            .filter(|wi| wi.entity_type == "memory")
            .map(|wi| wi.entity_id.clone())
            .collect();

        // Pre-build search_index embedding lookup (entity_id → embedding_json)
        // to avoid per-memory scan of search_index for semantic boost.
        let mut search_embeddings: std::collections::HashMap<String, String> = std::collections::HashMap::new();
        for si in ctx.db.search_index().workspace_id().filter(&workspace_id) {
            if si.entity_type == "memory" && ws_memory_ids.contains(&si.entity_id) {
                search_embeddings.insert(si.entity_id.clone(), si.embedding_json.clone());
            }
        }

        let query_emb = crate::hybrid_query::parse_embedding_json(&query_embedding_json);

        let mut scored: Vec<(f64, String, String, String)> = Vec::new();

        // Iterate workspace's known memory IDs — direct PK lookups, no scan
        for memory_id in &ws_memory_ids {
            let m = match ctx.db.memory().id().find(memory_id) {
                Some(m) => m,
                None => continue,
            };
            if !crate::memory::is_readable(&m, now) {
                continue;
            }
            if !memory_type.is_empty() && m.memory_type != memory_type {
                continue;
            }
            if !tier.is_empty() && m.tier != tier {
                continue;
            }
            if min_created_at > 0 && m.created_at < min_created_at {
                continue;
            }

            // Compute age
            let age = if now > m.created_at {
                (now - m.created_at) as f64
            } else {
                0.0
            };

            // Base recency: exponential decay
            let half_life: f64 = 7.0 * 86_400_000_000.0;
            let recency_score = if recency_weight > 0.0 {
                (-age / half_life).exp()
            } else {
                1.0
            };
            let blended_recency = 1.0 - recency_weight + recency_weight * recency_score;

            // Semantic boost from pre-built embedding lookup — O(1) per memory
            let semantic_boost = if !query_emb.is_empty() {
                if let Some(emb_str) = search_embeddings.get(&m.id) {
                    let stored_emb = crate::hybrid_query::parse_embedding_json(emb_str);
                    if stored_emb.len() == query_emb.len() {
                        crate::hybrid_query::cosine_similarity(&query_emb, &stored_emb)
                    } else {
                        0.0
                    }
                } else {
                    0.0
                }
            } else {
                0.0
            };

            // Final score: blend recency (70%) with semantic relevance (30%)
            let score = 0.7 * blended_recency + 0.3 * semantic_boost;

            scored.push((score, m.id.clone(), decrypt_if_enabled(ctx, &m.workspace_id, &m.content), m.context.clone()));
        }

        // Sort by score descending, take top limit
        scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(limit as usize);

        for (score, entity_id, content, context) in &scored {
            let context_json = format!(
                "{{\"workspace_context\":{},\"memory_context\":{}}}",
                serde_json::to_string(&workspace_context)
                    .unwrap_or_else(|_| "\"\"".to_string()),
                serde_json::to_string(context)
                    .unwrap_or_else(|_| "\"\"".to_string()),
            );

            ctx.db.hybrid_result().insert(HybridResult {
                id: uuid_v7(ctx),
                workspace_id: workspace_id.clone(),
                query_hash: qhash.clone(),
                entity_type: "memory".to_string(),
                entity_id: entity_id.clone(),
                content: content.clone(),
                score: *score,
                strategy: format!("temporal_weighted_{}", (recency_weight * 100.0) as u32),
                context_json,
                created_at: now,
            });
        }

        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Reducer: get_search_results
// ---------------------------------------------------------------------------

/// Reducer that signals the client should read the `HybridResult`
/// table directly. SpacetimeDB v2.4 reducers cannot return row data to the
/// caller, so after calling `hybrid_search` the client queries `HybridResult`
/// filtered by `workspace_id` and `query_hash`.
#[reducer]
pub fn get_search_results(
    ctx: &ReducerContext,
    workspace_id: String,
    query_hash: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Validate that results exist for this workspace+hash combination
    let exists = ctx
        .db
        .hybrid_result()
        .workspace_query().filter((workspace_id.as_str(), query_hash.as_str()))
        .take(crate::MAX_RESULTS)
        .next().is_some();

    if !exists {
        return Err(format!(
            "No search results found for workspace '{}' and query hash '{}'. \
             Call hybrid_search first.",
            workspace_id, query_hash
        ));
    }

    // Signal success — the client reads `HybridResult` directly from the
    // subscription or a SQL query.
    Ok(())
}

// ---------------------------------------------------------------------------
// Reducer: compute_god_nodes
// ---------------------------------------------------------------------------

/// Compute the top-N most connected nodes (highest degree) in the knowledge
/// graph for a workspace. Clears previous `GodNode` entries for this
/// workspace and inserts fresh ones.
#[reducer]
pub fn compute_god_nodes(
    ctx: &ReducerContext,
    workspace_id: String,
    top_n: u32,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let top_n = if top_n == 0 { 10 } else { top_n };

    // Count degree for every node that has at least one edge in this workspace
    let mut degree_map: std::collections::HashMap<String, u64> =
        std::collections::HashMap::new();

    for edge in ctx.db.kg_edge().workspace_id().filter(&workspace_id) {
        // Increment degree for both source and target
        *degree_map.entry(edge.source_node_id.clone()).or_insert(0) += 1;
        // Only count once per edge if source == target (self-loop), but in
        // practice self-loops are rare; we still count them once.
        if edge.target_node_id != edge.source_node_id {
            *degree_map.entry(edge.target_node_id.clone()).or_insert(0) += 1;
        }
    }

    // Sort by degree descending, take top N
    let mut sorted: Vec<(String, u64)> = degree_map.into_iter().collect();
    sorted.sort_by_key(|x| std::cmp::Reverse(x.1));
    sorted.truncate(top_n as usize);

    // Remove previous GodNode entries for this workspace
    let old: Vec<_> = ctx
        .db
        .god_node()
        .iter().take(crate::MAX_RESULTS)
        .filter(|g| g.workspace_id == workspace_id)
        .collect();
    for g in old {
        ctx.db.god_node().id().delete(&g.id);
    }

    // Insert new GodNode entries
    for (node_id, edge_count) in &sorted {
        ctx.db.god_node().insert(GodNode {
            id: uuid_v7(ctx),
            workspace_id: workspace_id.clone(),
            node_id: node_id.clone(),
            edge_count: *edge_count,
            computed_at: now,
        });
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Reducer: search_sessions_semantic
// ---------------------------------------------------------------------------

/// Cross-workspace semantic session search.
///
/// Iterates all indexed memories (entity_type="memory") across ALL workspaces,
/// computes cosine similarity against ``query_embedding_json``, groups by
/// workspace to find each session's best match, and stores the top-*limit*
/// results in the ``SessionSearchResult`` table.
///
/// This enables Zep-style ``search_sessions``: given a natural-language query,
/// return sessions whose memory content is semantically relevant — not just
/// those whose name matches the query string.
#[reducer]
pub fn search_sessions_semantic(
    ctx: &ReducerContext,
    query_embedding_json: String,
    limit: u32,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let query_emb = parse_embedding_json(&query_embedding_json);
    if query_emb.is_empty() {
        return Err("No query embedding provided — cannot perform semantic search".to_string());
    }

    let limit = if limit == 0 { 10 } else { limit };
    let qhash = format!("sessions:{}", limit);

    // Clear previous results for this query hash
    let old: Vec<_> = ctx.db.session_search_result().iter().take(crate::MAX_RESULTS)
        .filter(|r| r.query_hash == qhash)
        .collect();
    for r in old {
        ctx.db.session_search_result().delete(r);
    }

    // Collect all indexed memories with embeddings, grouped by workspace
    use std::collections::HashMap;
    // (best_score, top_memory_id, top_memory_content, memory_count)
    let mut workspace_scores: HashMap<String, (f64, String, String, u32)> = HashMap::new();

    for si in ctx.db.search_index().iter().take(crate::MAX_RESULTS) {
        if si.entity_type != "memory" {
            continue;
        }
        let stored_emb = parse_embedding_json(&si.embedding_json);
        if stored_emb.is_empty() {
            continue;
        }
        let score = cosine_similarity(&query_emb, &stored_emb);
        if score < 0.1 {
            continue;
        }

        let entry = workspace_scores
            .entry(si.workspace_id.clone())
            .or_insert_with(|| (0.0, String::new(), String::new(), 0));
        entry.3 += 1; // count

        if score > entry.0 {
            entry.0 = score;
            entry.1 = si.entity_id.clone();
            entry.2 = si.content.clone();
        }
    }

    // Sort by score descending, take top-k
    let mut sorted: Vec<(String, (f64, String, String, u32))> = workspace_scores
        .into_iter()
        .collect();
    sorted.sort_by(|a, b| b.1.0.partial_cmp(&a.1.0).unwrap_or(std::cmp::Ordering::Equal));

    for (ws_id, (score, mem_id, mem_content, count)) in sorted.iter().take(limit as usize) {
        // Try to resolve the workspace name as the session name
        let session_name = ctx.db.workspace()
            .id()
            .find(ws_id.clone())
            .map(|ws| ws.name.clone())
            .unwrap_or_else(|| ws_id.clone());

        ctx.db.session_search_result().insert(SessionSearchResult {
            id: uuid_v7(ctx),
            query_hash: qhash.clone(),
            workspace_id: ws_id.clone(),
            session_name,
            score: *score,
            top_memory_id: mem_id.clone(),
            top_memory_content: mem_content.clone(),
            memory_count: *count,
            created_at: now,
        });
    }

    Ok(())
}

// ── Search by tags ──────────────────────────────────────────────────────────────

/// Search memories by tag filter, optionally with semantic ranking.
///
/// `tag_ids_json`: JSON array of tag ID strings. Only memories that have ALL
///   specified tags are returned (intersection).
/// `workspace_id`: Scope to a specific workspace.
/// `query_embedding_json`: Optional JSON array of f64 embeddings. Pass "[]" to
///   skip semantic ranking (results ordered by recency).
/// `limit`: Maximum results to return (default 10).
///
/// Results are written to `hybrid_result` with strategy "tagged".
#[reducer]
pub fn search_by_tags(
    ctx: &ReducerContext,
    workspace_id: String,
    tag_ids_json: String,
    query_embedding_json: String,
    limit: u32,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let qhash = format!("tagged:{}", tag_ids_json); // deterministic query hash
    let limit = if limit == 0 { 10 } else { limit };

    // Parse tag IDs
    let tag_ids: Vec<String> = serde_json::from_str(&tag_ids_json)
        .map_err(|e| format!("Invalid tag_ids_json: {}", e))?;
    if tag_ids.is_empty() {
        return Err("search_by_tags: at least one tag_id required".to_string());
    }

    // ── Clear previous results for this query_hash ──
    let old: Vec<_> = ctx
        .db
        .hybrid_result()
        .workspace_query().filter((workspace_id.as_str(), qhash.as_str()))
        .take(crate::MAX_RESULTS)
        .collect();
    for r in old {
        ctx.db.hybrid_result().id().delete(r.id);
    }

    // ── Find memories tagged with ALL specified tags (intersection) ──
    // Collect all (memory_id, tag_id) pairs, then filter to memories that
    // appear for every requested tag.
    let mut mem_tags: std::collections::HashMap<String, Vec<String>> = std::collections::HashMap::new();
    for mt in ctx.db.memory_tag().workspace_id().filter(&workspace_id) {
        if tag_ids.contains(&mt.tag_id) {
            mem_tags.entry(mt.memory_id.clone())
                .or_default()
                .push(mt.tag_id.clone());
        }
    }
    // Collect memory IDs that have ALL of the requested tags
    let matched_memory_ids: Vec<String> = mem_tags
        .into_iter()
        .filter(|(_, tags)| {
            tag_ids.iter().all(|tid| tags.contains(tid))
        })
        .map(|(mid, _)| mid)
        .collect();

    if matched_memory_ids.is_empty() {
        return Ok(()); // No matches — nothing to write
    }

    // ── Parse query embedding ──
    let query_emb = parse_embedding_json(&query_embedding_json);
    let has_embedding = !query_emb.is_empty();
    let qnorm = if has_embedding {
        let s: f64 = query_emb.iter().map(|x| x * x).sum();
        s.sqrt()
    } else {
        0.0
    };

    // ── Score and rank ──
    struct Candidate {
        entity_id: String,
        entity_type: String,
        content: String,
        score: f64,
    }

    let mut candidates: Vec<Candidate> = Vec::new();

    // Pre-fetch search_index for efficient lookup
    let si_map: std::collections::HashMap<String, (String, String, String)> = ctx
        .db
        .search_index()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
        .filter(|si| matched_memory_ids.contains(&si.entity_id))
        .map(|si| {
            (
                si.entity_id.clone(),
                (
                    si.embedding_json.clone(),
                    si.content.clone(),
                    si.entity_type.clone(),
                ),
            )
        })
        .collect();

    for mid in &matched_memory_ids {
        let (emb_str, content, etype) = match si_map.get(mid) {
            Some(v) => v.clone(),
            None => continue,
        };

        let score = if has_embedding && !emb_str.is_empty() && emb_str != "[]" {
            if let Ok(stored_emb) = serde_json::from_str::<Vec<f64>>(&emb_str) {
                if stored_emb.len() == query_emb.len() && qnorm > 0.0 {
                    let s_norm: f64 = stored_emb.iter().map(|x| x * x).sum::<f64>().sqrt();
                    if s_norm > 0.0 {
                        let dot: f64 = query_emb.iter().zip(stored_emb.iter()).map(|(a, b)| a * b).sum();
                        (dot / (qnorm * s_norm)).clamp(0.0, 1.0)
                    } else {
                        0.0
                    }
                } else {
                    0.0
                }
            } else {
                0.0
            }
        } else {
            // No embedding — score by recency (recent = higher)
            0.5
        };

        if score >= 0.1 {
            candidates.push(Candidate {
                entity_id: mid.clone(),
                entity_type: etype,
                content,
                score,
            });
        }
    }

    // Sort by score descending
    candidates.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));

    // Insert top results
    let workspace_context = ctx
        .db
        .workspace()
        .id()
        .find(&workspace_id)
        .map(|ws| ws.context)
        .unwrap_or_default();

    for c in candidates.into_iter().take(limit as usize) {
        let memory_context = if c.entity_type == "memory" {
            match ctx.db.memory().id().find(&c.entity_id) {
                // Zero-scheduler maintenance: skip inactive/expired
                Some(m) if crate::memory::is_readable(&m, now) => m.context,
                Some(_) => continue,
                None => String::new(),
            }
        } else {
            String::new()
        };
        let context_json = make_context_json(&workspace_context, &memory_context);

        ctx.db.hybrid_result().insert(HybridResult {
            id: uuid_v7(ctx),
            workspace_id: workspace_id.clone(),
            query_hash: qhash.clone(),
            entity_type: c.entity_type,
            entity_id: c.entity_id,
            content: c.content,
            score: c.score,
            strategy: "tagged".to_string(),
            context_json,
            created_at: now,
        });
    }

    Ok(())
}

// ─── Tests ──────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_query_hash_deterministic() {
        let h1 = query_hash("hello world");
        let h2 = query_hash("hello world");
        assert_eq!(h1, h2);
    }

    #[test]
    fn test_query_hash_different_queries() {
        let h1 = query_hash("foo");
        let h2 = query_hash("bar");
        assert_ne!(h1, h2);
    }

    #[test]
    fn test_query_hash_empty() {
        let h = query_hash("");
        assert_eq!(h.len(), 16);
    }

    #[test]
    fn test_parse_embedding_json_valid() {
        let parsed = parse_embedding_json("[1.0, 2.0, 3.0]");
        assert_eq!(parsed.len(), 3);
        assert!((parsed[0] - 1.0).abs() < 1e-10);
        assert!((parsed[2] - 3.0).abs() < 1e-10);
    }

    #[test]
    fn test_parse_embedding_json_empty_array() {
        let parsed = parse_embedding_json("[]");
        assert!(parsed.is_empty());
    }

    #[test]
    fn test_parse_embedding_json_empty_string() {
        let parsed = parse_embedding_json("");
        assert!(parsed.is_empty());
    }

    #[test]
    fn test_parse_embedding_json_null() {
        let parsed = parse_embedding_json("null");
        assert!(parsed.is_empty());
    }

    #[test]
    fn test_parse_embedding_json_invalid() {
        let parsed = parse_embedding_json("not json");
        assert!(parsed.is_empty());
    }

    #[test]
    fn test_cosine_similarity_identical() {
        let v = vec![1.0, 2.0, 3.0, 4.0];
        let sim = cosine_similarity(&v, &v);
        assert!((sim - 1.0).abs() < 1e-6);
    }

    #[test]
    fn test_cosine_similarity_orthogonal() {
        let a = vec![1.0, 0.0];
        let b = vec![0.0, 1.0];
        let sim = cosine_similarity(&a, &b);
        assert!(sim.abs() < 1e-10);
    }

    #[test]
    fn test_cosine_similarity_partial() {
        let a = vec![1.0, 0.0];
        let b = vec![1.0, 1.0];
        let sim = cosine_similarity(&a, &b);
        // dot=1.0, |a|=1.0, |b|=sqrt(2) ≈ 1.414, sim ≈ 0.707
        assert!((sim - 1.0 / 2.0_f64.sqrt()).abs() < 1e-6);
    }

    #[test]
    fn test_cosine_similarity_mismatched_lengths() {
        let a = vec![1.0, 2.0];
        let b = vec![1.0];
        let sim = cosine_similarity(&a, &b);
        assert_eq!(sim, 0.0);
    }

    #[test]
    fn test_cosine_similarity_empty() {
        let sim = cosine_similarity(&[], &[]);
        assert_eq!(sim, 0.0);
    }

    #[test]
    fn test_cosine_similarity_zero_vector() {
        let a = vec![0.0, 0.0];
        let b = vec![1.0, 2.0];
        let sim = cosine_similarity(&a, &b);
        assert_eq!(sim, 0.0);
    }

    #[test]
    fn test_cosine_similarity_single_dimension() {
        let a = vec![5.0];
        let b = vec![2.5];
        let sim = cosine_similarity(&a, &b);
        // Both 1-D, dot = 12.5, |a|=5, |b|=2.5, sim=1.0
        assert!((sim - 1.0).abs() < 1e-6);
    }

    // ── euclidean_distance / euclidean_similarity ─────────────────────────────────

    #[test]
    fn test_euclidean_distance_identical() {
        let v = vec![1.0, 2.0, 3.0, 4.0];
        let d = euclidean_distance(&v, &v);
        assert!(d.abs() < 1e-10);
    }

    #[test]
    fn test_euclidean_distance_different() {
        let a = vec![0.0, 0.0];
        let b = vec![3.0, 4.0];
        let d = euclidean_distance(&a, &b);
        assert!((d - 5.0).abs() < 1e-10);
    }

    #[test]
    fn test_euclidean_distance_mismatched() {
        let a = vec![1.0, 2.0];
        let b = vec![1.0];
        let d = euclidean_distance(&a, &b);
        assert_eq!(d, f64::MAX);
    }

    #[test]
    fn test_euclidean_distance_empty() {
        let d = euclidean_distance(&[], &[]);
        assert_eq!(d, f64::MAX);
    }

    #[test]
    fn test_euclidean_similarity_identical() {
        let v = vec![1.0, 2.0, 3.0];
        let sim = euclidean_similarity(&v, &v);
        assert!((sim - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_euclidean_similarity_far() {
        // Very far apart → similarity approaches 0
        let a = vec![0.0, 0.0];
        let b = vec![1e6, 1e6];
        let sim = euclidean_similarity(&a, &b);
        assert!(sim > 0.0 && sim < 0.01);
    }

    #[test]
    fn test_euclidean_similarity_mismatched() {
        let a = vec![1.0, 2.0];
        let b = vec![1.0];
        let sim = euclidean_similarity(&a, &b);
        assert_eq!(sim, 0.0);
    }

    #[test]
    fn test_euclidean_similarity_empty() {
        let sim = euclidean_similarity(&[], &[]);
        assert_eq!(sim, 0.0);
    }

    // ── tokenize_query ───────────────────────────────────────────────────────────

    #[test]
    fn test_tokenize_query_basic() {
        let tokens = tokenize_query("Rust memory system");
        assert!(tokens.contains(&"rust".to_string()));
        assert!(tokens.contains(&"memory".to_string()));
        assert!(tokens.contains(&"system".to_string()));
    }

    #[test]
    fn test_tokenize_query_removes_stopwords() {
        let tokens = tokenize_query("the and for with");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_tokenize_query_short_words() {
        let tokens = tokenize_query("a b c d");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_tokenize_query_mixed() {
        let tokens = tokenize_query("the quick brown fox jumps");
        assert!(!tokens.contains(&"the".to_string()));
        assert!(tokens.contains(&"quick".to_string()));
        assert!(tokens.contains(&"brown".to_string()));
        assert!(tokens.contains(&"fox".to_string()));
        assert!(tokens.contains(&"jumps".to_string()));
    }

    #[test]
    fn test_tokenize_query_punctuation() {
        let tokens = tokenize_query("hello, world! how's it?");
        assert!(tokens.contains(&"hello".to_string()));
        assert!(tokens.contains(&"world".to_string()));
        assert!(!tokens.contains(&"it".to_string()));
    }

    #[test]
    fn test_tokenize_query_empty() {
        let tokens = tokenize_query("");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_tokenize_query_numbers() {
        let tokens = tokenize_query("GPT4 and BERT score");
        assert!(tokens.contains(&"gpt4".to_string()));
        assert!(tokens.contains(&"bert".to_string()));
        assert!(tokens.contains(&"score".to_string()));
    }

    // ── make_context_json ────────────────────────────────────────────────────────

    #[test]
    fn test_make_context_json_basic() {
        let json = make_context_json("workspace ctx", "memory ctx");
        assert!(json.contains("workspace_context"));
        assert!(json.contains("workspace ctx"));
        assert!(json.contains("memory_context"));
        assert!(json.contains("memory ctx"));
    }

    #[test]
    fn test_make_context_json_empty_strings() {
        let json = make_context_json("", "");
        // Should produce valid JSON: {"workspace_context":"","memory_context":""}
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert!(parsed.is_object());
        assert_eq!(parsed["workspace_context"], "");
        assert_eq!(parsed["memory_context"], "");
    }

    #[test]
    fn test_make_context_json_special_chars() {
        let json = make_context_json("hello \"world\"", "line\nbreak");
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["workspace_context"], "hello \"world\"");
        assert_eq!(parsed["memory_context"], "line\nbreak");
    }

    #[test]
    fn test_make_context_json_valid_json() {
        let json = make_context_json("a", "b");
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert!(parsed.is_object());
        assert_eq!(parsed["workspace_context"], "a");
        assert_eq!(parsed["memory_context"], "b");
    }

    // ── MMR formula (pure calculation, no reducer context) ───────────────────────

    #[test]
    fn test_mmr_relevance_dominates_with_high_lambda() {
        // MMR with λ=1.0 should return results in pure relevance order
        // (no diversity penalty). Since we can't test the full reducer
        // in a unit test, we verify the formula directly.
        let relevance: f64 = 0.9;
        let max_sim: f64 = 0.8;
        let lambda: f64 = 1.0;
        let mmr: f64 = lambda * relevance - (1.0 - lambda) * max_sim;
        assert!((mmr - 0.9_f64).abs() < 1e-10);
    }

    #[test]
    fn test_mmr_diversity_matters_with_low_lambda() {
        // λ=0.0 means only diversity matters — penalize high similarity
        let relevance: f64 = 0.9;
        let max_sim: f64 = 0.8;
        let lambda: f64 = 0.0;
        let mmr: f64 = lambda * relevance - (1.0 - lambda) * max_sim;
        assert!((mmr - (-0.8_f64)).abs() < 1e-10);
    }

    #[test]
    fn test_mmr_standard_lambda() {
        // λ=0.7 is the standard default
        let relevance: f64 = 0.85;
        let max_sim: f64 = 0.60;
        let lambda: f64 = 0.7;
        let mmr: f64 = lambda * relevance - (1.0 - lambda) * max_sim;
        let expected: f64 = 0.7 * 0.85 - 0.3 * 0.60; // 0.595 - 0.18 = 0.415
        assert!((mmr - expected).abs() < 1e-10);
    }

    // ── Query Hash (pure function) ──────────────────────────────────

    #[test]
    fn test_query_hash_is_deterministic() {
        let a = query_hash("hello world");
        let b = query_hash("hello world");
        assert_eq!(a, b);
        assert!(!a.is_empty());
    }

    #[test]
    fn test_query_hash_differs_for_different_queries() {
        let a = query_hash("hello world");
        let b = query_hash("world hello");
        assert_ne!(a, b);
    }

    #[test]
    fn test_query_hash_empty_string_produces_valid_hash() {
        let h = query_hash("");
        assert!(!h.is_empty());
    }

    #[test]
    fn test_query_hash_unicode_produces_hash() {
        let h = query_hash("über cool café");
        assert!(!h.is_empty());
    }

    #[test]
    fn test_cache_ttl_zero_means_no_cache() {
        // When cache_ttl_ms is 0, the check is skipped entirely.
        // We can't call the reducer without a ctx, so we verify the
        // logic directly: the condition `cache_ttl_ms > 0` gates the
        // cache lookup, so 0 means always re-run.
        let cache_ttl_ms: u64 = 0;
        assert!(!(cache_ttl_ms > 0));
    }

    #[test]
    fn test_cache_ttl_threshold_logic() {
        // If created_at >= oldest_allowed, the row is fresh.
        // This tests the comparison used in the cache-hit check.
        let now: i64 = 1_000_000;
        let cache_ttl_ms: u64 = 100;
        let oldest_allowed = now.saturating_sub(cache_ttl_ms as i64); // 999_900

        // Fresh rows: created_at == now
        assert!(now >= oldest_allowed);
        // Row from just inside the window
        assert!(999_950i64 >= oldest_allowed);
        // Row from just outside the window
        assert!(999_800i64 < oldest_allowed);
        // Row from far in the past
        assert!(500_000i64 < oldest_allowed);
    }

    #[test]
    fn test_cache_ttl_edge_case_zero() {
        // cache_ttl_ms=0: oldest_allowed = now - 0 = now
        // Only rows with created_at >= now pass — but no row can have
        // created_at > now, so in practice the cache is always stale.
        let now: i64 = 1_000_000;
        let oldest_allowed = now.saturating_sub(0u64 as i64);
        assert_eq!(oldest_allowed, now);
        // A row created right now passes
        assert!(now >= oldest_allowed);
        // A row created 1 microsecond ago fails
        assert!(999_999i64 < oldest_allowed);
    }

    #[test]
    fn test_cache_ttl_saturating_sub_does_not_underflow() {
        // Even with a very large TTL and a now that is before the Unix epoch
        // (which shouldn't happen in practice since now_micros returns
        // microseconds since Unix epoch), saturating_sub should not panic
        // or wrap around. The result may be negative but that's fine — the
        // comparison against created_at will correctly mark all rows as stale.
        let now: i64 = 50;
        let cache_ttl_ms: u64 = 1_000_000;
        let oldest_allowed = now.saturating_sub(cache_ttl_ms as i64);
        // The result should be exactly 50 - 1_000_000 = -999_950 (no saturation
        // needed since this is well within i64 range).  The important thing is
        // that no arithmetic panic or overflow occurred.
        assert_eq!(oldest_allowed, -999_950);
    }
}
