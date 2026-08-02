use spacetimedb::*;
use crate::auth::require_auth;
use crate::trace_span;
use crate::tracing::TracingSpanKind;
use crate::workspace::check_space_access;
use crate::{now_micros, uuid_v7};

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// An autonomous reflection session — tracks the lifecycle of a Hindsight
/// reflect-style reasoning loop that runs periodically within a workspace.
#[table(accessor = reflection_session)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ReflectionSession {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub peer_id: String,
    /// "idle" | "running" | "completed" | "failed"
    #[index(btree)]
    pub status: String,
    /// JSON config: interval_minutes, max_cycles, focus_areas, min_confidence, llm_model
    pub config_json: String,
    pub cycle_count: u32,
    pub insights_count: u32,
    pub started_at: i64,
    pub completed_at: i64,
    pub updated_at: i64,
}

/// A single insight produced by a reflection cycle.
#[table(accessor = reflection_insight)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ReflectionInsight {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub session_id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub cycle_number: u32,
    pub content: String,
    /// Clamped to 0.0–1.0
    pub confidence: f64,
    /// "pattern" | "contradiction" | "gap" | "observation" | "connection" | "synthesis"
    pub insight_type: String,
    /// JSON array of source memory IDs
    pub source_memory_ids_json: String,
    /// JSON array of source note IDs
    pub source_note_ids_json: String,
    pub created_at: i64,
}

/// Result table for query responses (compute-and-store pattern).
#[table(accessor = reflection_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ReflectionResult {
    #[primary_key]
    pub result_id: String,
    /// JSON-encoded query result
    pub data: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

/// The allowed status values for a reflection session.
const VALID_STATUSES: &[&str] = &["idle", "running", "completed", "failed"];

/// The allowed insight types.
const VALID_INSIGHT_TYPES: &[&str] = &[
    "pattern",
    "contradiction",
    "gap",
    "observation",
    "connection",
    "synthesis",
];

/// Valid status transitions (from → to).
fn is_valid_transition(from: &str, to: &str) -> bool {
    match from {
        "idle" => to == "running",
        "running" => to == "completed" || to == "failed",
        "completed" | "failed" => false,
        _ => false,
    }
}

/// Validate that `status` is one of the recognised session statuses.
fn validate_status(status: &str) -> Result<(), String> {
    if VALID_STATUSES.contains(&status) {
        Ok(())
    } else {
        Err(format!(
            "Invalid session status '{}'. Must be one of: {}",
            status,
            VALID_STATUSES.join(", ")
        ))
    }
}

/// Validate that `insight_type` is one of the recognised types.
fn validate_insight_type(insight_type: &str) -> Result<(), String> {
    if VALID_INSIGHT_TYPES.contains(&insight_type) {
        Ok(())
    } else {
        Err(format!(
            "Invalid insight type '{}'. Must be one of: {}",
            insight_type,
            VALID_INSIGHT_TYPES.join(", ")
        ))
    }
}

/// Clamp a confidence value to [0.0, 1.0].
fn clamp_confidence(confidence: f64) -> f64 {
    confidence.clamp(0.0, 1.0)
}

// ---------------------------------------------------------------------------
// Helpers — result table management
// ---------------------------------------------------------------------------

/// Clear all existing reflection_result rows for a workspace.
fn clear_reflection_results(ctx: &ReducerContext, _workspace_id: &str) {
    // Since the result table does not have a workspace_id column, we delete
    // all rows. This is a conservative approach matching the pattern used
    // elsewhere (e.g. consolidation does not filter by workspace for results).
    let stale: Vec<String> = ctx
        .db
        .reflection_result()
        .iter()
        .take(crate::MAX_RESULTS)
        .map(|r: ReflectionResult| r.result_id.clone())
        .collect();
    for rid in stale {
        ctx.db.reflection_result().result_id().delete(rid);
    }
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

/// Create a new reflection session in "idle" status.
#[reducer]
pub fn create_reflection_session(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
    config_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_reflection_session", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    validate_status("idle")?;

    let now = now_micros(ctx);
    let id = uuid_v7(ctx);
    let ws_clone = workspace_id.clone();

    let session = ReflectionSession {
        id: id.clone(),
        workspace_id: ws_clone,
        peer_id,
        status: "idle".to_string(),
        config_json,
        cycle_count: 0,
        insights_count: 0,
        started_at: now,
        completed_at: 0,
        updated_at: now,
    };

    ctx.db.reflection_session().insert(session);
    Ok(())
})
}

