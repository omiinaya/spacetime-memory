use spacetimedb::*;
use crate::auth::require_auth;
use crate::session::{agent_step, session, session_step_result, check_session_access, AgentStep};
use crate::{now_micros, uuid_v7};

/// ── Interrupt/Resume Protocol ────────────────────────────────────────────
///
/// LangGraph-parity interrupt/resume for agent sessions.
///
/// State machine tracked via agent step types and session metadata:
///
///   running ──(interrupt_session)──▸ interrupted ──(resume_session)──▸ running
///       │                                                               │
///       └──────────────────── (completed) ───────────────────────────────┘
///
/// - **Interrupt** writes a step with `step_type = "interrupt"` whose
///   `content` is JSON carrying `{"reason": "...", "target_step": "..."}`.
/// - **Resume** finds the most recent interrupt, writes a `step_type =
///   "resume"` marker, and restores the session to running state.
/// - **State** is read from the session's `metadata` field and the most
///   recent agent step.
///
/// No new tables are created — we reuse the existing `session` and
/// `agent_step` tables.
///
/// ── Constants used in session metadata ───────────────────────────────────
///
/// Metadata key holding the session state machine status.
const STATE_KEY: &str = "interrupt_state";

/// Metadata key holding the last interrupt step id for resume.
const INTERRUPT_STEP_KEY: &str = "interrupt_step_id";

/// Metadata key holding the last interrupt reason.
const REASON_KEY: &str = "interrupt_reason";

/// Metadata key holding the target step id for resume.
const TARGET_STEP_KEY: &str = "interrupt_target_step";

// ── Helpers ──────────────────────────────────────────────────────────────

/// Serialize session metadata from a JSON string to a writable map.
fn metadata_to_map(metadata_json: &str) -> serde_json::Map<String, serde_json::Value> {
    let parsed: serde_json::Value = serde_json::from_str(metadata_json)
        .unwrap_or(serde_json::Value::Object(serde_json::Map::new()));
    match parsed {
        serde_json::Value::Object(map) => map,
        _ => serde_json::Map::new(),
    }
}

/// Deserialize a metadata map back into a JSON string.
fn map_to_metadata(map: &serde_json::Map<String, serde_json::Value>) -> String {
    serde_json::to_string(map).unwrap_or_else(|_| "{}".to_string())
}

/// Read a string value from metadata map.
fn get_meta(map: &serde_json::Map<String, serde_json::Value>, key: &str) -> String {
    map.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string()
}

/// Build the JSON content for an interrupt step.
fn make_interrupt_content(reason: &str, target_step: &str) -> String {
    let mut map = serde_json::Map::new();
    map.insert(
        "reason".to_string(),
        serde_json::Value::String(reason.to_string()),
    );
    map.insert(
        "target_step".to_string(),
        serde_json::Value::String(target_step.to_string()),
    );
    map.insert(
        "interrupted_at".to_string(),
        serde_json::Value::String(String::new()), // filled by reducer
    );
    serde_json::to_string(&map).unwrap_or_else(|_| "{}".to_string())
}

/// Build the JSON content for a resume step.
fn make_resume_content(from_interrupt: &str, restored_state: &str) -> String {
    let mut map = serde_json::Map::new();
    map.insert(
        "from_interrupt".to_string(),
        serde_json::Value::String(from_interrupt.to_string()),
    );
    map.insert(
        "restored_state".to_string(),
        serde_json::Value::String(restored_state.to_string()),
    );
    map.insert(
        "resumed_at".to_string(),
        serde_json::Value::String(String::new()),
    );
    serde_json::to_string(&map).unwrap_or_else(|_| "{}".to_string())
}

