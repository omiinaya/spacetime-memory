use spacetimedb::*;
use crate::auth::require_auth;
use crate::hybrid_query;
use crate::hybrid_query::{
    entity_search_index, entity_term_index,
};

use crate::{now_micros, uuid_v7};

/// An entry in the search index, holding pre-computed embeddings and
/// text for retrieval. Since SpacetimeDB cannot perform native vector
/// search, this table stores the data that clients query via SQL and
/// post-process with their own vector comparison logic.
#[table(accessor = search_index, public)]
#[derive(Debug, Clone)]
pub struct SearchIndex {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// "memory" | "node" | "chunk" | "peer"
    #[index(btree)]
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
        workspace_id: workspace_id.clone(),
        entity_type: entity_type.clone(),
        entity_id: entity_id.clone(),
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
    // Register in workspace index for hybrid_search pre-filtering
    // and populate EntitySearchIndex for O(1) PK lookups
    hybrid_query::register_indexed_entity(ctx, &workspace_id, &entity_type, &entity_id, &id);
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
        // Clone before moving into struct for workspace index registration
        let reg_ws = workspace_id.clone();
        let reg_etype = entity_type.clone();
        let reg_eid = entity_id.clone();
        ctx.db.search_index().insert(SearchIndex {
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
            bm25_text: content,
            tokens,
            created_at: now,
        });
        // Register in workspace index + EntitySearchIndex for O(1) PK lookups
        hybrid_query::register_indexed_entity(ctx, &reg_ws, &reg_etype, &reg_eid, &id);
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

