use spacetimedb::*;
use crate::auth::require_auth;
use crate::crypto::encrypt_if_enabled;

use crate::{now_micros, uuid_v7};
use crate::workspace::check_space_access;

/// A session represents a conversation or interaction within a workspace.
#[table(accessor = session)]
#[derive(Debug, Clone)]
pub struct Session {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub name: String,
    pub summary: String,
    pub metadata: String,
    pub created_at: i64,
    pub updated_at: i64,
}

/// Join table linking sessions to peers. Composite key: (session_id, peer_id).
/// No `#[primary_key]` attribute; SpacetimeDB uses the combination as a unique constraint.
#[table(accessor = session_participant)]
#[derive(Debug, Clone)]
pub struct SessionParticipant {
    pub session_id: String,
    pub peer_id: String,
    pub role: String,
    pub joined_at: i64,
}

/// Agent reasoning step — records chain-of-thought, tool calls, observations.
#[table(accessor = agent_step)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AgentStep {
    #[primary_key]
    pub id: String,
    pub session_id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// "thought", "action", "observation", "tool_call", "tool_result"
    pub step_type: String,
    /// JSON or text content
    pub content: String,
    pub summary: String,
    /// For chain-of-thought linking
    pub parent_step_id: String,
    pub created_at: i64,
}

/// Result table for get_session_steps reducer.
#[table(accessor = session_step_result)]
#[derive(Debug, Clone)]
pub struct SessionStepResult {
    pub query_hash: String,
    pub id: String,
    pub session_id: String,
    pub workspace_id: String,
    pub step_type: String,
    pub content: String,
    pub summary: String,
    pub parent_step_id: String,
    pub created_at: i64,
}

#[reducer]
pub fn create_session(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    metadata_json: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    ctx.db.session().insert(Session {
        id: id.clone(),
        workspace_id,
        name,
        summary: String::new(),
        metadata: if metadata_json.is_empty() {
            String::from("{}")
        } else {
            metadata_json
        },
        created_at: now,
        updated_at: now,
    });
    Ok(())
}

#[reducer]
pub fn join_session(
    ctx: &ReducerContext,
    session_id: String,
    peer_id: String,
    role: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Verify session exists + caller has permission
    let caller = ctx.sender().to_hex();
    let _workspace_id = check_session_access(ctx, &session_id, &caller, "editor")?;

    // Check if already a participant
    let already = ctx
        .db
        .session_participant()
        .iter().take(crate::MAX_RESULTS)
        .find(|sp| sp.session_id == session_id && sp.peer_id == peer_id);

    if already.is_some() {
        return Err(format!(
            "Peer '{}' is already a participant in session '{}'",
            peer_id, session_id
        ));
    }

    ctx.db.session_participant().insert(SessionParticipant {
        session_id,
        peer_id,
        role,
        joined_at: now_micros(ctx),
    });
    Ok(())
}

#[reducer]
pub fn leave_session(
    ctx: &ReducerContext,
    session_id: String,
    peer_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Verify session exists + caller has permission
    let caller = ctx.sender().to_hex();
    let _workspace_id = check_session_access(ctx, &session_id, &caller, "editor")?;

    // Verify the participant exists
    let exists = ctx
        .db
        .session_participant()
        .iter().take(crate::MAX_RESULTS)
        .any(|sp| sp.session_id == session_id && sp.peer_id == peer_id);

    if !exists {
        return Err(format!(
            "Peer '{}' is not a participant in session '{}'",
            peer_id, session_id
        ));
    }

    // Delete matching rows (table has no PK, so iterate and delete each row)
    let to_delete: Vec<_> = ctx.db.session_participant()
        .iter().take(crate::MAX_RESULTS)
        .filter(|sp| sp.session_id == session_id && sp.peer_id == peer_id)
        .collect();
    for sp in to_delete {
        ctx.db.session_participant().delete(sp);
    }

    Ok(())
}

#[reducer]
pub fn update_session_summary(
    ctx: &ReducerContext,
    session_id: String,
    summary: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    let _workspace_id = check_session_access(ctx, &session_id, &caller, "editor")?;

    let mut session = ctx
        .db
        .session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Session '{}' not found", session_id))?;

    // Encrypt summary if workspace encryption is enabled
    session.summary = encrypt_if_enabled(ctx, &session.workspace_id, &summary)?;
    session.updated_at = now_micros(ctx);

    ctx.db.session().id().update(session);
    Ok(())
}

// ── Agent step reducers ──────────────────────────────────────────────────

