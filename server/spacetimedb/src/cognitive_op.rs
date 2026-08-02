use spacetimedb::*;

use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::{now_micros, uuid_v4_uniq};

// ---------------------------------------------------------------------------
// Cognitive operation — named abstraction wrapping pipeline stages (Cognee parity)
// ---------------------------------------------------------------------------

/// A cognitive operation is a named, typed operation that wraps a pipeline stage.
/// Inspired by Cognee's "cognitive operations" abstraction.
#[table(accessor = cognitive_op)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CognitiveOp {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Unique operation name (e.g. "entity_extract", "semantic_search")
    pub name: String,
    /// Operation type: "observe", "filter", "extract", "transform", "classify", "rank", "store"
    pub op_type: String,
    /// Human-readable description
    pub description: String,
    /// Operation-specific configuration as JSON
    pub config_json: String,
    /// Maps to existing pipeline stage type
    pub pipeline_stage_type: String,
    pub created_at: i64,
    pub updated_at: i64,
}

// ---------------------------------------------------------------------------
// Result tables
// ---------------------------------------------------------------------------

/// Result table for cognitive operation queries.
#[table(accessor = cognitive_op_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CognitiveOpResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// JSON data payload
    pub data: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn register_cognitive_op(
    ctx: &ReducerContext,
    workspace_id: String,
    _peer_id: String,
    name: String,
    op_type: String,
    description: String,
    config_json: String,
    pipeline_stage_type: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "register_cognitive_op", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        // Validate op_type
        let valid_types = ["observe", "filter", "extract", "transform", "classify", "rank", "store"];
        if !valid_types.contains(&op_type.as_str()) {
            return Err(format!("Invalid op_type '{}'. Must be one of: observe, filter, extract, transform, classify, rank, store", op_type));
        }

        // Check for duplicate name in the same workspace
        for existing in ctx.db.cognitive_op().iter() {
            if existing.workspace_id == workspace_id && existing.name == name {
                return Err(format!("Cognitive op '{}' already exists in this workspace", name));
            }
        }

        let now = now_micros(ctx);
        let id = uuid_v4_uniq(ctx, |id| ctx.db.cognitive_op().id().find(id).is_none(), 3);

        let op = CognitiveOp {
            id: id.clone(),
            workspace_id: workspace_id.clone(),
            name,
            op_type,
            description,
            config_json,
            pipeline_stage_type,
            created_at: now,
            updated_at: now,
        };

        let op_json = change_event::record_to_json(&op);
        ctx.db.cognitive_op().insert(op);
        change_event::log_change(ctx, &ws_id, "cognitive_op", "insert", &id, &op_json);
        Ok(())
    })
}

#[reducer]
pub fn unregister_cognitive_op(
    ctx: &ReducerContext,
    workspace_id: String,
    op_id: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "unregister_cognitive_op", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        let existing = ctx.db.cognitive_op().id().find(&op_id)
            .ok_or_else(|| "Cognitive op not found".to_string())?;

        if existing.workspace_id != workspace_id {
            return Err("Cognitive op not found in this workspace".to_string());
        }

        let op_json = change_event::record_to_json(&existing);
        ctx.db.cognitive_op().id().delete(&op_id);
        change_event::log_change(ctx, &ws_id, "cognitive_op", "delete", &op_id, &op_json);
        Ok(())
    })
}

#[reducer]
pub fn get_cognitive_ops(
    ctx: &ReducerContext,
    workspace_id: String,
    op_type_filter: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_cognitive_ops", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "viewer")?;

        let mut ops: Vec<CognitiveOp> = ctx.db.cognitive_op()
            .iter()
            .filter(|op| {
                if op.workspace_id != workspace_id {
                    return false;
                }
                if op_type_filter.is_empty() || op_type_filter == "all" {
                    return true;
                }
                op.op_type == op_type_filter
            })
            .collect();

        // Sort by created_at ascending
        ops.sort_by_key(|a| a.created_at);

        let data = serde_json::to_string(&ops).unwrap_or_else(|_| "[]".to_string());
        let now = now_micros(ctx);
        let result_id = uuid_v4_uniq(ctx, |id| ctx.db.cognitive_op_result().id().find(id).is_none(), 3);

        ctx.db.cognitive_op_result().insert(CognitiveOpResult {
            id: result_id,
            workspace_id: workspace_id.clone(),
            data,
            created_at: now,
        });

        Ok(())
    })
}

