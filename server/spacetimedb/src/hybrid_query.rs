use spacetimedb::*;
use crate::auth::require_auth;
use crate::auth::require_admin;

use crate::knowledge_graph::{kg_edge, kg_node};
use crate::memory::memory;
use crate::retrieval::{
    search_index, term_index, bm25_idf, bm25_score,
};
use crate::workspace::workspace;
use crate::{now_micros, uuid_v7, MAX_RESULTS};
use crate::tracing::TracingSpanKind;
use crate::trace_span;

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// Stores results from a hybrid multi-strategy search query.
/// Clients read this table after calling `hybrid_search` to get fused results.
#[table(accessor = hybrid_result, public)]
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
#[table(accessor = god_node, public)]
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

/// Result table for cross-workspace session search via semantic (cosine)
/// similarity.  Clients call ``search_sessions_semantic`` then read this table.
#[table(accessor = session_search_result, public)]
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
    _polyphonic: bool,
    mmr_lambda: f64,
) -> Result<(), String> {
    trace_span!(ctx, "hybrid_search", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let qhash = query_hash(&query);
    let query_lower = query.to_lowercase();
    let query_terms: Vec<&str> = query_lower.split_whitespace().collect();

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
        .iter()
        .take(MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id && r.query_hash == qhash)
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
                for si in ctx.db.search_index().iter()
                    .filter(|si| si.workspace_id == workspace_id)
                    .take(MAX_RESULTS)
                {
                    let stored_emb = parse_embedding_json(&si.embedding_json);
                    if stored_emb.is_empty() {
                        continue;
                    }
                    let base_score = cosine_similarity(&query_emb, &stored_emb);
                    if base_score < 0.1 {
                        continue; // skip near-zero matches
                    }

                    // Weight score by entity trust_score (0.5x–1.0x multiplier)
                    let trust = if si.entity_type == "memory" {
                        ctx.db
                            .memory()
                            .id()
                            .find(&si.entity_id)
                            .map(|m| m.trust_score)
                            .unwrap_or(0.5)
                    } else {
                        0.5
                    };
                    let score = base_score * (0.5 + trust * 0.5);

                    let memory_context = if si.entity_type == "memory" {
                        ctx.db.memory().id().find(&si.entity_id)
                            .map(|m| m.context)
                            .unwrap_or_default()
                    } else {
                        String::new()
                    };
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
                    _count += 1;
                }
            }

            "keyword" => {
                // BM25-based keyword search using the inverted term index
                let query_terms = tokenize_query(&query_lower);
                if query_terms.is_empty() {
                    continue;
                }

                // Collect all term index entries for the query terms in this workspace
                // Build: entity_id → Vec<(term, tf, doc_len)>
                use std::collections::HashMap;
                let mut entity_terms: HashMap<String, Vec<(String, u32, u32)>> = HashMap::new();
                let mut term_doc_freq: HashMap<String, usize> = HashMap::new();

                for ti in ctx.db.term_index().iter().take(crate::MAX_RESULTS) {
                    if ti.workspace_id != workspace_id {
                        continue;
                    }
                    if ti.entity_type != "memory" {
                        continue;
                    }
                    let ti_term_lower = ti.term.to_lowercase();
                    if !query_terms.contains(&ti_term_lower) {
                        continue;
                    }
                    // Count distinct entities per term for IDF
                    let _key = (ti.entity_id.clone(), ti_term_lower.clone());
                    entity_terms
                        .entry(ti.entity_id.clone())
                        .or_default()
                        .push((ti_term_lower.clone(), ti.term_frequency, ti.doc_length));
                    *term_doc_freq.entry(ti_term_lower).or_insert(0) += 1;
                }

                if entity_terms.is_empty() {
                    continue;
                }

                // Count total documents in workspace for IDF
                let total_docs = ctx
                    .db
                    .term_index()
                    .iter()
                    .filter(|ti| ti.workspace_id == workspace_id && ti.entity_type == "memory")
                    .map(|ti| ti.entity_id.clone())
                    .collect::<std::collections::HashSet<_>>()
                    .len()
                    .max(1) as usize;

                // Compute average doc length
                let mut total_tokens: u64 = 0;
                let mut doc_count: u64 = 0;
                for ti in ctx.db.term_index().iter().take(crate::MAX_RESULTS) {
                    if ti.workspace_id == workspace_id && ti.entity_type == "memory" {
                        total_tokens += ti.doc_length as u64;
                        doc_count += 1;
                    }
                }
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
                        .map(|m| m.content.clone())
                        .unwrap_or_default();

                    scored.push((entity_id.clone(), content, total_score));
                }

                // Sort by BM25 score descending and take top limit
                scored.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));
                let mut _count: u32 = 0;
                for (entity_id, content, bm25) in &scored {
                    if _count >= limit {
                        break;
                    }
                    // Cap score to [0, 1] range
                    let score = bm25.max(0.0).min(1.0);

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
                    _count += 1;
                }
            }

            "graph" => {
                // Phase 1: find nodes whose label or summary matches query terms
                let matching_node_ids: Vec<String> = ctx
                    .db
                    .kg_node()
                    .iter()
                    .filter(|n| n.workspace_id == workspace_id)
                    .take(MAX_RESULTS)
                    .filter(|n| {
                        let label_lower = n.label.to_lowercase();
                        let summary_lower = n.summary.to_lowercase();
                        query_terms
                            .iter()
                            .any(|t| label_lower.contains(t) || summary_lower.contains(t))
                    })
                    .map(|n| n.id.clone())
                    .collect();

                let mut _count: u32 = 0;
                for node_id in &matching_node_ids {
                    if _count >= limit {
                        break;
                    }
                    // Find edges that touch this node
                    let edges: Vec<_> = ctx
                        .db
                        .kg_edge()
                        .iter()
                        .filter(|e| {
                            e.workspace_id == workspace_id
                                && (e.source_node_id == *node_id || e.target_node_id == *node_id)
                        })
                        .collect();

                    for edge in &edges {
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
                                content: format!("{}: {}", node.label, node.summary),
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
                let mut memories: Vec<_> = ctx
                    .db
                    .memory()
                    .iter()
                    .filter(|m| m.workspace_id == workspace_id)
                    .take(crate::MAX_RESULTS)
                    .filter(|m| {
                        if !memory_type.is_empty() && m.memory_type != memory_type {
                            return false;
                        }
                        if !tier.is_empty() && m.tier != tier {
                            return false;
                        }
                        true
                    })
                    .collect();

                // Most recent first
                memories.sort_by(|a, b| b.created_at.cmp(&a.created_at));

                let mut _count: u32 = 0;
                for m in &memories {
                    if _count >= limit {
                        break;
                    }
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
                        content: m.content.clone(),
                        score,
                        strategy: "temporal".to_string(),
                        context_json,
                        created_at: now,
                    });
                    _count += 1;
                }
            }

            _ => {
                return Err(format!("Unknown strategy '{}'", strategy));
            }
        }
    }

    // ── Score Normalization REMOVED ────────────────────────────────
    // Min-max normalization was done here but the Python SDK's fusion
    // pipeline (client.py search()) does its own per-strategy min-max
    // before weighted fusion. Double normalization flattened score
    // distributions. The SDK handles it correctly. (Removed Jun 2026.)

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
            .iter()
            .take(MAX_RESULTS)
            .filter(|r| r.query_hash == qhash && r.workspace_id == workspace_id)
            .collect();

        if all_rows.len() >= 2 && !query_emb.is_empty() {
            use std::collections::HashMap;

            // Build embedding lookup: entity_id → Vec<f64>
            let mut emb_cache: HashMap<String, Vec<f64>> = HashMap::new();
            for si in ctx.db.search_index().iter()
                .filter(|si| si.workspace_id == workspace_id)
                .take(MAX_RESULTS)
            {
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
        .iter().take(crate::MAX_RESULTS)
        .any(|r| r.workspace_id == workspace_id && r.query_hash == query_hash);

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

    for edge in ctx.db.kg_edge().iter().take(crate::MAX_RESULTS) {
        if edge.workspace_id != workspace_id {
            continue;
        }
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
    sorted.sort_by(|a, b| b.1.cmp(&a.1));
    sorted.truncate(top_n as usize);

    // Remove previous GodNode entries for this workspace
    let old: Vec<_> = ctx
        .db
        .god_node()
        .iter()
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
/// Iterates all indexed memories (entity_type=\"memory\") across ALL workspaces,
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
}
