use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v4};
use crate::workspace::check_space_access;

/// A session represents a conversation or interaction within a workspace.
#[table(accessor = session)]
#[derive(Debug, Clone)]
pub struct Session {
    #[primary_key]
    pub id: String,
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
#[derive(Debug, Clone)]
pub struct AgentStep {
    #[primary_key]
    pub id: String,
    pub session_id: String,
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
#[table(accessor = session_step_result, public)]
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
    let id = uuid_v4(ctx);

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
        .iter()
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
        .iter()
        .any(|sp| sp.session_id == session_id && sp.peer_id == peer_id);

    if !exists {
        return Err(format!(
            "Peer '{}' is not a participant in session '{}'",
            peer_id, session_id
        ));
    }

    // Delete matching rows (table has no PK, so iterate and delete each row)
    let to_delete: Vec<_> = ctx.db.session_participant()
        .iter()
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

    session.summary = summary;
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
    let id = uuid_v4(ctx);

    // Verify session exists
    ctx.db
        .session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Session '{}' not found", session_id))?;

    ctx.db.agent_step().insert(AgentStep {
        id: id.clone(),
        session_id: session_id.clone(),
        workspace_id,
        step_type,
        content,
        summary,
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

    let mut steps: Vec<_> = ctx.db.agent_step().iter().take(crate::MAX_RESULTS)
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
    let to_delete: Vec<_> = ctx.db.agent_step().iter().take(crate::MAX_RESULTS)
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