/// ── Reducers ────────────────────────────────────────────────────────────
///
/// Pause an agent session, recording a formal interrupt point.
///
/// Writes a step with `step_type = "interrupt"` and updates session
/// metadata to track the interrupt state.
///
/// # Arguments
///
/// * `session_id` — The session to interrupt.
/// * `reason` — Human/readable reason for the interrupt (e.g.
///   "awaiting user input", "tool timeout", "max steps reached").
/// * `target_step_id` — Optional step id where execution should resume.
///   Pass empty string if unknown.
#[reducer]
pub fn interrupt_session(
    ctx: &ReducerContext,
    workspace_id: String,
    session_id: String,
    reason: String,
    target_step_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    let _ws_id = check_session_access(ctx, &session_id, &caller, "editor")?;

    let now = now_micros(ctx);

    // ── Validate session exists ──
    let mut session = ctx
        .db
        .session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Session '{}' not found", session_id))?;

    // ── Build interrupt step content ──
    let mut content = make_interrupt_content(&reason, &target_step_id);
    // Patch the interrupted_at timestamp
    if let Ok(mut v) = serde_json::from_str::<serde_json::Value>(&content) {
        if let Some(obj) = v.as_object_mut() {
            obj.insert(
                "interrupted_at".to_string(),
                serde_json::Value::Number(serde_json::Number::from(now)),
            );
        }
        content = serde_json::to_string(&v).unwrap_or(content);
    }

    let step_id = uuid_v7(ctx);

    // ── Insert the interrupt step ──
    ctx.db.agent_step().insert(AgentStep {
        id: step_id.clone(),
        session_id: session_id.clone(),
        workspace_id: workspace_id.clone(),
        step_type: "interrupt".to_string(),
        content,
        summary: format!("interrupt: {}", reason),
        parent_step_id: target_step_id.clone(),
        created_at: now,
    });

    // ── Update session metadata with interrupt state ──
    let mut meta = metadata_to_map(&session.metadata);
    meta.insert(
        STATE_KEY.to_string(),
        serde_json::Value::String("interrupted".to_string()),
    );
    meta.insert(
        INTERRUPT_STEP_KEY.to_string(),
        serde_json::Value::String(step_id),
    );
    meta.insert(
        REASON_KEY.to_string(),
        serde_json::Value::String(reason),
    );
    meta.insert(
        TARGET_STEP_KEY.to_string(),
        serde_json::Value::String(target_step_id),
    );
    session.metadata = map_to_metadata(&meta);
    session.updated_at = now;
    ctx.db.session().id().update(session);

    Ok(())
}

/// Resume a previously interrupted session.
///
/// Finds the interrupt step, writes a `step_type = "resume"` marker, and
/// restores the session to `running` state.
///
/// # Arguments
///
/// * `session_id` — The session to resume.
/// * `from_step_id` — The interrupt step id to resume from. If empty, uses
///   the most recent interrupt step.
#[reducer]
pub fn resume_session(
    ctx: &ReducerContext,
    workspace_id: String,
    session_id: String,
    from_step_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    let _ws_id = check_session_access(ctx, &session_id, &caller, "editor")?;

    let now = now_micros(ctx);

    // ── Validate session exists ──
    let mut session = ctx
        .db
        .session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Session '{}' not found", session_id))?;

    // ── Find the interrupt step ──
    let interrupt_step = if from_step_id.is_empty() {
        // Find most recent interrupt step
        let steps: Vec<_> = ctx
            .db
            .agent_step()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|s| s.session_id == session_id && s.step_type == "interrupt")
            .collect();
        steps
            .into_iter()
            .max_by_key(|s| s.created_at)
            .ok_or_else(|| {
                format!(
                    "Session '{}' has no interrupt step to resume from",
                    session_id
                )
            })?
    } else {
        ctx.db
            .agent_step()
            .id()
            .find(&from_step_id)
            .ok_or_else(|| format!("Interrupt step '{}' not found", from_step_id))?
    };

    if interrupt_step.step_type != "interrupt" {
        return Err(format!(
            "Step '{}' is not an interrupt step (type='{}')",
            interrupt_step.id, interrupt_step.step_type
        ));
    }

    // ── Extract target step from interrupt content ──
    let target_step = interrupt_step.parent_step_id.clone();
    let restored_state = if target_step.is_empty() {
        "start".to_string()
    } else {
        format!("step:{}", target_step)
    };

    // ── Build resume step content ──
    let mut content = make_resume_content(&interrupt_step.id, &restored_state);
    if let Ok(mut v) = serde_json::from_str::<serde_json::Value>(&content) {
        if let Some(obj) = v.as_object_mut() {
            obj.insert(
                "resumed_at".to_string(),
                serde_json::Value::Number(serde_json::Number::from(now)),
            );
        }
        content = serde_json::to_string(&v).unwrap_or(content);
    }

    let step_id = uuid_v7(ctx);

    // ── Insert the resume step ──
    ctx.db.agent_step().insert(AgentStep {
        id: step_id.clone(),
        session_id: session_id.clone(),
        workspace_id: workspace_id.clone(),
        step_type: "resume".to_string(),
        content,
        summary: format!(
            "resumed from interrupt '{}'",
            interrupt_step.id
        ),
        parent_step_id: interrupt_step.id.clone(),
        created_at: now,
    });

    // ── Update session metadata: back to running ──
    let mut meta = metadata_to_map(&session.metadata);
    meta.insert(
        STATE_KEY.to_string(),
        serde_json::Value::String("running".to_string()),
    );
    // Clear interrupt-specific keys
    meta.remove(INTERRUPT_STEP_KEY);
    meta.remove(REASON_KEY);
    meta.remove(TARGET_STEP_KEY);
    session.metadata = map_to_metadata(&meta);
    session.updated_at = now;
    ctx.db.session().id().update(session);

    Ok(())
}