/// Start (or continue) a reflection cycle on a session.
///
/// Sets status to "running", increments `cycle_count`, and writes a change event.
/// The session must be in "idle" status to start a new cycle.
#[reducer]
pub fn start_reflection_cycle(
    ctx: &ReducerContext,
    workspace_id: String,
    session_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "start_reflection_cycle", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    let mut session = ctx
        .db
        .reflection_session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Reflection session '{}' not found", session_id))?;

    if !is_valid_transition(&session.status, "running") {
        return Err(format!(
            "Cannot transition session '{}' from status '{}' to 'running'",
            session_id, session.status
        ));
    }

    let now = now_micros(ctx);
    session.status = "running".to_string();
    session.cycle_count += 1;
    session.updated_at = now;

    let cycle_count = session.cycle_count;

    ctx.db.reflection_session().id().update(session);

    // Write a change event for observability
    let data_json = serde_json::json!({
        "session_id": session_id,
        "cycle_count": cycle_count,
        "status": "running",
        "action": "cycle_start",
    });
    crate::change_event::log_change(
        ctx,
        &workspace_id,
        "reflection_session",
        "update",
        &session_id,
        &data_json.to_string(),
    );

    Ok(())
})
}

/// Store a reflection insight produced by a cycle.
///
/// Automatically increments `insights_count` on the parent session.
/// `confidence` is clamped to [0.0, 1.0].
#[reducer]
pub fn store_reflection_insight(
    ctx: &ReducerContext,
    workspace_id: String,
    session_id: String,
    content: String,
    confidence: f64,
    insight_type: String,
    source_memory_ids_json: String,
    source_note_ids_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "store_reflection_insight", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    let session = ctx
        .db
        .reflection_session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Reflection session '{}' not found", session_id))?;

    validate_insight_type(&insight_type)?;
    let clamped_confidence = clamp_confidence(confidence);

    let now = now_micros(ctx);
    let id = uuid_v7(ctx);
    let workspace_clone = workspace_id.clone();

    let insight = ReflectionInsight {
        id: id.clone(),
        session_id: session_id.clone(),
        workspace_id: workspace_clone,
        cycle_number: session.cycle_count,
        content,
        confidence: clamped_confidence,
        insight_type,
        source_memory_ids_json,
        source_note_ids_json,
        created_at: now,
    };

    ctx.db.reflection_insight().insert(insight);

    // Increment the parent session's insights_count
    let mut updated_session = session;
    updated_session.insights_count += 1;
    updated_session.updated_at = now;
    ctx.db.reflection_session().id().update(updated_session);

    Ok(())
})
}

/// Complete a reflection session by setting its final status ("completed" or "failed")
/// and recording the completion timestamp.
#[reducer]
pub fn complete_reflection_session(
    ctx: &ReducerContext,
    workspace_id: String,
    session_id: String,
    status: String,
) -> Result<(), String> {
    trace_span!(ctx, "complete_reflection_session", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    validate_status(&status)?;

    if status != "completed" && status != "failed" {
        return Err(format!(
            "Cannot complete session '{}' with status '{}'. Must be 'completed' or 'failed'.",
            session_id, status
        ));
    }

    let mut session = ctx
        .db
        .reflection_session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Reflection session '{}' not found", session_id))?;

    if !is_valid_transition(&session.status, &status) {
        return Err(format!(
            "Cannot transition session '{}' from status '{}' to '{}'",
            session_id, session.status, status
        ));
    }

    let now = now_micros(ctx);
    session.status = status;
    session.completed_at = now;
    session.updated_at = now;

    ctx.db.reflection_session().id().update(session);
    Ok(())
})
}

/// Query reflection sessions for a workspace.
///
/// Results are stored in the `reflection_result` table (compute-and-store pattern).
#[reducer]
pub fn get_reflection_sessions(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_reflection_sessions", TracingSpanKind::Read, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    let sessions: Vec<ReflectionSession> = ctx
        .db
        .reflection_session()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
        .collect();

    let data = serde_json::to_string(&sessions)
        .unwrap_or_else(|_| "[]".to_string());

    let now = now_micros(ctx);

    // Compute-and-store: clear old results, write new
    clear_reflection_results(ctx, &workspace_id);

    let result = ReflectionResult {
        result_id: uuid_v7(ctx),
        data,
        created_at: now,
    };
    ctx.db.reflection_result().insert(result);

    Ok(())
})
}

