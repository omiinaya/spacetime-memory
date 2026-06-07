use spacetimedb::*;
use crate::{uuid_v4, now_micros};
use sha2::{Sha256, Digest};
use pbkdf2::pbkdf2_hmac;

// ── Tables ────────────────────────────────────────────────────────────

/// User account with password auth.
#[table(accessor = account, public)]
#[derive(Debug, Clone)]
pub struct Account {
    #[primary_key]
    pub id: String,             // ctx.sender().to_hex() as PK
    pub username: String,
    pub display_name: String,
    pub password_hash: String,  // hex(PBKDF2(password, salt))
    pub password_salt: String,  // hex(random salt)
    pub role: String,           // "admin" | "user"
    pub is_active: bool,
    pub created_at: i64,
    pub updated_at: i64,
}

/// An API key for programmatic access.
#[table(accessor = api_key, public)]
#[derive(Debug, Clone)]
pub struct ApiKey {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub key_hash: String,
    pub name: String,
    pub permissions: String,
    pub is_active: bool,
    pub created_at: i64,
    pub last_used_at: i64,
}

// ── Reducers ──────────────────────────────────────────────────────────

/// Register a new account. First user is admin.
#[reducer]
pub fn register(
    ctx: &ReducerContext,
    username: String,
    display_name: String,
    password: String,
) -> Result<(), String> {
    let identity = ctx.sender().to_hex().to_string();

    if username.trim().is_empty() {
        return Err("Username cannot be empty".to_string());
    }
    if password.len() < 6 {
        return Err("Password must be at least 6 characters".to_string());
    }

    // Check for existing accounts (first user = admin)
    let existing_count = ctx.db.account().iter().count();
    let role = if existing_count == 0 { "admin" } else { "user" };

    // Check if this identity already has an account
    if ctx.db.account().id().find(&identity).is_some() {
        return Err("This identity already has an account".to_string());
    }

    // Check username uniqueness
    let name_taken = ctx.db.account().iter()
        .any(|a: Account| a.username.to_lowercase() == username.trim().to_lowercase());
    if name_taken {
        return Err("Username already taken".to_string());
    }

    let now = now_micros(ctx);
    let salt = derive_salt(&identity, now);
    let hash = hash_password(&password, &salt);

    ctx.db.account().insert(Account {
        id: identity.clone(),  // identity hex as PK
        username: username.trim().to_string(),
        display_name: if display_name.trim().is_empty() { username.trim().to_string() } else { display_name.trim().to_string() },
        password_hash: hex::encode(hash),
        password_salt: hex::encode(salt),
        role: role.to_string(),
        is_active: true,
        created_at: now,
        updated_at: now,
    });

    Ok(())
}

/// Login with username + password. Links this WebSocket identity to the account.
#[reducer]
pub fn login(ctx: &ReducerContext, username: String, password: String) -> Result<(), String> {
    let identity = ctx.sender().to_hex().to_string();

    let account = ctx.db.account().iter()
        .find(|a: &Account| a.username.to_lowercase() == username.trim().to_lowercase() && a.is_active)
        .ok_or_else(|| "Invalid username or password".to_string())?;

    // Verify password
    let salt = hex::decode(&account.password_salt)
        .map_err(|_| "Internal error: invalid salt".to_string())?;
    let expected_hash = hex::decode(&account.password_hash)
        .map_err(|_| "Internal error: invalid hash".to_string())?;

    let computed = hash_password(&password, &salt);

    if computed != expected_hash {
        return Err("Invalid username or password".to_string());
    }

    // If the identity changed (different browser), update it so this account
    // is now associated with this identity going forward
    if account.id != identity {
        // Delete old identity row, insert with new identity
        // First check if new identity collides with another account
        if ctx.db.account().id().find(&identity).is_some() {
            return Err("This browser identity is already linked to another account".to_string());
        }
        ctx.db.account().id().delete(&account.id);

        let mut updated = account;
        updated.id = identity;
        updated.updated_at = now_micros(ctx);
        ctx.db.account().insert(updated);
    } else {
        // Just update the timestamp
        let mut updated = account;
        updated.updated_at = now_micros(ctx);
        ctx.db.account().id().update(updated);
    }

    Ok(())
}

/// Logout — detach identity from account.
/// The user must re-login to access gated features.
#[reducer]
pub fn logout(ctx: &ReducerContext) -> Result<(), String> {
    let identity = ctx.sender().to_hex().to_string();

    if let Some(account) = ctx.db.account().id().find(&identity) {
        let mut updated = account;
        updated.id = String::new();  // detach
        updated.updated_at = now_micros(ctx);
        ctx.db.account().id().update(updated);
    }

    Ok(())
}