/// Add an agent reasoning step (thought, action, tool_call, etc.).
#[reducer]
pub fn add_agent_step(
    ctx: &ReducerContext,
    session_id: String,
    workspace_id: String,
    step_type: String,
    content: String,
    summary: String,
    parent_step_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    // Verify session exists
    ctx.db
        .session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Session '{}' not found", session_id))?;

    // Encrypt content and summary if workspace encryption is enabled
    let enc_content = encrypt_if_enabled(ctx, &workspace_id, &content)?;
    let enc_summary = encrypt_if_enabled(ctx, &workspace_id, &summary)?;
    ctx.db.agent_step().insert(AgentStep {
        id: id.clone(),
        session_id: session_id.clone(),
        workspace_id,
        step_type,
        content: enc_content,
        summary: enc_summary,
        parent_step_id,
        created_at: now,
    });

    // Update session's updated_at timestamp
    if let Some(mut sess) = ctx.db.session().id().find(&session_id) {
        sess.updated_at = now;
        ctx.db.session().id().update(sess);
    }

    Ok(())
}

/// Retrieve all steps for a session, stored in session_step_result table.
#[reducer]
pub fn get_session_steps(
    ctx: &ReducerContext,
    session_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    let _workspace_id = check_session_access(ctx, &session_id, &caller, "viewer")?;
    let query_hash = format!("steps:{}", session_id);

    // Clear previous results for this hash
    let old: Vec<_> = ctx.db.session_step_result().iter().take(crate::MAX_RESULTS)
        .filter(|r| r.query_hash == query_hash)
        .collect();
    for r in old {
        ctx.db.session_step_result().delete(r);
    }

    let mut steps: Vec<_> = ctx.db.agent_step().workspace_id().filter(&_workspace_id).take(crate::MAX_RESULTS)
        .filter(|s| s.session_id == session_id)
        .collect();
    steps.sort_by_key(|s| s.created_at);

    for s in &steps {
        ctx.db.session_step_result().insert(SessionStepResult {
            query_hash: query_hash.clone(),
            id: s.id.clone(),
            session_id: s.session_id.clone(),
            workspace_id: s.workspace_id.clone(),
            step_type: s.step_type.clone(),
            content: s.content.clone(),
            summary: s.summary.clone(),
            parent_step_id: s.parent_step_id.clone(),
            created_at: s.created_at,
        });
    }

    Ok(())
}

/// Delete all agent steps for a given session.
#[reducer]
pub fn delete_session_steps(ctx: &ReducerContext, session_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    let _workspace_id = check_session_access(ctx, &session_id, &caller, "editor")?;
    let to_delete: Vec<_> = ctx.db.agent_step().workspace_id().filter(&_workspace_id).take(crate::MAX_RESULTS)
        .filter(|s| s.session_id == session_id)
        .collect();
    for s in to_delete {
        ctx.db.agent_step().delete(s);
    }
    Ok(())
}

// ── Session ACL guard ─────────────────────────────────────────────────

/// Resolve a session_id to its workspace_id and check that `peer_id`
/// has at least the `required` permission level on that workspace.
///
/// This is the standard guard for session-scoped operations
/// (messages, participant management, session updates).
pub fn check_session_access(
    ctx: &ReducerContext,
    session_id: &str,
    peer_id: &str,
    required: &str,
) -> Result<String, String> {
    let session = ctx
        .db
        .session()
        .id()
        .find(session_id.to_string())
        .ok_or_else(|| format!("Session '{}' not found", session_id))?;

    check_space_access(ctx, &session.workspace_id, peer_id, required)?;
    Ok(session.workspace_id)
}