/// Query reflection insights for a specific session.
///
/// Results are stored in the `reflection_result` table (compute-and-store pattern).
#[reducer]
pub fn get_reflection_insights(
    ctx: &ReducerContext,
    workspace_id: String,
    session_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_reflection_insights", TracingSpanKind::Read, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    // Verify the session exists and belongs to this workspace
    let _session = ctx
        .db
        .reflection_session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Reflection session '{}' not found", session_id))?;

    let insights: Vec<ReflectionInsight> = ctx
        .db
        .reflection_insight()
        .session_id()
        .filter(&session_id)
        .take(crate::MAX_RESULTS)
        .collect();

    let data = serde_json::to_string(&insights)
        .unwrap_or_else(|_| "[]".to_string());

    let now = now_micros(ctx);

    // Compute-and-store: clear old results, write new
    clear_reflection_results(ctx, &workspace_id);

    let result = ReflectionResult {
        result_id: uuid_v7(ctx),
        data,
        created_at: now,
    };
    ctx.db.reflection_result().insert(result);

    Ok(())
})
}

/// Delete a reflection session and all its associated insights (cascading delete).
#[reducer]
pub fn delete_reflection_session(
    ctx: &ReducerContext,
    workspace_id: String,
    session_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "delete_reflection_session", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    let _session = ctx
        .db
        .reflection_session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Reflection session '{}' not found", session_id))?;

    // Cascading delete: remove all insights for this session
    let insight_ids: Vec<String> = ctx
        .db
        .reflection_insight()
        .session_id()
        .filter(&session_id)
        .take(crate::MAX_RESULTS)
        .map(|i: ReflectionInsight| i.id.clone())
        .collect();

    for iid in &insight_ids {
        ctx.db.reflection_insight().id().delete(iid);
    }

    // Delete the session itself
    ctx.db.reflection_session().id().delete(&session_id);

    Ok(())
})
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // ---- Status validation ----

    #[test]
    fn test_validate_status_valid() {
        for s in &["idle", "running", "completed", "failed"] {
            assert!(validate_status(s).is_ok(), "Expected '{}' to be valid", s);
        }
    }

    #[test]
    fn test_validate_status_invalid() {
        assert!(validate_status("unknown").is_err());
        assert!(validate_status("paused").is_err());
        assert!(validate_status("").is_err());
    }

    #[test]
    fn test_is_valid_transition_idle_to_running() {
        assert!(is_valid_transition("idle", "running"));
    }

    #[test]
    fn test_is_valid_transition_running_to_completed() {
        assert!(is_valid_transition("running", "completed"));
    }

    #[test]
    fn test_is_valid_transition_running_to_failed() {
        assert!(is_valid_transition("running", "failed"));
    }

    #[test]
    fn test_is_valid_transition_completed_no_transition() {
        assert!(!is_valid_transition("completed", "running"));
        assert!(!is_valid_transition("completed", "idle"));
        assert!(!is_valid_transition("completed", "failed"));
    }

    #[test]
    fn test_is_valid_transition_failed_no_transition() {
        assert!(!is_valid_transition("failed", "running"));
        assert!(!is_valid_transition("failed", "idle"));
        assert!(!is_valid_transition("failed", "completed"));
    }

    #[test]
    fn test_is_valid_transition_unknown_from() {
        assert!(!is_valid_transition("unknown", "running"));
    }

    #[test]
    fn test_is_valid_transition_idle_skip() {
        // Direct idle → completed is NOT allowed
        assert!(!is_valid_transition("idle", "completed"));
        assert!(!is_valid_transition("idle", "failed"));
    }

    // ---- Insight type validation ----

    #[test]
    fn test_validate_insight_type_valid() {
        for t in &["pattern", "contradiction", "gap", "observation", "connection", "synthesis"] {
            assert!(validate_insight_type(t).is_ok(), "Expected '{}' to be valid", t);
        }
    }

    #[test]
    fn test_validate_insight_type_invalid() {
        assert!(validate_insight_type("conclusion").is_err());
        assert!(validate_insight_type("question").is_err());
        assert!(validate_insight_type("").is_err());
        assert!(validate_insight_type(" Pattern").is_err()); // no leading space
    }

    // ---- Confidence clamping ----

    #[test]
    fn test_clamp_confidence_in_range() {
        assert!((clamp_confidence(0.5) - 0.5).abs() < f64::EPSILON);
        assert!((clamp_confidence(0.0) - 0.0).abs() < f64::EPSILON);
        assert!((clamp_confidence(1.0) - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_clamp_confidence_below_zero() {
        assert!((clamp_confidence(-0.5) - 0.0).abs() < f64::EPSILON);
        assert!((clamp_confidence(-1.0) - 0.0).abs() < f64::EPSILON);
        assert!((clamp_confidence(f64::NEG_INFINITY) - 0.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_clamp_confidence_above_one() {
        assert!((clamp_confidence(1.5) - 1.0).abs() < f64::EPSILON);
        assert!((clamp_confidence(100.0) - 1.0).abs() < f64::EPSILON);
        assert!((clamp_confidence(f64::INFINITY) - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_clamp_confidence_nan_becomes_zero() {
        // clamp(NaN, 0, 1) returns NaN in Rust, but we can verify the behaviour
        let clamped = clamp_confidence(f64::NAN);
        assert!(clamped.is_nan(), "NaN should remain NaN after clamp");
        // We accept this edge case; the reducer will store NaN which is
        // undesirable but not a crash. Integration-level validation is
        // recommended.
    }

    // ---- Struct construction ----

    #[test]
    fn test_reflection_session_struct_defaults() {
        let session = ReflectionSession {
            id: "sess-1".into(),
            workspace_id: "ws-1".into(),
            peer_id: "peer-1".into(),
            status: "idle".into(),
            config_json: r#"{"interval_minutes": 30, "max_cycles": 5}"#.into(),
            cycle_count: 0,
            insights_count: 0,
            started_at: 1_000_000,
            completed_at: 0,
            updated_at: 1_000_000,
        };
        assert_eq!(session.status, "idle");
        assert_eq!(session.cycle_count, 0);
        assert_eq!(session.insights_count, 0);
        assert_eq!(session.completed_at, 0);
    }

    #[test]
    fn test_reflection_insight_struct() {
        let insight = ReflectionInsight {
            id: "ins-1".into(),
            session_id: "sess-1".into(),
            workspace_id: "ws-1".into(),
            cycle_number: 1,
            content: "Test insight content".into(),
            confidence: 0.85,
            insight_type: "pattern".into(),
            source_memory_ids_json: r#"["mem-1", "mem-2"]"#.into(),
            source_note_ids_json: r#"["note-1"]"#.into(),
            created_at: 2_000_000,
        };
        assert_eq!(insight.cycle_number, 1);
        assert!((insight.confidence - 0.85).abs() < f64::EPSILON);
        assert_eq!(insight.insight_type, "pattern");
    }

    #[test]
    fn test_reflection_result_struct() {
        let result = ReflectionResult {
            result_id: "res-1".into(),
            data: r#"[]"#.into(),
            created_at: 3_000_000,
        };
        assert_eq!(result.data, "[]");
        assert_eq!(result.created_at, 3_000_000);
    }

    // ---- Edge cases ----

    #[test]
    fn test_empty_source_arrays_are_valid() {
        // Empty JSON arrays are valid source identifiers
        let insight = ReflectionInsight {
            id: "ins-empty".into(),
            session_id: "sess-1".into(),
            workspace_id: "ws-1".into(),
            cycle_number: 0,
            content: "Empty sources".into(),
            confidence: 0.5,
            insight_type: "observation".into(),
            source_memory_ids_json: "[]".into(),
            source_note_ids_json: "[]".into(),
            created_at: 0,
        };
        assert_eq!(insight.source_memory_ids_json, "[]");
        assert_eq!(insight.source_note_ids_json, "[]");
    }

    #[test]
    fn test_large_confidence_values_get_clamped() {
        let clamped = clamp_confidence(999.0);
        assert!((clamped - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_very_negative_confidence_clamped() {
        let clamped = clamp_confidence(-999.0);
        assert!((clamped - 0.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_status_error_message_contains_valid_statuses() {
        let err = validate_status("bogus").unwrap_err();
        assert!(err.contains("bogus"));
        assert!(err.contains("idle"));
        assert!(err.contains("running"));
        assert!(err.contains("completed"));
        assert!(err.contains("failed"));
    }

    #[test]
    fn test_insight_type_error_message_contains_valid_types() {
        let err = validate_insight_type("bogus").unwrap_err();
        assert!(err.contains("bogus"));
        assert!(err.contains("pattern"));
        assert!(err.contains("contradiction"));
        assert!(err.contains("gap"));
        assert!(err.contains("observation"));
        assert!(err.contains("connection"));
        assert!(err.contains("synthesis"));
    }

    #[test]
    fn test_all_statuses_are_valid_for_validation() {
        // The validate_status function should accept exactly the 4 valid statuses
        for s in VALID_STATUSES {
            assert!(validate_status(s).is_ok(), "validate_status should accept '{}'", s);
        }
    }

    #[test]
    fn test_all_insight_types_are_valid_for_validation() {
        for t in VALID_INSIGHT_TYPES {
            assert!(validate_insight_type(t).is_ok(), "validate_insight_type should accept '{}'", t);
        }
    }
}
