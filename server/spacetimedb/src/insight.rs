use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// An insight represents a Hindsight reflect-style reasoning result.
#[table(accessor = insight, public)]
#[derive(Debug, Clone)]
pub struct Insight {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub peer_id: String,
    pub content: String,
    /// "conclusion" | "observation" | "connection" | "question"
    pub insight_type: String,
    /// JSON array of source memory IDs
    pub source_memory_ids_json: String,
    pub confidence: f64,
    pub created_at: i64,
}

#[reducer]
pub fn create_insight(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
    content: String,
    insight_type: String,
    source_memory_ids_json: String,
    confidence: f64,
) -> Result<(), String> {
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

    let ins = Insight {
        id: id.clone(),
        workspace_id,
        peer_id,
        content,
        insight_type,
        source_memory_ids_json,
        confidence,
        created_at: now,
    };

    ctx.db.insight().insert(ins);
    Ok(())
}

#[reducer]
pub fn delete_insight(ctx: &ReducerContext, id: String) -> Result<(), String> {
    ctx.db
        .insight()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Insight '{}' not found", id))?;

    ctx.db.insight().id().delete(&id);
    Ok(())
}
