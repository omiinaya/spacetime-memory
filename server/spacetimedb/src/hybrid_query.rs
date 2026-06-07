use spacetimedb::*;

use crate::knowledge_graph::{kg_edge, kg_node};
use crate::memory::memory;
use crate::retrieval::search_index;
use crate::{now_micros, uuid_v4};

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

/// Count how many of the given query terms appear in `text` (case-insensitive).
fn term_match_count(text: &str, terms: &[&str]) -> usize {
    let lower = text.to_lowercase();
    terms.iter().filter(|t| lower.contains(*t)).count()
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
) -> Result<(), String> {
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
                let mut count: u32 = 0;
                for si in ctx.db.search_index().iter() {
                    if count >= limit {
                        break;
                    }
                    if si.workspace_id != workspace_id {
                        continue;
                    }
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

                    ctx.db.hybrid_result().insert(HybridResult {
                        id: uuid_v4(ctx),
                        workspace_id: workspace_id.clone(),
                        query_hash: qhash.clone(),
                        entity_type: si.entity_type.clone(),
                        entity_id: si.entity_id.clone(),
                        content: si.content.clone(),
                        score,
                        strategy: "semantic".to_string(),
                        created_at: now,
                    });
                    count += 1;
                }
            }

            "keyword" => {
                let mut count: u32 = 0;
                for m in ctx.db.memory().iter() {
                    if count >= limit {
                        break;
                    }
                    if m.workspace_id != workspace_id {
                        continue;
                    }
                    if !memory_type.is_empty() && m.memory_type != memory_type {
                        continue;
                    }
                    if !tier.is_empty() && m.tier != tier {
                        continue;
                    }
                    let content_lower = m.content.to_lowercase();
                    if !query_terms.iter().any(|t| content_lower.contains(t)) {
                        continue;
                    }
                    let matched = term_match_count(&m.content, &query_terms);
                    let base_score = if !query_terms.is_empty() {
                        matched as f64 / query_terms.len() as f64
                    } else {
                        0.0
                    };
                    // Weight by trust_score
                    let score = base_score * (0.5 + m.trust_score * 0.5);

                    ctx.db.hybrid_result().insert(HybridResult {
                        id: uuid_v4(ctx),
                        workspace_id: workspace_id.clone(),
                        query_hash: qhash.clone(),
                        entity_type: "memory".to_string(),
                        entity_id: m.id.clone(),
                        content: m.content.clone(),
                        score,
                        strategy: "keyword".to_string(),
                        created_at: now,
                    });
                    count += 1;
                }
            }

            "graph" => {
                // Phase 1: find nodes whose label or summary matches query terms
                let matching_node_ids: Vec<String> = ctx
                    .db
                    .kg_node()
                    .iter()
                    .filter(|n| {
                        if n.workspace_id != workspace_id {
                            return false;
                        }
                        let label_lower = n.label.to_lowercase();
                        let summary_lower = n.summary.to_lowercase();
                        query_terms
                            .iter()
                            .any(|t| label_lower.contains(t) || summary_lower.contains(t))
                    })
                    .map(|n| n.id.clone())
                    .collect();

                let mut count: u32 = 0;
                for node_id in &matching_node_ids {
                    if count >= limit {
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
                        if count >= limit {
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

                        ctx.db.hybrid_result().insert(HybridResult {
                            id: uuid_v4(ctx),
                            workspace_id: workspace_id.clone(),
                            query_hash: qhash.clone(),
                            entity_type: "node".to_string(),
                            entity_id,
                            content,
                            score,
                            strategy: "graph".to_string(),
                            created_at: now,
                        });
                        count += 1;
                    }

                    // Also include the matching node itself
                    if count < limit {
                        if let Some(node) = ctx.db.kg_node().id().find(node_id) {
                            ctx.db.hybrid_result().insert(HybridResult {
                                id: uuid_v4(ctx),
                                workspace_id: workspace_id.clone(),
                                query_hash: qhash.clone(),
                                entity_type: "node".to_string(),
                                entity_id: node.id.clone(),
                                content: format!("{}: {}", node.label, node.summary),
                                score: 0.3,
                                strategy: "graph".to_string(),
                                created_at: now,
                            });
                            count += 1;
                        }
                    }
                }
            }

            "temporal" => {
                let mut memories: Vec<_> = ctx
                    .db
                    .memory()
                    .iter()
                    .filter(|m| {
                        if m.workspace_id != workspace_id {
                            return false;
                        }
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

                let mut count: u32 = 0;
                for m in &memories {
                    if count >= limit {
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

                    ctx.db.hybrid_result().insert(HybridResult {
                        id: uuid_v4(ctx),
                        workspace_id: workspace_id.clone(),
                        query_hash: qhash.clone(),
                        entity_type: "memory".to_string(),
                        entity_id: m.id.clone(),
                        content: m.content.clone(),
                        score,
                        strategy: "temporal".to_string(),
                        created_at: now,
                    });
                    count += 1;
                }
            }

            _ => {
                return Err(format!("Unknown strategy '{}'", strategy));
            }
        }
    }

    Ok(())
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
    // Validate that results exist for this workspace+hash combination
    let exists = ctx
        .db
        .hybrid_result()
        .iter()
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
    let now = now_micros(ctx);
    let top_n = if top_n == 0 { 10 } else { top_n };

    // Count degree for every node that has at least one edge in this workspace
    let mut degree_map: std::collections::HashMap<String, u64> =
        std::collections::HashMap::new();

    for edge in ctx.db.kg_edge().iter() {
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
            id: uuid_v4(ctx),
            workspace_id: workspace_id.clone(),
            node_id: node_id.clone(),
            edge_count: *edge_count,
            computed_at: now,
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
    fn test_term_match_count_all_match() {
        let count = term_match_count("the quick brown fox", &["the", "quick", "fox"]);
        assert_eq!(count, 3);
    }

    #[test]
    fn test_term_match_count_some_match() {
        let count = term_match_count("hello world", &["hello", "missing", "world"]);
        assert_eq!(count, 2);
    }

    #[test]
    fn test_term_match_count_none() {
        let count = term_match_count("hello world", &["foo", "bar"]);
        assert_eq!(count, 0);
    }

    #[test]
    fn test_term_match_count_case_insensitive() {
        let count = term_match_count("HELLO WORLD", &["hello"]);
        assert_eq!(count, 1);
    }

    #[test]
    fn test_term_match_count_empty_terms() {
        let count = term_match_count("hello", &[]);
        assert_eq!(count, 0);
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
}
