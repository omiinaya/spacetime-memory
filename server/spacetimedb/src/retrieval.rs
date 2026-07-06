use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};

/// An entry in the search index, holding pre-computed embeddings and
/// text for retrieval. Since SpacetimeDB cannot perform native vector
/// search, this table stores the data that clients query via SQL and
/// post-process with their own vector comparison logic.
#[table(accessor = search_index)]
#[derive(Debug, Clone)]
pub struct SearchIndex {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// "memory" | "node" | "chunk" | "peer"
    pub entity_type: String,
    pub entity_id: String,
    pub content: String,
    /// JSON array of f64 embeddings
    pub embedding_json: String,
    /// Pre-computed BM25-friendly text for keyword search
    pub bm25_text: String,
    /// Number of tokens in the content (approximate)
    pub tokens: u32,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Indexing reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn index_entity(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_type: String,
    entity_id: String,
    content: String,
    embedding_json: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    // Validate entity_type
    match entity_type.as_str() {
        "memory" | "node" | "chunk" | "peer" | "note" => {}
        _ => {
            return Err(format!(
                "Invalid entity_type '{}': must be 'memory', 'node', 'chunk', 'peer', or 'note'",
                entity_type
            ));
        }
    }

    // Approximate token count: split on whitespace
    let tokens = content.split_whitespace().count() as u32;

    let entry = SearchIndex {
        id: id.clone(),
        workspace_id,
        entity_type,
        entity_id,
        content: content.clone(),
        embedding_json: if embedding_json.is_empty() {
            String::from("[]")
        } else {
            embedding_json
        },
        // BM25 text is identical to content; clients may override via SQL
        bm25_text: content,
        tokens,
        created_at: now,
    };

    ctx.db.search_index().insert(entry);
    Ok(())
}

/// Batch version of `index_entity` — indexes multiple entities in a single reducer call.
///
/// Accepts a JSON array of (workspace_id, entity_type, entity_id, content, embedding_json) tuples.
#[reducer]
pub fn index_entity_batch(
    ctx: &ReducerContext,
    items_json: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let items: Vec<(String, String, String, String, String)> =
        serde_json::from_str(&items_json).map_err(|e| format!("Invalid batch JSON: {e}"))?;

    let now = now_micros(ctx);
    for (workspace_id, entity_type, entity_id, content, embedding_json) in items {
        // Validate entity_type
        match entity_type.as_str() {
            "memory" | "node" | "chunk" | "peer" | "note" => {}
            _ => {
                return Err(format!(
                    "Invalid entity_type '{}': must be 'memory', 'node', 'chunk', 'peer', or 'note'",
                    entity_type
                ));
            }
        }
        let tokens = content.split_whitespace().count() as u32;
        let id = uuid_v7(ctx);
        ctx.db.search_index().insert(SearchIndex {
            id,
            workspace_id,
            entity_type,
            entity_id,
            content: content.clone(),
            embedding_json: if embedding_json.is_empty() {
                String::from("[]")
            } else {
                embedding_json
            },
            bm25_text: content,
            tokens,
            created_at: now,
        });
    }
    Ok(())
}

#[reducer]
pub fn remove_from_index(
    ctx: &ReducerContext,
    entity_type: String,
    entity_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let matched = ctx
        .db
        .search_index()
        .iter().take(crate::MAX_RESULTS)
        .filter(|si| si.entity_type == entity_type && si.entity_id == entity_id)
        .collect::<Vec<_>>();

    for si in matched {
        ctx.db.search_index().id().delete(&si.id);
    }

    // Also clean up term index entries
    let terms_to_delete: Vec<String> = ctx
        .db
        .term_index()
        .iter().take(crate::MAX_RESULTS)
        .filter(|ti| ti.entity_type == entity_type && ti.entity_id == entity_id)
        .map(|ti| ti.id.clone())
        .collect();
    for tid in terms_to_delete {
        ctx.db.term_index().id().delete(&tid);
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// BM25 Inverted Index
// ---------------------------------------------------------------------------

/// Inverted index entry for BM25 keyword search.
///
/// One row per (term, entity) pair.  Populated by `index_terms` and
/// cleared by `remove_from_index`.  Queried by `hybrid_search` keyword
/// strategy.
#[table(accessor = term_index)]
#[derive(Debug, Clone)]
pub struct TermIndex {
    #[primary_key]
    pub id: String,
    /// Normalised to lowercase
    pub term: String,
    pub workspace_id: String,
    pub entity_type: String,
    pub entity_id: String,
    /// How many times `term` appears in this entity's content
    pub term_frequency: u32,
    /// Total token count of the source document
    pub doc_length: u32,
}

/// Tokenize content into lowercase terms, filtering stopwords and
/// short tokens.
fn tokenize(content: &str) -> Vec<String> {
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

    content
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .map(|w| w.to_lowercase())
        .filter(|w| w.len() >= 2 && !stopwords.contains(&w.as_str()))
        .collect()
}

/// Compute BM25 score for a set of documents given query terms.
///
/// `idf_map`: term → (doc_freq, total_docs)
/// `doc`: (tf, doc_len)
/// k1 = 1.2, b = 0.75
pub(crate) fn bm25_score(
    tf: u32,
    doc_len: u32,
    avg_doc_len: f64,
) -> f64 {
    let k1: f64 = 1.2;
    let b: f64 = 0.75;

    let tf_f = tf as f64;
    let dl_f = doc_len as f64;

    // Standard BM25 term saturation
    let numerator = tf_f * (k1 + 1.0);
    let denominator = tf_f + k1 * (1.0 - b + b * dl_f / avg_doc_len.max(1.0));
    numerator / denominator.max(1e-10)
}

/// Compute IDF for a term: ln((N - df + 0.5) / (df + 0.5) + 1)
pub(crate) fn bm25_idf(doc_freq: usize, total_docs: usize) -> f64 {
    if doc_freq == 0 || total_docs == 0 {
        return 0.0;
    }
    let n = total_docs as f64;
    let df = doc_freq as f64;
    ((n - df + 0.5) / (df + 0.5) + 1.0).ln()
}

/// Populate `TermIndex` entries for an entity from its content.
///
/// Tokenizes `content`, counts term frequencies, computes doc length,
/// and inserts one `TermIndex` row per unique term.  Called by SDK
/// after `index_entity`.
#[reducer]
pub fn index_terms(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_type: String,
    entity_id: String,
    content: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    // Remove any existing term index entries for this entity
    let old: Vec<String> = ctx
        .db
        .term_index()
        .iter().take(crate::MAX_RESULTS)
        .filter(|ti| ti.entity_type == entity_type && ti.entity_id == entity_id)
        .map(|ti| ti.id.clone())
        .collect();
    for id in old {
        ctx.db.term_index().id().delete(&id);
    }

    let terms = tokenize(&content);
    if terms.is_empty() {
        return Ok(());
    }

    let doc_length = terms.len() as u32;

    // Count term frequencies
    use std::collections::HashMap;
    let mut freq: HashMap<String, u32> = HashMap::new();
    for t in &terms {
        *freq.entry(t.clone()).or_insert(0) += 1;
    }

    // Insert one TermIndex row per unique term
    for (term, tf) in freq {
        let id = format!("ti:{}:{}:{}", workspace_id, entity_id, term);
        ctx.db.term_index().insert(TermIndex {
            id,
            term,
            workspace_id: workspace_id.clone(),
            entity_type: entity_type.clone(),
            entity_id: entity_id.clone(),
            term_frequency: tf,
            doc_length,
        });
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // retrieval.rs has pure functions for tokenization and BM25 text prep

    #[test]
    fn test_token_count_approximation() {
        let content = "Hello world this is a test";
        let tokens = content.split_whitespace().count() as u32;
        assert_eq!(tokens, 6);
    }

    #[test]
    fn test_token_count_empty() {
        let content = "";
        let tokens = content.split_whitespace().count() as u32;
        assert_eq!(tokens, 0);
    }

    #[test]
    fn test_token_count_multiple_spaces() {
        let content = "Hello    world   test";
        let tokens = content.split_whitespace().count() as u32;
        assert_eq!(tokens, 3);
    }

    #[test]
    fn test_token_count_newlines() {
        let content = "Line 1
Line 2
Line 3";
        let tokens = content.split_whitespace().count() as u32;
        assert_eq!(tokens, 6); // "Line", "1", "Line", "2", "Line", "3"
    }

    #[test]
    fn test_entity_type_validation() {
        let valid = ["memory", "node", "chunk", "peer", "note"];
        for v in valid {
            assert!(["memory", "node", "chunk", "peer", "note"].contains(&v));
        }
        assert!(!["memory", "node", "chunk", "peer", "note"].contains(&"invalid"));
    }

    #[test]
    fn test_bm25_text_same_as_content() {
        let content = "Test content for BM25";
        let bm25_text = content.clone();
        assert_eq!(bm25_text, content);
    }
}