// ── Tests ────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_session_initialization() {
        let session = Session {
            id: "sess_001".to_string(),
            workspace_id: "ws_001".to_string(),
            name: "Test Session".to_string(),
            summary: String::new(),
            metadata: "{}".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };

        assert_eq!(session.id, "sess_001");
        assert_eq!(session.workspace_id, "ws_001");
        assert_eq!(session.name, "Test Session");
        assert_eq!(session.summary, "");
        assert_eq!(session.metadata, "{}");
        assert_eq!(session.created_at, 1_000_000);
        assert_eq!(session.updated_at, 1_000_000);
    }

    #[test]
    fn test_session_participant_initialization() {
        let participant = SessionParticipant {
            session_id: "sess_001".to_string(),
            peer_id: "peer_abc".to_string(),
            role: "editor".to_string(),
            joined_at: 1_000_000,
        };

        assert_eq!(participant.session_id, "sess_001");
        assert_eq!(participant.peer_id, "peer_abc");
        assert_eq!(participant.role, "editor");
        assert_eq!(participant.joined_at, 1_000_000);
    }

    #[test]
    fn test_agent_step_initialization() {
        let step = AgentStep {
            id: "step_001".to_string(),
            session_id: "sess_001".to_string(),
            workspace_id: "ws_001".to_string(),
            step_type: "thought".to_string(),
            content: r#"{"thinking":"analyzing..."}"#.to_string(),
            summary: String::new(),
            parent_step_id: String::new(),
            created_at: 1_000_000,
        };

        assert_eq!(step.id, "step_001");
        assert_eq!(step.session_id, "sess_001");
        assert_eq!(step.workspace_id, "ws_001");
        assert_eq!(step.step_type, "thought");
        assert_eq!(step.content, r#"{"thinking":"analyzing..."}"#);
        assert_eq!(step.summary, "");
        assert_eq!(step.parent_step_id, "");
        assert_eq!(step.created_at, 1_000_000);
    }

    #[test]
    fn test_session_step_result_initialization() {
        let result = SessionStepResult {
            query_hash: "steps:sess_001".to_string(),
            id: "step_001".to_string(),
            session_id: "sess_001".to_string(),
            workspace_id: "ws_001".to_string(),
            step_type: "thought".to_string(),
            content: r#"{"thinking":"analyzing..."}"#.to_string(),
            summary: String::new(),
            parent_step_id: String::new(),
            created_at: 1_000_000,
        };

        assert_eq!(result.query_hash, "steps:sess_001");
        assert_eq!(result.id, "step_001");
        assert_eq!(result.session_id, "sess_001");
        assert_eq!(result.workspace_id, "ws_001");
        assert_eq!(result.step_type, "thought");
        assert_eq!(result.content, r#"{"thinking":"analyzing..."}"#);
        assert_eq!(result.summary, "");
        assert_eq!(result.parent_step_id, "");
        assert_eq!(result.created_at, 1_000_000);
    }

    #[test]
    fn test_agent_step_serde() {
        let step = AgentStep {
            id: "step_serde_001".to_string(),
            session_id: "sess_002".to_string(),
            workspace_id: "ws_002".to_string(),
            step_type: "tool_call".to_string(),
            content: r#"{"tool":"search","args":{"q":"test"}}"#.to_string(),
            summary: "Searched for test".to_string(),
            parent_step_id: "step_000".to_string(),
            created_at: 2_000_000,
        };

        let json = serde_json::to_string(&step).expect("serialize AgentStep");
        let deserialized: AgentStep = serde_json::from_str(&json).expect("deserialize AgentStep");

        assert_eq!(deserialized.id, step.id);
        assert_eq!(deserialized.session_id, step.session_id);
        assert_eq!(deserialized.workspace_id, step.workspace_id);
        assert_eq!(deserialized.step_type, step.step_type);
        assert_eq!(deserialized.content, step.content);
        assert_eq!(deserialized.summary, step.summary);
        assert_eq!(deserialized.parent_step_id, step.parent_step_id);
        assert_eq!(deserialized.created_at, step.created_at);
    }

    #[test]
    fn test_default_values() {
        // Session defaults: summary is empty string, metadata is "{}"
        let session = Session {
            id: "sess_default".to_string(),
            workspace_id: "ws_default".to_string(),
            name: "Default Session".to_string(),
            summary: String::new(),
            metadata: "{}".to_string(),
            created_at: 0,
            updated_at: 0,
        };

        assert_eq!(session.summary, "");
        assert_eq!(session.metadata, "{}");

        // AgentStep defaults: summary and parent_step_id are empty strings
        let step = AgentStep {
            id: "step_default".to_string(),
            session_id: "sess_default".to_string(),
            workspace_id: "ws_default".to_string(),
            step_type: "thought".to_string(),
            content: String::new(),
            summary: String::new(),
            parent_step_id: String::new(),
            created_at: 0,
        };

        assert_eq!(step.summary, "");
        assert_eq!(step.parent_step_id, "");
    }

    // -------------------------------------------------------------------------
    // Additional edge case and struct tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_session_empty_name() {
        let session = Session {
            id: "sess_empty_name".to_string(),
            workspace_id: "ws".to_string(),
            name: String::new(),
            summary: String::new(),
            metadata: "{}".to_string(),
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(session.name, "");
    }

    #[test]
    fn test_session_metadata_empty_becomes_default() {
        // The reducer defaults empty metadata_json to "{}"
        let metadata = if String::new().is_empty() {
            String::from("{}")
        } else {
            String::new()
        };
        assert_eq!(metadata, "{}");
    }

    #[test]
    fn test_session_participant_empty_role() {
        let participant = SessionParticipant {
            session_id: "sess_empty_role".to_string(),
            peer_id: "peer".to_string(),
            role: String::new(),
            joined_at: 0,
        };
        assert_eq!(participant.role, "");
    }

    #[test]
    fn test_session_with_long_strings() {
        let long_name = "x".repeat(1_000);
        let long_summary = "y".repeat(5_000);
        let long_metadata = format!(r#"{{"data":"{}"}}"#, "z".repeat(1_000));
        let session = Session {
            id: "sess_long".to_string(),
            workspace_id: "ws".to_string(),
            name: long_name.clone(),
            summary: long_summary.clone(),
            metadata: long_metadata.clone(),
            created_at: 100,
            updated_at: 200,
        };
        assert_eq!(session.name.len(), 1_000);
        assert_eq!(session.summary.len(), 5_000);
        assert!(session.metadata.len() > 1_000);
        assert_eq!(session.name, long_name);
        assert_eq!(session.summary, long_summary);
        assert_eq!(session.metadata, long_metadata);
    }

    #[test]
    fn test_session_updated_at_ge_created_at() {
        let session = Session {
            id: "sess_ts".to_string(),
            workspace_id: "ws".to_string(),
            name: "Timestamps".to_string(),
            summary: String::new(),
            metadata: "{}".to_string(),
            created_at: 1_000,
            updated_at: 2_000,
        };
        assert!(session.updated_at >= session.created_at);

        let equal_ts = Session {
            id: "sess_eq_ts".to_string(),
            workspace_id: "ws".to_string(),
            name: "Equal".to_string(),
            summary: String::new(),
            metadata: "{}".to_string(),
            created_at: 5_000,
            updated_at: 5_000,
        };
        assert_eq!(equal_ts.updated_at, equal_ts.created_at);
    }

    #[test]
    fn test_session_clone_maintains_fields() {
        let session = Session {
            id: "sess_clone".to_string(),
            workspace_id: "ws".to_string(),
            name: "CloneTest".to_string(),
            summary: "summary".to_string(),
            metadata: r#"{"key":"value"}"#.to_string(),
            created_at: 10,
            updated_at: 20,
        };
        let cloned = session.clone();
        assert_eq!(cloned.id, session.id);
        assert_eq!(cloned.name, session.name);
        assert_eq!(cloned.summary, session.summary);
        assert_eq!(cloned.metadata, session.metadata);
    }

    #[test]
    fn test_session_participant_clone() {
        let sp = SessionParticipant {
            session_id: "sess".to_string(),
            peer_id: "peer".to_string(),
            role: "viewer".to_string(),
            joined_at: 99,
        };
        let cloned = sp.clone();
        assert_eq!(cloned.session_id, sp.session_id);
        assert_eq!(cloned.peer_id, sp.peer_id);
        assert_eq!(cloned.role, "viewer");
        assert_eq!(cloned.joined_at, 99);
    }

    #[test]
    fn test_agent_step_all_step_types() {
        let step_types = vec!["thought", "action", "observation", "tool_call", "tool_result"];
        for st in step_types {
            let step = AgentStep {
                id: format!("step_{}", st),
                session_id: "sess".to_string(),
                workspace_id: "ws".to_string(),
                step_type: st.to_string(),
                content: format!("content_{}", st),
                summary: format!("summary_{}", st),
                parent_step_id: "parent".to_string(),
                created_at: 0,
            };
            assert_eq!(step.step_type, st);
            assert_eq!(step.content, format!("content_{}", st));
        }
    }

    #[test]
    fn test_agent_step_long_content() {
        let long_content = "c".repeat(10_000);
        let step = AgentStep {
            id: "step_long".to_string(),
            session_id: "sess".to_string(),
            workspace_id: "ws".to_string(),
            step_type: "observation".to_string(),
            content: long_content.clone(),
            summary: String::new(),
            parent_step_id: String::new(),
            created_at: 0,
        };
        assert_eq!(step.content.len(), 10_000);
        assert_eq!(step.content, long_content);
    }

    #[test]
    fn test_session_debug_format() {
        let session = Session {
            id: "debug_sess".to_string(),
            workspace_id: "ws".to_string(),
            name: "DebugSession".to_string(),
            summary: "test".to_string(),
            metadata: "{}".to_string(),
            created_at: 0,
            updated_at: 0,
        };
        let debug = format!("{:?}", session);
        assert!(debug.contains("debug_sess"));
        assert!(debug.contains("DebugSession"));
    }

    #[test]
    fn test_session_step_result_empty_strings() {
        let result = SessionStepResult {
            query_hash: String::new(),
            id: String::new(),
            session_id: String::new(),
            workspace_id: String::new(),
            step_type: String::new(),
            content: String::new(),
            summary: String::new(),
            parent_step_id: String::new(),
            created_at: 0,
        };
        assert_eq!(result.query_hash, "");
        assert_eq!(result.id, "");
        assert_eq!(result.step_type, "");
    }
}
