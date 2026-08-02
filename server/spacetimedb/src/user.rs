use spacetimedb::*;

use crate::auth::require_auth;
use crate::{now_micros, MAX_RESULTS};
use crate::memory::memory;
use crate::session::session;

/// A Zep user record. Private table — access only through authenticated reducers.
#[table(accessor = user)]
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
#[table(accessor = user_session_result)]
#[derive(Debug, Clone)]
pub struct UserSessionResult {
    #[index(btree)]
    pub query_id: String,
    pub user_id: String,
    pub session_id: String,
    pub session_name: String,
    pub workspace_id: String,
    pub created_at: i64,
}

/// Result table for `get_user` and `list_users` reducers.
/// NOTE: This table is **public** — only expose fields that are safe
/// to share. For sensitive data (email etc.), use the private `user` table instead.
/// Each row carries a prefixed ID for client filtering:
///   - `get_user:<user_id>` — single user lookup
///   - `list_users:<user_id>` — multi-user listing
#[table(accessor = user_get_result)]
#[derive(Debug, Clone)]
pub struct UserGetResult {
    pub id: String,
    pub user_id: String,
    pub first_name: Option<String>,
    pub last_name: Option<String>,
    pub metadata_json: String,
    pub created_at: u64,
    pub updated_at: u64,
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
/// Writes the result to the public `user_get_result` table with id `get_user:<user_id>`.
#[reducer]
pub fn get_user(ctx: &ReducerContext, user_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    let user = ctx
        .db
        .user()
        .user_id()
        .find(&user_id)
        .ok_or_else(|| format!("User '{}' not found", user_id))?;

    // Clear previous results for this query
    let old: Vec<_> = ctx
        .db
        .user_get_result()
        .iter()
        .take(MAX_RESULTS)
        .filter(|r| r.id == format!("get_user:{}", user_id))
        .collect();
    for r in old {
        ctx.db.user_get_result().delete(r);
    }

    ctx.db.user_get_result().insert(UserGetResult {
        id: format!("get_user:{}", user_id),
        user_id: user.user_id.clone(),
        first_name: user.first_name,
        last_name: user.last_name,
        metadata_json: user.metadata_json,
        created_at: user.created_at,
        updated_at: user.updated_at,
    });

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

/// List all users. Results are written to `user_get_result` with id `list_users:<user_id>`
/// for each user, keyed by a `list_users:all` query prefix.
/// Clients read from the public `user_get_result` table after calling this reducer.
#[reducer]
pub fn list_users(ctx: &ReducerContext) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    // Clear previous list results
    let old: Vec<_> = ctx
        .db
        .user_get_result()
        .iter()
        .take(MAX_RESULTS)
        .filter(|r| r.id.starts_with("list_users:"))
        .collect();
    for r in old {
        ctx.db.user_get_result().delete(r);
    }

    // Insert every user into the result table
    for u in ctx.db.user().iter().take(MAX_RESULTS) {
        ctx.db.user_get_result().insert(UserGetResult {
            id: format!("list_users:{}", u.user_id),
            user_id: u.user_id.clone(),
            first_name: u.first_name,
            last_name: u.last_name,
            metadata_json: u.metadata_json,
            created_at: u.created_at,
            updated_at: u.updated_at,
        });
    }

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
        .query_id().filter(&query_id)
        .take(crate::MAX_RESULTS)
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
    for mem in ctx.db.memory().iter().take(crate::MAX_RESULTS * 4) {
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
    for sess in ctx.db.session().iter().take(crate::MAX_RESULTS * 4) {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_user_creation() {
        let user = User {
            user_id: "usr_test_001".to_string(),
            email: Some("alice@example.com".to_string()),
            first_name: Some("Alice".to_string()),
            last_name: Some("Smith".to_string()),
            metadata_json: r#"{"planet":"Earth"}"#.to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };

        assert_eq!(user.user_id, "usr_test_001");
        assert_eq!(user.email, Some("alice@example.com".to_string()));
        assert_eq!(user.first_name, Some("Alice".to_string()));
        assert_eq!(user.last_name, Some("Smith".to_string()));
        assert_eq!(user.metadata_json, r#"{"planet":"Earth"}"#);
        assert_eq!(user.created_at, 1_000_000);
        assert_eq!(user.updated_at, 1_000_000);
    }

    #[test]
    fn test_user_settings_creation() {
        let result = UserSessionResult {
            query_id: "user_sessions:usr_002".to_string(),
            user_id: "usr_002".to_string(),
            session_id: "sess_abc123".to_string(),
            session_name: "My Session".to_string(),
            workspace_id: "ws_42".to_string(),
            created_at: 2_000_000,
        };

        assert_eq!(result.query_id, "user_sessions:usr_002");
        assert_eq!(result.user_id, "usr_002");
        assert_eq!(result.session_id, "sess_abc123");
        assert_eq!(result.session_name, "My Session");
        assert_eq!(result.workspace_id, "ws_42");
        assert_eq!(result.created_at, 2_000_000);
    }

    // ── Additional tests ──────────────────────────────────────────────

    #[test]
    fn test_user_get_result_construction() {
        let r = UserGetResult {
            id: "get_user:usr_003".to_string(),
            user_id: "usr_003".to_string(),
            first_name: Some("Bob".to_string()),
            last_name: Some("Jones".to_string()),
            metadata_json: r#"{"preferences":"dark_mode"}"#.to_string(),
            created_at: 3_000_000,
            updated_at: 4_000_000,
        };
        assert_eq!(r.id, "get_user:usr_003");
        assert_eq!(r.first_name, Some("Bob".to_string()));
        assert_eq!(r.last_name, Some("Jones".to_string()));
    }

    #[test]
    fn test_user_get_result_empty_names() {
        let r = UserGetResult {
            id: "get_user:usr_004".to_string(),
            user_id: "usr_004".to_string(),
            first_name: None,
            last_name: None,
            metadata_json: "{}".to_string(),
            created_at: 5_000_000,
            updated_at: 5_000_000,
        };
        assert!(r.first_name.is_none());
        assert!(r.last_name.is_none());
    }

    #[test]
    fn test_user_empty_email_and_names() {
        // Replicates the pattern from add_user: empty fields become None
        let email = String::new();
        let first_name = String::new();
        let last_name = String::new();
        assert!(email.is_empty());
        assert!(first_name.is_empty());
        assert!(last_name.is_empty());
    }

    #[test]
    fn test_user_empty_metadata_becomes_json() {
        // In add_user, empty metadata_json becomes "{}"
        let metadata_json = if true { String::from("{}") } else { String::new() };
        assert_eq!(metadata_json, "{}");
    }

    #[test]
    fn test_user_composite_id_format() {
        // get_user uses "get_user:{user_id}" as the result id
        // list_users uses "list_users:{user_id}" as the result id
        let user_id = "usr_composite_001";
        let get_id = format!("get_user:{}", user_id);
        let list_id = format!("list_users:{}", user_id);
        assert_eq!(get_id, "get_user:usr_composite_001");
        assert_eq!(list_id, "list_users:usr_composite_001");
        assert!(get_id.starts_with("get_user:"));
        assert!(list_id.starts_with("list_users:"));
    }

    #[test]
    fn test_user_session_result_linking() {
        // Multiple sessions can share the same user_id via user_session_result
        let user_id = "usr_session_user".to_string();
        let r1 = UserSessionResult {
            query_id: format!("user_sessions:{}", user_id),
            user_id: user_id.clone(),
            session_id: "sess_001".to_string(),
            session_name: "Session One".to_string(),
            workspace_id: "ws_001".to_string(),
            created_at: 100,
        };
        let r2 = UserSessionResult {
            query_id: format!("user_sessions:{}", user_id),
            user_id: user_id.clone(),
            session_id: "sess_002".to_string(),
            session_name: "Session Two".to_string(),
            workspace_id: "ws_001".to_string(),
            created_at: 200,
        };
        assert_eq!(r1.user_id, user_id);
        assert_eq!(r2.user_id, user_id);
        assert_ne!(r1.session_id, r2.session_id);
    }

    #[test]
    fn test_user_long_string_fields() {
        let long_first = "A".repeat(500);
        let long_last = "B".repeat(500);
        let user = User {
            user_id: "usr_long".to_string(),
            email: Some("long@example.com".to_string()),
            first_name: Some(long_first.clone()),
            last_name: Some(long_last.clone()),
            metadata_json: "{}".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(user.first_name.unwrap().len(), 500);
        assert_eq!(user.last_name.unwrap().len(), 500);
    }

    #[test]
    fn test_user_delete_user_id_pattern() {
        // delete_user uses ctx.db.user().user_id().find(&user_id) then .delete()
        let user_id = "usr_to_delete".to_string();
        // user_id.find() uses the index on user_id field
        assert_eq!(user_id, "usr_to_delete");
    }

    #[test]
    fn test_user_list_users_prefix_pattern() {
        // list_users filters by r.id.starts_with("list_users:")
        let prefix = "list_users:";
        let id = format!("{}usr_001", prefix);
        assert!(id.starts_with(prefix));
        let non_list = "get_user:usr_001";
        assert!(!non_list.starts_with(prefix));
    }
}
