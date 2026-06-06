use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// A memory entry storing world facts, experiences, or mental models
/// for an AI agent within a workspace.
#[table(accessor = memory, public)]
#[derive(Debug, Clone)]
pub struct Memory {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub peer_id: String,
    pub observer_id: String,
    /// "world_fact" | "experience" | "mental_model"
    pub memory_type: String,
    pub content: String,
    pub summary: String,
    /// JSON array of entity references
    pub entities_json: String,
    pub confidence: f64,
    pub source_session_id: String,
    pub source_message_id: String,
    pub is_active: bool,
    pub created_at: i64,
    /// 0 = no expiry
    pub expires_at: i64,
    pub updated_at: i64,
}

#[reducer]
pub fn store_memory(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
    observer_id: String,
    memory_type: String,
    content: String,
    summary: String,
    entities_json: String,
    confidence: f64,
    source_session_id: String,
    source_message_id: String,
) -> Result<(), String> {
    let now = now_micros();
    let id = uuid_v4();

    let mem = Memory {
        id: id.clone(),
        workspace_id,
        peer_id,
        observer_id,
        memory_type,
        content,
        summary,
        entities_json,
        confidence,
        source_session_id,
        source_message_id,
        is_active: true,
        created_at: now,
        expires_at: 0,
        updated_at: now,
    };

    ctx.db.memory().insert(mem);
    Ok(())
}

#[reducer]
pub fn update_memory(
    ctx: &ReducerContext,
    id: String,
    content: String,
    summary: String,
    confidence: f64,
) -> Result<(), String> {
    let mut mem = ctx
        .db
        .memory()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Memory '{}' not found", id))?;

    mem.content = content;
    mem.summary = summary;
    mem.confidence = confidence;
    mem.updated_at = now_micros();

    ctx.db.memory().id().update(mem);
    Ok(())
}

#[reducer]
pub fn deactivate_memory(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let mut mem = ctx
        .db
        .memory()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Memory '{}' not found", id))?;

    mem.is_active = false;
    mem.updated_at = now_micros();

    ctx.db.memory().id().update(mem);
    Ok(())
}

#[reducer]
pub fn expire_memories(ctx: &ReducerContext) -> Result<(), String> {
    let now = now_micros();

    let expired: Vec<_> = ctx
        .db
        .memory()
        .iter()
        .filter(|m| m.expires_at > 0 && m.expires_at < now)
        .collect();

    for mut mem in expired {
        mem.is_active = false;
        mem.updated_at = now;
        ctx.db.memory().id().update(mem);
    }

    Ok(())
}
