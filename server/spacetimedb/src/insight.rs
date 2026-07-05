use spacetimedb::*;
use crate::auth::require_auth;

use crate::trace_span;
use crate::{now_micros, uuid_v4_uniq};
use crate::tracing::TracingSpanKind;
use crate::workspace::check_space_access;

/// An insight represents a Hindsight reflect-style reasoning result.
#[table(accessor = insight)]
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
    trace_span!(ctx, "create_insight", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v4_uniq(ctx, |id| ctx.db.insight().id().find(id).is_none(), 3);

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
})
}

#[reducer]
pub fn delete_insight(ctx: &ReducerContext, id: String) -> Result<(), String> {
    trace_span!(ctx, "delete_insight", TracingSpanKind::Write, "", {
    let _account = require_auth(ctx)?;
    let insight = ctx
        .db
        .insight()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Insight '{}' not found", id))?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &insight.workspace_id, &caller, "editor")?;

    ctx.db.insight().id().delete(&id);
    Ok(())
})
}

// ---------------------------------------------------------------------------
// MentalModel — higher-level abstractions synthesized from raw memories
// ---------------------------------------------------------------------------

/// A mental model is a higher-level abstraction, belief, pattern, heuristic,
/// or rule synthesized from a set of experiences (raw memories).
#[table(accessor = mental_model)]
#[derive(Debug, Clone)]
pub struct MentalModel {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// "mental_model", "belief", "pattern", "heuristic", "abstraction"
    pub model_type: String,
    /// The synthesized content (filled by Python LLM script)
    pub content: String,
    /// JSON array of source memory IDs
    pub source_memory_ids: String,
    /// Confidence score 0.0-1.0 (set by Python script after LLM call)
    pub confidence: f64,
    /// "pending", "completed", "failed"
    pub status: String,
    pub created_at: i64,
    pub updated_at: i64,
}

#[reducer]
pub fn synthesize_mental_models(
    ctx: &ReducerContext,
    workspace_id: String,
    memory_ids_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "synthesize_mental_models", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v4_uniq(ctx, |id| ctx.db.insight().id().find(id).is_none(), 3);

    // Validate that memory_ids_json is valid JSON
    if let Err(e) = serde_json::from_str::<Vec<String>>(&memory_ids_json) {
        return Err(format!("Invalid memory_ids_json: {}", e));
    }

    let model = MentalModel {
        id: id.clone(),
        workspace_id,
        model_type: "mental_model".to_string(),
        content: "Synthesis requested. Run mental_model_synthesis.py to generate LLM output.".to_string(),
        source_memory_ids: memory_ids_json,
        confidence: 0.5,
        status: "pending".to_string(),
        created_at: now,
        updated_at: now,
    };

    ctx.db.mental_model().insert(model);
    Ok(())
}

#[reducer]
pub fn update_mental_model(
    ctx: &ReducerContext,
    id: String,
    content: String,
    confidence: f64,
    status: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let mut model = ctx
        .db
        .mental_model()
        .id()
        .find(&id)
        .ok_or_else(|| format!("MentalModel '{}' not found", id))?;

    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &model.workspace_id, &caller, "editor")?;

    model.content = content;
    model.confidence = confidence;
    model.status = status;
    model.updated_at = now;

    ctx.db.mental_model().id().update(model);
    Ok(())
}

#[reducer]
pub fn delete_mental_model(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let model = ctx
        .db
        .mental_model()
        .id()
        .find(&id)
        .ok_or_else(|| format!("MentalModel '{}' not found", id))?;

    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &model.workspace_id, &caller, "editor")?;

    ctx.db.mental_model().id().delete(&id);
    Ok(())
}
