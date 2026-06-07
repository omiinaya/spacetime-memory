use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// A memory entry storing world facts, experiences, or mental models
/// for an AI agent within a workspace.
#[table(accessor = memory, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
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

    // ---- OpenViking: Tiered contexts ----
    /// "L0"=critical, "L1"=normal, "L2"=archival
    pub tier: String,

    // ---- RetainDB: Reinforcement & Versioning ----
    /// How many times this memory has been accessed
    pub access_count: u64,
    /// Memory strength 0.0–1.0
    pub strength: f64,
    /// Version number (incremented on updates)
    pub version: u32,
    /// Temporal validity; 0 = always valid
    pub valid_from: i64,

    // ---- OpenViking: Hierarchy ----
    /// Points to a ContextDirectory; empty "" if not organised
    pub parent_directory_id: String,

    // ---- RetainDB: Consolidation ----
    /// If this memory was consolidated into another, the target memory id
    pub consolidated_to: String,

    // ---- Holographic: Trust Scoring & Feedback ----
    /// Trust score 0.0–1.0; adjusted by user feedback
    pub trust_score: f64,
    /// How many user feedback ratings received
    pub feedback_count: u32,
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
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

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

        // OpenViking + RetainDB fields
        tier: String::from("L1"),
        access_count: 0,
        strength: 0.5,
        version: 1,
        valid_from: 0,
        parent_directory_id: String::new(),
        consolidated_to: String::new(),
        trust_score: 0.5,
        feedback_count: 0,
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
    mem.updated_at = now_micros(ctx);

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
    mem.updated_at = now_micros(ctx);

    ctx.db.memory().id().update(mem);
    Ok(())
}

#[reducer]
pub fn expire_memories(ctx: &ReducerContext) -> Result<(), String> {
    let now = now_micros(ctx);

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
