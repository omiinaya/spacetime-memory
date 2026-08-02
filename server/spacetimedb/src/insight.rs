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
    #[index(btree)]
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
        workspace_id: workspace_id.clone(),
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
        workspace_id: workspace_id.clone(),
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
})
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


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_insight_initialization() {
        let ins = Insight {
            id: "ins_001".to_string(),
            workspace_id: "ws_001".to_string(),
            peer_id: "peer_abc".to_string(),
            content: "The system shows a pattern of failures after midnight.".to_string(),
            insight_type: "conclusion".to_string(),
            source_memory_ids_json: r#"["mem_001","mem_002"]"#.to_string(),
            confidence: 0.85,
            created_at: 1_000_000,
        };
        assert_eq!(ins.id, "ins_001");
        assert_eq!(ins.insight_type, "conclusion");
        assert_eq!(ins.confidence, 0.85);
        assert!(!ins.content.is_empty());
    }

    #[test]
    fn test_insight_types() {
        for (insight_type, desc) in [
            ("conclusion", "default type"),
            ("observation", "direct observation"),
            ("connection", "relational insight"),
            ("question", "open question"),
        ] {
            let ins = Insight {
                id: format!("ins_{}", insight_type),
                workspace_id: "ws_001".to_string(),
                peer_id: "peer_abc".to_string(),
                content: format!("Test {} insight", desc),
                insight_type: insight_type.to_string(),
                source_memory_ids_json: "[]".to_string(),
                confidence: 0.5,
                created_at: 1_000_000,
            };
            assert_eq!(ins.insight_type, insight_type);
            assert!((ins.confidence - 0.5).abs() < f64::EPSILON);
        }
    }

    #[test]
    fn test_insight_confidence_bounds() {
        let low = Insight {
            id: "ins_low".to_string(),
            workspace_id: "ws_001".to_string(),
            peer_id: "peer_abc".to_string(),
            content: "Low confidence insight".to_string(),
            insight_type: "observation".to_string(),
            source_memory_ids_json: "[]".to_string(),
            confidence: 0.0,
            created_at: 0,
        };
        let high = Insight {
            id: "ins_high".to_string(),
            workspace_id: "ws_001".to_string(),
            peer_id: "peer_abc".to_string(),
            content: "High confidence insight".to_string(),
            insight_type: "conclusion".to_string(),
            source_memory_ids_json: "[]".to_string(),
            confidence: 1.0,
            created_at: 0,
        };
        assert_eq!(low.confidence, 0.0);
        assert_eq!(high.confidence, 1.0);
    }

    #[test]
    fn test_insight_empty_source_memories() {
        let ins = Insight {
            id: "ins_empty".to_string(),
            workspace_id: "ws_001".to_string(),
            peer_id: "peer_abc".to_string(),
            content: "Insight with no source memories".to_string(),
            insight_type: "conclusion".to_string(),
            source_memory_ids_json: "[]".to_string(),
            confidence: 0.5,
            created_at: 0,
        };
        assert_eq!(ins.source_memory_ids_json, "[]");
        let ids: Vec<String> = serde_json::from_str(&ins.source_memory_ids_json).unwrap();
        assert!(ids.is_empty());
    }

    #[test]
    fn test_mental_model_initialization() {
        let model = MentalModel {
            id: "mm_001".to_string(),
            workspace_id: "ws_001".to_string(),
            model_type: "pattern".to_string(),
            content: "Users tend to ask about memory in the first 5 messages.".to_string(),
            source_memory_ids: r#"["mem_001","mem_003"]"#.to_string(),
            confidence: 0.7,
            status: "completed".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(model.model_type, "pattern");
        assert_eq!(model.status, "completed");
        assert_eq!(model.confidence, 0.7);
    }

    #[test]
    fn test_mental_model_pending_status() {
        let model = MentalModel {
            id: "mm_pending".to_string(),
            workspace_id: "ws_001".to_string(),
            model_type: "abstraction".to_string(),
            content: "Pending synthesis".to_string(),
            source_memory_ids: "[]".to_string(),
            confidence: 0.5,
            status: "pending".to_string(),
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(model.status, "pending");
        assert_eq!(model.confidence, 0.5);
    }
}