/// Get the current state machine status of a session.
///
/// Reads session metadata and the most recent step to determine the
/// session's interrupt state.
///
/// Results are written to the `session_step_result` table with query hash
/// `state:<session_id>`.
#[reducer]
pub fn get_session_state(
    ctx: &ReducerContext,
    session_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    let _ws_id = check_session_access(ctx, &session_id, &caller, "viewer")?;

    let session = ctx
        .db
        .session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Session '{}' not found", session_id))?;

    let meta = metadata_to_map(&session.metadata);
    let state = get_meta(&meta, STATE_KEY);

    // Default to "running" if no interrupt state is recorded
    let current_state = if state.is_empty() { "running" } else { &state };

    // Find the most recent step of each significant type
    let steps: Vec<_> = ctx
        .db
        .agent_step()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|s| s.session_id == session_id)
        .collect();

    let last_interrupt = steps
        .iter()
        .filter(|s| s.step_type == "interrupt")
        .max_by_key(|s| s.created_at);

    let last_resume = steps
        .iter()
        .filter(|s| s.step_type == "resume")
        .max_by_key(|s| s.created_at);

    let total_steps = steps.len();

    // Build state info JSON
    let mut info = serde_json::Map::new();
    info.insert(
        "session_id".to_string(),
        serde_json::Value::String(session_id.clone()),
    );
    info.insert(
        "workspace_id".to_string(),
        serde_json::Value::String(session.workspace_id.clone()),
    );
    info.insert(
        "state".to_string(),
        serde_json::Value::String(current_state.to_string()),
    );
    info.insert(
        "total_steps".to_string(),
        serde_json::Value::Number(serde_json::Number::from(total_steps as u64)),
    );
    info.insert(
        "interrupt_reason".to_string(),
        serde_json::Value::String(get_meta(&meta, REASON_KEY)),
    );
    info.insert(
        "interrupt_step_id".to_string(),
        serde_json::Value::String(match last_interrupt {
            Some(s) => s.id.clone(),
            None => String::new(),
        }),
    );
    info.insert(
        "last_resume_step_id".to_string(),
        serde_json::Value::String(match last_resume {
            Some(s) => s.id.clone(),
            None => String::new(),
        }),
    );
    info.insert(
        "updated_at".to_string(),
        serde_json::Value::Number(serde_json::Number::from(session.updated_at)),
    );

    let info_json = serde_json::to_string(&info).unwrap_or_else(|_| "{}".to_string());

    // Store result in session_step_result table (same pattern as get_session_steps)
    let query_hash = format!("state:{}", session_id);

    // Clear previous results for this hash
    let old: Vec<_> = ctx
        .db
        .session_step_result()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|r| r.query_hash == query_hash)
        .collect();
    for r in old {
        ctx.db.session_step_result().delete(r);
    }

    ctx.db.session_step_result().insert(crate::session::SessionStepResult {
        query_hash,
        id: uuid_v7(ctx),
        session_id: session_id.clone(),
        workspace_id: session.workspace_id.clone(),
        step_type: "state_info".to_string(),
        content: info_json,
        summary: format!("state:{}", current_state),
        parent_step_id: String::new(),
        created_at: now_micros(ctx),
    });

    Ok(())
}

// ── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metadata_to_map_empty() {
        let map = metadata_to_map("{}");
        assert!(map.is_empty());
    }

    #[test]
    fn test_metadata_to_map_invalid() {
        let map = metadata_to_map("not-json");
        assert!(map.is_empty());
    }

    #[test]
    fn test_metadata_to_map_roundtrip() {
        let mut expected = serde_json::Map::new();
        expected.insert(
            "state".to_string(),
            serde_json::Value::String("interrupted".to_string()),
        );
        expected.insert(
            "reason".to_string(),
            serde_json::Value::String("test".to_string()),
        );

        let json = map_to_metadata(&expected);
        let parsed = metadata_to_map(&json);

        assert_eq!(parsed.get("state").and_then(|v| v.as_str()), Some("interrupted"));
        assert_eq!(parsed.get("reason").and_then(|v| v.as_str()), Some("test"));
    }

    #[test]
    fn test_get_meta_missing() {
        let map = serde_json::Map::new();
        assert_eq!(get_meta(&map, "nonexistent"), "");
    }

    #[test]
    fn test_get_meta_present() {
        let mut map = serde_json::Map::new();
        map.insert(
            "key".to_string(),
            serde_json::Value::String("value".to_string()),
        );
        assert_eq!(get_meta(&map, "key"), "value");
    }

    #[test]
    fn test_make_interrupt_content() {
        let content = make_interrupt_content("user input required", "step_005");
        let parsed: serde_json::Value =
            serde_json::from_str(&content).expect("valid JSON");

        assert_eq!(parsed["reason"], "user input required");
        assert_eq!(parsed["target_step"], "step_005");
        assert!(parsed.get("interrupted_at").is_some());
    }

    #[test]
    fn test_make_interrupt_content_empty_target() {
        let content = make_interrupt_content("tool timeout", "");
        let parsed: serde_json::Value =
            serde_json::from_str(&content).expect("valid JSON");

        assert_eq!(parsed["reason"], "tool timeout");
        assert_eq!(parsed["target_step"], "");
    }

    #[test]
    fn test_make_resume_content() {
        let content = make_resume_content("step_interrupt_001", "step:step_005");
        let parsed: serde_json::Value =
            serde_json::from_str(&content).expect("valid JSON");

        assert_eq!(parsed["from_interrupt"], "step_interrupt_001");
        assert_eq!(parsed["restored_state"], "step:step_005");
        assert!(parsed.get("resumed_at").is_some());
    }

    #[test]
    fn test_make_resume_content_start() {
        let content = make_resume_content("step_interrupt_001", "start");
        let parsed: serde_json::Value =
            serde_json::from_str(&content).expect("valid JSON");

        assert_eq!(parsed["restored_state"], "start");
    }

    #[test]
    fn test_state_constants_are_valid_strings() {
        assert_eq!(STATE_KEY, "interrupt_state");
        assert_eq!(INTERRUPT_STEP_KEY, "interrupt_step_id");
        assert_eq!(REASON_KEY, "interrupt_reason");
        assert_eq!(TARGET_STEP_KEY, "interrupt_target_step");
    }

    #[test]
    fn test_interrupt_content_contains_required_fields() {
        let content = make_interrupt_content("test", "step_001");
        let parsed: serde_json::Value =
            serde_json::from_str(&content).expect("valid JSON");
        let obj = parsed.as_object().expect("object");

        assert!(obj.contains_key("reason"), "missing 'reason'");
        assert!(obj.contains_key("target_step"), "missing 'target_step'");
        assert!(obj.contains_key("interrupted_at"), "missing 'interrupted_at'");
    }

    #[test]
    fn test_resume_content_contains_required_fields() {
        let content = make_resume_content("interrupt_001", "step:002");
        let parsed: serde_json::Value =
            serde_json::from_str(&content).expect("valid JSON");
        let obj = parsed.as_object().expect("object");

        assert!(obj.contains_key("from_interrupt"), "missing 'from_interrupt'");
        assert!(obj.contains_key("restored_state"), "missing 'restored_state'");
        assert!(obj.contains_key("resumed_at"), "missing 'resumed_at'");
    }
}