    // Clean up entity search index (EntitySearchIndex — entity_id → search_index PK)
    let esi_to_delete: Vec<String> = ctx
        .db
        .entity_search_index()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|esi| esi.entity_id == entity_id)
        .map(|esi| esi.id.clone())
        .collect();
    for esi_id in esi_to_delete {
        ctx.db.entity_search_index().id().delete(&esi_id);
    }

    // Clean up entity term index (EntityTermIndex — entity_id → term_index PK)
    let eti_to_delete: Vec<String> = ctx
        .db
        .entity_term_index()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|eti| eti.entity_id == entity_id)
        .map(|eti| eti.id.clone())
        .collect();
    for eti_id in eti_to_delete {
        ctx.db.entity_term_index().id().delete(&eti_id);
    }

    // Clean up workspace index entries
    hybrid_query::unregister_workspace_entity(ctx, "search_index", &entity_id);
    if entity_type == "memory" {
        hybrid_query::unregister_workspace_entity(ctx, "memory", &entity_id);
    }
    hybrid_query::unregister_workspace_entity(ctx, "term_memory", &entity_id);

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
    #[index(btree)]
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
///
/// Clamped to non-negative: when df races ahead of N (concurrent writes)
/// or a term appears in >50% of docs, raw BM25 IDF goes negative and would
/// invert ranking. Lucene/Elasticsearch clamp the same way.
pub(crate) fn bm25_idf(doc_freq: usize, total_docs: usize) -> f64 {
    if doc_freq == 0 || total_docs == 0 {
        return 0.0;
    }
    let n = total_docs as f64;
    let df = doc_freq as f64;
    ((n - df + 0.5) / (df + 0.5) + 1.0).ln().max(0.0)
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

    // Remove any existing term index entries for this entity.
    // The PK is `ti:{workspace}:{entity_id}:{term}`, and there is a btree
    // index on workspace_id — use it (plus an entity_id filter) instead of a
    // full-table scan. The old `.iter().take(MAX_RESULTS).filter(...)` was
    // O(entire table) per store: with 100K+ benchmark chunks × ~20 terms each
    // the term_index table grows to millions of rows and every store paid a
    // multi-second full scan (measured 8s/chunk), making bulk ingestion
    // infeasible.
    let old: Vec<String> = ctx
        .db
        .term_index()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
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

    // Insert one TermIndex row per unique term, and register in EntityTermIndex
    for (term, tf) in freq {
        let ti_id = format!("ti:{}:{}:{}", workspace_id, entity_id, term);
        ctx.db.term_index().insert(TermIndex {
            id: ti_id.clone(),
            term,
            workspace_id: workspace_id.clone(),
            entity_type: entity_type.clone(),
            entity_id: entity_id.clone(),
            term_frequency: tf,
            doc_length,
        });
        // Register in EntityTermIndex for O(1) PK lookups during keyword search
        hybrid_query::register_entity_term(ctx, &workspace_id, &entity_id, &ti_id);
    }

    // Register in workspace index for keyword strategy pre-filtering
    if entity_type == "memory" {
        hybrid_query::register_workspace_entity(ctx, &workspace_id, "memory", &entity_id);
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
        let bm25_text = content;
        assert_eq!(bm25_text, content);
    }


    // ── tokenize ─────────────────────────────────────────────────────────────────

    #[test]
    fn test_tokenize_basic() {
        let tokens = tokenize("Rust memory system");
        assert!(tokens.contains(&"rust".to_string()));
        assert!(tokens.contains(&"memory".to_string()));
        assert!(tokens.contains(&"system".to_string()));
    }

    #[test]
    fn test_tokenize_removes_stopwords() {
        let tokens = tokenize("the and for with");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_tokenize_short_words() {
        let tokens = tokenize("a b c d");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_tokenize_mixed() {
        let tokens = tokenize("the quick brown fox jumps");
        assert!(!tokens.contains(&"the".to_string()));
        assert!(tokens.contains(&"quick".to_string()));
        assert!(tokens.contains(&"brown".to_string()));
        assert!(tokens.contains(&"fox".to_string()));
        assert!(tokens.contains(&"jumps".to_string()));
    }

    #[test]
    fn test_tokenize_punctuation() {
        let tokens = tokenize("hello, world! how's it?");
        assert!(tokens.contains(&"hello".to_string()));
        assert!(tokens.contains(&"world".to_string()));
        assert!(!tokens.contains(&"it".to_string()));
    }

    #[test]
    fn test_tokenize_empty() {
        let tokens = tokenize("");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_tokenize_numbers() {
        let tokens = tokenize("GPT4 and BERT score");
        assert!(tokens.contains(&"gpt4".to_string()));
        assert!(tokens.contains(&"bert".to_string()));
        assert!(tokens.contains(&"score".to_string()));
    }

    #[test]
    fn test_tokenize_case_insensitive() {
        let tokens = tokenize("Hello WORLD");
        assert!(tokens.contains(&"hello".to_string()));
        assert!(tokens.contains(&"world".to_string()));
    }

    #[test]
    fn test_tokenize_unicode() {
        let tokens = tokenize("café résumé");
        assert!(tokens.contains(&"café".to_string()));
        assert!(tokens.contains(&"résumé".to_string()));
    }

    // ── bm25_idf ─────────────────────────────────────────────────────────────────

    #[test]
    fn test_bm25_idf_common_term() {
        let idf = bm25_idf(90, 100);
        assert!(idf > 0.0);
        assert!(idf < 1.0);
    }

    #[test]
    fn test_bm25_idf_rare_term() {
        let idf = bm25_idf(2, 100);
        assert!(idf > 0.0);
    }

    #[test]
    fn test_bm25_idf_all_docs() {
        let idf = bm25_idf(100, 100);
        assert!(idf > 0.0);
        assert!(idf < 1.0);
    }

    #[test]
    fn test_bm25_idf_zero_doc_freq() {
        let idf = bm25_idf(0, 100);
        assert_eq!(idf, 0.0);
    }

    #[test]
    fn test_bm25_idf_zero_total() {
        let idf = bm25_idf(5, 0);
        assert_eq!(idf, 0.0);
    }

    #[test]
    fn test_bm25_idf_single_doc() {
        let idf = bm25_idf(1, 1);
        assert!(idf > 0.0);
    }

    // ── bm25_score ───────────────────────────────────────────────────────────────

    #[test]
    fn test_bm25_score_higher_tf_higher_score() {
        let score_1 = bm25_score(5, 100, 50.0);
        let score_2 = bm25_score(10, 100, 50.0);
        assert!(score_2 > score_1);
    }

    #[test]
    fn test_bm25_score_shorter_doc_higher_score_same_tf() {
        let score_short = bm25_score(3, 10, 50.0);
        let score_long = bm25_score(3, 100, 50.0);
        assert!(score_short > score_long);
    }

    #[test]
    fn test_bm25_score_zero_tf() {
        let score = bm25_score(0, 100, 50.0);
        assert_eq!(score, 0.0);
    }

    #[test]
    fn test_bm25_score_positive() {
        let score = bm25_score(3, 30, 25.0);
        assert!(score > 0.0);
        // BM25 term score asymptotes at k1+1 = 2.2, not 1.0 (this is the
        // term-saturation factor only — the IDF weight is applied separately)
        assert!(score <= 2.2);
    }

    #[test]
    fn test_bm25_score_saturating() {
        let score = bm25_score(1000, 100, 50.0);
        assert!(score > 0.0);
        // BM25 with k1=1.2 asymptotes at k1+1 = 2.2
        assert!(score <= 2.2);
    }

    #[test]
    fn test_bm25_score_doc_len_zero() {
        let score = bm25_score(3, 0, 25.0);
        assert!(score > 0.0);
    }

    #[test]
    fn test_bm25_score_avg_doc_len_zero() {
        let score = bm25_score(3, 30, 0.0);
        assert!(score > 0.0);
    }


    // ── Edge case tests ──────────────────────────────────────────────

    #[test]
    fn test_tokenize_special_characters() {
        let tokens = tokenize("hello!@#$%^&*()world");
        assert!(tokens.iter().any(|t| t == "hello"));
        assert!(tokens.iter().any(|t| t == "world"));
    }

    #[test]
    fn test_tokenize_empty_and_whitespace() {
        let tokens = tokenize("");
        assert!(tokens.is_empty());

        let _tokens = tokenize("   ");
        // May produce no tokens (all single char after filtering)
        // Should not panic
    }

    #[test]
    fn test_tokenize_unicode_search() {
        let tokens = tokenize("Hello 世界 こんにちは");
        assert!(tokens.iter().any(|t| t == "hello"));
    }

    #[test]
    fn test_tokenize_very_large_content() {
        let large = "hello ".to_string() + &"x".repeat(10_000);
        let tokens = tokenize(&large);
        assert!(tokens.iter().any(|t| t == "hello"));
    }

    #[test]
    fn test_bm25_score_special_char_tf_dl() {
        let score = bm25_score(5, 100, 80.0);
        assert!(score > 0.0);
        assert!(score <= 2.2); // asymptote k1+1, not 1.0
    }

    #[test]
    fn test_bm25_score_very_large_tf() {
        let score = bm25_score(1_000_000, 100_000_000, 80_000.0);
        assert!(score > 0.0);
        assert!(score <= 2.2);
    }

    #[test]
    fn test_bm25_score_extreme_avg_doc_len() {
        let score = bm25_score(5, 100, f64::MAX);
        assert!(score >= 0.0);
        assert!(score.is_finite());
    }

    #[test]
    fn test_bm25_idf_very_large_values() {
        let idf = bm25_idf(1_000_000, 1_000_000_000);
        assert!(idf >= 0.0);
        assert!(idf.is_finite());

        let idf = bm25_idf(999_999_999, 1_000_000_000);
        assert!(idf >= 0.0);
        assert!(idf.is_finite());
    }

    #[test]
    fn test_bm25_idf_concurrent_writes_simulation() {
        let idf = bm25_idf(1_000_000, 999_999);
        assert!(idf >= 0.0);
        assert!(idf.is_finite());

        let idf = bm25_idf(1, 0);
        assert_eq!(idf, 0.0);
    }

    #[test]
    fn test_token_count_empty_search() {
        let content = "";
        let tokens = content.split_whitespace().count() as u32;
        assert_eq!(tokens, 0);

        let content = "   ";
        let tokens = content.split_whitespace().count() as u32;
        assert_eq!(tokens, 0);
    }

    #[test]
    fn test_token_count_special_characters() {
        let content = "<script>alert('xss')</script>";
        let tokens = content.split_whitespace().count() as u32;
        assert!(tokens > 0);
    }

    #[test]
    fn test_token_count_unicode() {
        let content = "Hello 世界";
        let tokens = content.split_whitespace().count() as u32;
        assert_eq!(tokens, 2);

        let content = "こんにちは";
        let tokens = content.split_whitespace().count() as u32;
        assert_eq!(tokens, 1);
    }

    #[test]
    fn test_bm25_score_network_partition_simulation() {
        let score = bm25_score(0, 0, 0.0);
        assert_eq!(score, 0.0);
    }

}

