use spacetimedb::*;

use crate::auth::require_auth;
use crate::{now_micros, MAX_RESULTS};
use crate::memory::memory;
use crate::session::session;

/// A Zep user record. Public table — clients can query directly.
#[table(accessor = user, public)]
#[derive(Debug, Clone)]
pub struct User {
    #[primary_key]
    pub user_id: String,
    pub email: Option<String>,
    pub first_name: Option<String>,
    pub last_name: Option<String>,
    pub metadata_json: String,
    pub created_at: u64,
    pub updated_at: u64,
}

/// Temporary result table for `get_user_sessions` reducer.
/// Clients read from this table after calling the reducer.
#[table(accessor = user_session_result, public)]
#[derive(Debug, Clone)]
pub struct UserSessionResult {
    pub query_id: String,
    pub user_id: String,
    pub session_id: String,
    pub session_name: String,
    pub workspace_id: String,
    pub created_at: i64,
}

// ── Reducers ──────────────────────────────────────────────────────────────

/// Add a new user.
#[reducer]
pub fn add_user(
    ctx: &ReducerContext,
    user_id: String,
    email: String,
    first_name: String,
    last_name: String,
    metadata_json: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    if user_id.trim().is_empty() {
        return Err("user_id cannot be empty".to_string());
    }

    // Check for duplicate
    if ctx.db.user().user_id().find(&user_id).is_some() {
        return Err(format!("User '{}' already exists", user_id));
    }

    let now = now_micros(ctx) as u64;

    ctx.db.user().insert(User {
        user_id,
        email: if email.is_empty() { None } else { Some(email) },
        first_name: if first_name.is_empty() { None } else { Some(first_name) },
        last_name: if last_name.is_empty() { None } else { Some(last_name) },
        metadata_json: if metadata_json.is_empty() { String::from("{}") } else { metadata_json },
        created_at: now,
        updated_at: now,
    });

    Ok(())
}

/// Get a single user by user_id.
/// The user table is public — clients can query it directly after this reducer
/// verifies authentication.
#[reducer]
pub fn get_user(ctx: &ReducerContext, user_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    ctx.db
        .user()
        .user_id()
        .find(&user_id)
        .ok_or_else(|| format!("User '{}' not found", user_id))?;

    Ok(())
}

/// Update an existing user. Only supplied fields are updated.
#[reducer]
pub fn update_user(
    ctx: &ReducerContext,
    user_id: String,
    email: String,
    first_name: String,
    last_name: String,
    metadata_json: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    let mut user = ctx
        .db
        .user()
        .user_id()
        .find(&user_id)
        .ok_or_else(|| format!("User '{}' not found", user_id))?;

    if !email.is_empty() {
        user.email = Some(email);
    }
    if !first_name.is_empty() {
        user.first_name = Some(first_name);
    }
    if !last_name.is_empty() {
        user.last_name = Some(last_name);
    }
    if !metadata_json.is_empty() {
        user.metadata_json = metadata_json;
    }

    user.updated_at = now_micros(ctx) as u64;
    ctx.db.user().user_id().update(user);

    Ok(())
}

/// Delete a user by user_id.
#[reducer]
pub fn delete_user(ctx: &ReducerContext, user_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    let user = ctx
        .db
        .user()
        .user_id()
        .find(&user_id)
        .ok_or_else(|| format!("User '{}' not found", user_id))?;

    ctx.db.user().user_id().delete(&user.user_id);
    Ok(())
}

/// List all users. The user table is public — clients can query it directly
/// after this reducer verifies authentication.
#[reducer]
pub fn list_users(ctx: &ReducerContext) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    // Just verify auth; clients query the public user table directly
    Ok(())
}

/// Get all sessions for a user. Results are stored in the `user_session_result`
/// public table, keyed by a generated `query_id`.
///
/// Queries the session and memory tables for sessions belonging to this user_id.
#[reducer]
pub fn get_user_sessions(ctx: &ReducerContext, user_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    let query_id = format!("user_sessions:{}", user_id);

    // Clear previous results for this query_id
    let old: Vec<_> = ctx
        .db
        .user_session_result()
        .iter()
        .filter(|r| r.query_id == query_id)
        .collect();
    for r in old {
        ctx.db.user_session_result().delete(r);
    }

    // Collect session IDs from the memory table where source_session_id references
    // sessions belonging to this user (by convention, source_session_id often
    // encodes the session ID). Also scan workspace names that match user patterns.
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut count: usize = 0;

    // Scan memory table for any session references tied to this user
    // (Memories with this user_id in peer_id or source_session_id)
    for mem in ctx.db.memory().iter() {
        if count >= MAX_RESULTS {
            break;
        }
        let session_id = if !mem.source_session_id.is_empty() {
            mem.source_session_id.clone()
        } else if mem.peer_id == user_id {
            // fallback: use peer_id as a session key
            mem.peer_id.clone()
        } else {
            continue;
        };

        if seen.contains(&session_id) {
            continue;
        }
        seen.insert(session_id.clone());

        // Try to resolve workspace name from the session or workspace table
        let workspace_id = mem.workspace_id.clone();
        let session_name = session_id.clone();

        ctx.db.user_session_result().insert(UserSessionResult {
            query_id: query_id.clone(),
            user_id: user_id.clone(),
            session_id: session_id.clone(),
            session_name,
            workspace_id,
            created_at: mem.created_at,
        });
        count += 1;
    }

    // Also scan sessions table for any with matching metadata or name containing user_id
    for sess in ctx.db.session().iter() {
        if count >= MAX_RESULTS {
            break;
        }
        let session_id = sess.id.clone();
        if seen.contains(&session_id) {
            continue;
        }
        // Check if session name or metadata references this user_id
        if sess.name.contains(&user_id) || sess.metadata.contains(&user_id) {
            seen.insert(session_id.clone());
            ctx.db.user_session_result().insert(UserSessionResult {
                query_id: query_id.clone(),
                user_id: user_id.clone(),
                session_id: session_id.clone(),
                session_name: sess.name.clone(),
                workspace_id: sess.workspace_id.clone(),
                created_at: sess.created_at,
            });
            count += 1;
        }
    }

    Ok(())
}
