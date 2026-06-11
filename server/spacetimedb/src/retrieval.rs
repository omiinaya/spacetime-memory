use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v4};

/// An entry in the search index, holding pre-computed embeddings and
/// text for retrieval. Since SpacetimeDB cannot perform native vector
/// search, this table stores the data that clients query via SQL and
/// post-process with their own vector comparison logic.
#[table(accessor = search_index, public)]
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
    let id = uuid_v4(ctx);

    // Validate entity_type
    match entity_type.as_str() {
        "memory" | "node" | "chunk" | "peer" => {}
        _ => {
            return Err(format!(
                "Invalid entity_type '{}': must be 'memory', 'node', 'chunk', or 'peer'",
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
        .iter()
        .filter(|si| si.entity_type == entity_type && si.entity_id == entity_id)
        .collect::<Vec<_>>();

    for si in matched {
        ctx.db.search_index().id().delete(&si.id);
    }

    Ok(())
}
