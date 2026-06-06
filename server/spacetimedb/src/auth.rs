use spacetimedb::*;
use crate::{uuid_v4, now_micros};

/// API keys for programmatic access
#[table(accessor = api_key, public)]
#[derive(Debug, Clone)]
pub struct ApiKey {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub key_hash: String,
    pub name: String,
    pub permissions: String, // JSON array: ["read", "write", "admin"]
    pub is_active: bool,
    pub created_at: i64,
    pub last_used_at: i64,
}

/// Identity-based auth tokens
#[table(accessor = auth_session, public)]
#[derive(Debug, Clone)]
pub struct AuthSession {
    #[primary_key]
    pub id: String,
    pub peer_id: String,
    pub token_hash: String,
    pub expires_at: i64,
    pub created_at: i64,
}

/// Create a new API key for a workspace
#[reducer]
pub fn create_api_key(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    permissions: String,
    key_hash: String,
) -> Result<(), String> {
    // Validate permissions is valid JSON array
    if serde_json::from_str::<Vec<String>>(&permissions).is_err() {
        return Err("permissions must be a valid JSON array of strings".to_string());
    }

    ctx.db.api_key().insert(ApiKey {
        id: uuid_v4(),
        workspace_id,
        key_hash,
        name,
        permissions,
        is_active: true,
        created_at: now_micros(),
        last_used_at: 0,
    });
    Ok(())
}

/// Deactivate an API key
#[reducer]
pub fn deactivate_api_key(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let mut key = ctx.db.api_key().id().find(&id)
        .ok_or_else(|| "API key not found".to_string())?;
    key.is_active = false;
    ctx.db.api_key().id().update(key);
    Ok(())
}

/// Create an auth session for a peer
#[reducer]
pub fn create_auth_session(
    ctx: &ReducerContext,
    peer_id: String,
    token_hash: String,
    ttl_minutes: i64,
) -> Result<(), String> {
    let expires_at = if ttl_minutes > 0 {
        now_micros() + ttl_minutes * 60_000_000
    } else {
        now_micros() + 7 * 86_400_000_000 // default 7 days
    };

    ctx.db.auth_session().insert(AuthSession {
        id: uuid_v4(),
        peer_id,
        token_hash,
        expires_at,
        created_at: now_micros(),
    });
    Ok(())
}

/// Revoke an auth session
#[reducer]
pub fn revoke_auth_session(ctx: &ReducerContext, id: String) -> Result<(), String> {
    ctx.db.auth_session().id().delete(&id);
    Ok(())
}

/// Clean up expired auth sessions
#[reducer]
pub fn cleanup_expired_sessions(ctx: &ReducerContext) -> Result<(), String> {
    let now = now_micros();
    let expired: Vec<AuthSession> = ctx.db.auth_session()
        .iter()
        .filter(|s| s.expires_at > 0 && s.expires_at < now)
        .collect();

    for session in expired {
        ctx.db.auth_session().id().delete(&session.id);
    }
    Ok(())
}
