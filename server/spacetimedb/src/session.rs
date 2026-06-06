use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// A session represents a conversation or interaction within a workspace.
#[table(accessor = session, public)]
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
#[table(accessor = session_participant, public)]
#[derive(Debug, Clone)]
pub struct SessionParticipant {
    pub session_id: String,
    pub peer_id: String,
    pub role: String,
    pub joined_at: i64,
}

#[reducer]
pub fn create_session(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    metadata_json: String,
) -> Result<(), String> {
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
    // Verify session exists
    ctx.db
        .session()
        .id()
        .find(&session_id)
        .ok_or_else(|| format!("Session '{}' not found", session_id))?;

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
    // Verify the participant exists (composite key lookup via iteration)
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