/// Update account settings.
#[reducer]
pub fn update_account(
    ctx: &ReducerContext,
    display_name: String,
    current_password: String,
    new_password: String,
) -> Result<(), String> {
    let identity = ctx.sender().to_hex().to_string();

    let account = require_auth(ctx)?;

    // Verify current password
    let salt = hex::decode(&account.password_salt)
        .map_err(|_| "Internal error".to_string())?;
    let expected_hash = hex::decode(&account.password_hash)
        .map_err(|_| "Internal error".to_string())?;
    let computed = hash_password(&current_password, &salt);
    if computed != expected_hash {
        return Err("Current password is incorrect".to_string());
    }

    let now = now_micros(ctx);
    let mut updated = account;

    if !display_name.trim().is_empty() {
        updated.display_name = display_name.trim().to_string();
    }

    if !new_password.is_empty() {
        if new_password.len() < 6 {
            return Err("New password must be at least 6 characters".to_string());
        }
        let new_salt = derive_salt(&identity, now);
        let new_hash = hash_password(&new_password, &new_salt);
        updated.password_hash = hex::encode(new_hash);
        updated.password_salt = hex::encode(new_salt);
    }

    updated.updated_at = now;
    ctx.db.account().id().update(updated);

    Ok(())
}

/// Deactivate account (soft delete).
#[reducer]
pub fn deactivate_account(ctx: &ReducerContext, password: String) -> Result<(), String> {
    let account = require_auth(ctx)?;

    let salt = hex::decode(&account.password_salt).map_err(|_| "Internal error".to_string())?;
    let expected_hash = hex::decode(&account.password_hash).map_err(|_| "Internal error".to_string())?;
    let computed = hash_password(&password, &salt);
    if computed != expected_hash {
        return Err("Password is incorrect".to_string());
    }

    let mut updated = account;
    updated.is_active = false;
    updated.updated_at = now_micros(ctx);
    ctx.db.account().id().update(updated);
    Ok(())
}

/// Create an API key.
#[reducer]
pub fn create_api_key(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    permissions: String,
    key_hash: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    // Validate permissions JSON
    if serde_json::from_str::<Vec<String>>(&permissions).is_err() {
        return Err("permissions must be a valid JSON array of strings".to_string());
    }

    ctx.db.api_key().insert(ApiKey {
        id: uuid_v4(ctx),
        workspace_id,
        key_hash,
        name,
        permissions,
        is_active: true,
        created_at: now_micros(ctx),
        last_used_at: 0,
    });
    Ok(())
}

/// Deactivate an API key.
#[reducer]
pub fn deactivate_api_key(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let mut key = ctx.db.api_key().id().find(&id)
        .ok_or_else(|| "API key not found".to_string())?;
    key.is_active = false;
    ctx.db.api_key().id().update(key);
    Ok(())
}

// ── Auth Guards ───────────────────────────────────────────────────────

/// Require authentication. Returns the Account or an error.
pub fn require_auth(ctx: &ReducerContext) -> Result<Account, String> {
    let identity = ctx.sender().to_hex().to_string();
    ctx.db.account().id().find(&identity)
        .filter(|a: &Account| a.is_active)
        .ok_or_else(|| "Not authenticated".to_string())
}

/// Require admin role.
pub fn require_admin(ctx: &ReducerContext) -> Result<Account, String> {
    let account = require_auth(ctx)?;
    if account.role != "admin" {
        return Err("Admin access required".to_string());
    }
    Ok(account)
}

/// Check if the caller is authenticated (no error, just bool).
pub fn is_authenticated(ctx: &ReducerContext) -> bool {
    let identity = ctx.sender().to_hex().to_string();
    ctx.db.account().id().find(&identity)
        .map_or(false, |a: Account| a.is_active)
}

// ── Crypto Helpers ────────────────────────────────────────────────────

const PBKDF2_ITERATIONS: u32 = 100_000;

/// Hash password with PBKDF2-HMAC-SHA256.
fn hash_password(password: &str, salt: &[u8]) -> Vec<u8> {
    let mut output = vec![0u8; 32];
    pbkdf2_hmac::<Sha256>(
        password.as_bytes(),
        salt,
        PBKDF2_ITERATIONS,
        &mut output,
    );
    output
}

/// Derive a deterministic salt from identity + timestamp.
/// For a personal app this is acceptable; a production app would use
/// client-side generated salts submitted as a parameter.
fn derive_salt(identity: &str, timestamp: i64) -> Vec<u8> {
    let mut hasher = Sha256::new();
    hasher.update(identity.as_bytes());
    hasher.update(&timestamp.to_le_bytes());
    hasher.update(b"spacetime-memory-auth-salt");
    hasher.finalize().to_vec()
}