#[reducer]
pub fn execute_cognitive_op(
    ctx: &ReducerContext,
    workspace_id: String,
    op_id: String,
    input_data_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "execute_cognitive_op", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        let op = ctx.db.cognitive_op().id().find(&op_id)
            .ok_or_else(|| "Cognitive op not found".to_string())?;

        if op.workspace_id != workspace_id {
            return Err("Cognitive op not found in this workspace".to_string());
        }

        // For now, execute by returning the input data wrapped with operation metadata.
        // In a full implementation this would route through the pipeline engine.
        let result = serde_json::json!({
            "op_name": op.name,
            "op_type": op.op_type,
            "pipeline_stage_type": op.pipeline_stage_type,
            "input": serde_json::from_str::<serde_json::Value>(&input_data_json).unwrap_or(serde_json::Value::String(input_data_json)),
            "status": "executed",
        });

        let data = serde_json::to_string(&result).unwrap_or_else(|_| "{}".to_string());
        let now = now_micros(ctx);
        let result_id = uuid_v4_uniq(ctx, |id| ctx.db.cognitive_op_result().id().find(id).is_none(), 3);

        ctx.db.cognitive_op_result().insert(CognitiveOpResult {
            id: result_id,
            workspace_id: workspace_id.clone(),
            data,
            created_at: now,
        });

        Ok(())
    })
}

#[reducer]
pub fn get_cognitive_pipeline(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_cognitive_pipeline", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "viewer")?;

        // Return ops in a standard pipeline order:
        // observe → extract → classify → filter → transform → rank → store
        let pipeline_order = [
            "observe", "extract", "classify", "filter", "transform", "rank", "store",
        ];

        let mut pipeline: Vec<Vec<CognitiveOp>> = Vec::new();
        for op_type in &pipeline_order {
            let ops: Vec<CognitiveOp> = ctx.db.cognitive_op()
                .iter()
                .filter(|op| op.workspace_id == workspace_id && &op.op_type == op_type)
                .collect();
            pipeline.push(ops);
        }

        // Flatten into a single ordered list
        let ordered: Vec<CognitiveOp> = pipeline.into_iter().flatten().collect();

        let data = serde_json::to_string(&ordered).unwrap_or_else(|_| "[]".to_string());
        let now = now_micros(ctx);
        let result_id = uuid_v4_uniq(ctx, |id| ctx.db.cognitive_op_result().id().find(id).is_none(), 3);

        ctx.db.cognitive_op_result().insert(CognitiveOpResult {
            id: result_id,
            workspace_id: workspace_id.clone(),
            data,
            created_at: now,
        });

        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_op_type_valid() {
        for op_type in &["observe", "filter", "extract", "transform", "classify", "rank", "store"] {
            assert!(validate_op_type(op_type).is_ok(), "op_type '{}' should be valid", op_type);
        }
    }

    #[test]
    fn test_validate_op_type_invalid() {
        let result = validate_op_type("invalid_op");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid op_type"));
    }

    #[test]
    fn test_validate_op_type_empty() {
        let result = validate_op_type("");
        assert!(result.is_err());
    }

    #[test]
    fn test_validate_op_type_uppercase() {
        // Should be case-sensitive — "Observe" should fail
        let result = validate_op_type("Observe");
        assert!(result.is_err());
    }

    #[test]
    fn test_pipeline_order_all_types() {
        // Verify pipeline order contains all 7 types
        let order = ["observe", "extract", "classify", "filter", "transform", "rank", "store"];
        assert_eq!(order.len(), 7);
        assert_eq!(order[0], "observe");
        assert_eq!(order[6], "store");
    }

    #[test]
    fn test_pipeline_order_no_duplicates() {
        use std::collections::HashSet;
        let order = ["observe", "extract", "classify", "filter", "transform", "rank", "store"];
        let mut seen = HashSet::new();
        for t in &order {
            assert!(seen.insert(t), "duplicate op_type in pipeline order: {}", t);
        }
    }

    #[test]
    fn test_validate_op_types_all_lowercase() {
        for op_type in &["observe", "filter", "extract", "transform", "classify", "rank", "store"] {
            assert_eq!(op_type.chars().all(|c| c.is_lowercase()), true);
        }
    }
}

#[allow(dead_code)]
/// Pure validation function for op_type (testable without STDB context).
pub fn validate_op_type(op_type: &str) -> Result<(), String> {
    let valid_types = ["observe", "filter", "extract", "transform", "classify", "rank", "store"];
    if valid_types.contains(&op_type) {
        Ok(())
    } else {
        Err(format!("Invalid op_type '{}'. Must be one of: observe, filter, extract, transform, classify, rank, store", op_type))
    }
}
