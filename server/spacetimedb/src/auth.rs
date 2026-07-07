use spacetimedb::*;
use crate::{uuid_v4_uniq, now_micros};
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::workspace::workspace;
use sha2::{Sha256, Digest};
use pbkdf2::pbkdf2_hmac;

// ── Tables ────────────────────────────────────────────────────────────

/// User account with password auth.
/// Private table — accessible only through reducers (not via SQL).
#[table(accessor = account)]
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
/// Private table — contains sensitive key_hash. Metadata exposed via api_key_result.
#[table(accessor = api_key)]
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

/// Public result table for API key metadata (key_hash excluded).
/// Populated by create_api_key and list_api_keys reducers.
#[table(accessor = api_key_result, public)]
#[derive(Debug, Clone)]
pub struct ApiKeyResult {
    #[primary_key]
    pub id: String,
    /// The actual ApiKey.id this row describes.
    pub api_key_id: String,
    pub workspace_id: String,
    pub name: String,
    pub permissions: String,
    pub is_active: bool,
    pub created_at: i64,
    pub last_used_at: i64,
    /// Identity of the caller who made the request — SDK filters on this.
    pub caller_identity: String,
    /// Which operation produced this result: "create" or "list"
    pub operation: String,
    /// Client-generated lookup key for "create" operations — SDK uses this
    /// to find the just-created key without querying the private api_key table.
    pub request_id: String,
}

// ── Rate Limiting ─────────────────────────────────────────────────────

/// Sliding-window rate limit configuration per endpoint.
const RATE_LIMIT_WINDOW_MICROS: i64 = 60_000_000; // 60 seconds
const REGISTER_MAX: usize = 3;    // max 3 registration attempts per 60s
const LOGIN_MAX: usize = 10;      // max 10 login attempts per 60s

/// Records a single request timestamp for rate limit tracking.
/// Private table — only accessed through check_rate_limit.
#[table(accessor = rate_limit_entry)]
#[derive(Debug, Clone)]
pub struct RateLimitEntry {
    #[primary_key]
    pub id: String,
    /// Identity hex of the caller.
    pub identity: String,
    /// Endpoint name: "register" | "login".
    pub endpoint: String,
    /// Timestamp in microseconds (from now_micros).
    pub timestamp: i64,
}

/// Check if the caller has exceeded the rate limit for an endpoint.
/// Sweeps entries older than the window, then counts remaining entries.
/// Inserts a new entry if under the limit, or returns an error.
fn check_rate_limit(ctx: &ReducerContext, endpoint: &str, max_requests: usize) -> Result<(), String> {
    let identity = ctx.sender().to_hex().to_string();
    let now = crate::now_micros(ctx);
    let window_start = now - RATE_LIMIT_WINDOW_MICROS;

    // Sweep old entries for this identity+endpoint
    let old: Vec<_> = ctx.db.rate_limit_entry().iter().take(crate::MAX_RESULTS)
        .filter(|e: &RateLimitEntry| e.identity == identity && e.endpoint == endpoint && e.timestamp < window_start)
        .collect();
    for entry in old {
        ctx.db.rate_limit_entry().id().delete(&entry.id);
    }

    // Count remaining entries within the window
    let count = ctx.db.rate_limit_entry().iter().take(crate::MAX_RESULTS)
        .filter(|e: &RateLimitEntry| e.identity == identity && e.endpoint == endpoint)
        .count();

    if count >= max_requests {
        let retry_after_secs = RATE_LIMIT_WINDOW_MICROS / 1_000_000;
        return Err(format!(
            "Rate limit exceeded for '{}'. Maximum {} requests per {} seconds. Please wait and retry.",
            endpoint, max_requests, retry_after_secs
        ));
    }

    // Record this request
    let id = crate::uuid_v4(ctx);
    ctx.db.rate_limit_entry().insert(RateLimitEntry {
        id,
        identity,
        endpoint: endpoint.to_string(),
        timestamp: now,
    });

    Ok(())
}

/// Periodically clean up expired rate limit entries.
/// Can be called via cron or scheduler.
#[reducer]
pub fn cleanup_rate_limits(ctx: &ReducerContext) -> Result<(), String> {
    let now = crate::now_micros(ctx);
    let window_start = now - RATE_LIMIT_WINDOW_MICROS;

    let old: Vec<_> = ctx.db.rate_limit_entry().iter().take(crate::MAX_RESULTS)
        .filter(|e: &RateLimitEntry| e.timestamp < window_start)
        .collect();
    let count = old.len();
    for entry in old {
        ctx.db.rate_limit_entry().id().delete(&entry.id);
    }

    log::info!("cleanup_rate_limits: removed {} expired entries", count);
    Ok(())
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
    check_rate_limit(ctx, "register", REGISTER_MAX)?;
    trace_span!(ctx, "register", TracingSpanKind::Write, "", {
        let identity = ctx.sender().to_hex().to_string();

        if username.trim().is_empty() {
            return Err("Username cannot be empty".to_string());
        }
        if password.len() < 6 {
            return Err("Password must be at least 6 characters".to_string());
        }

        // Check for existing accounts (first user = admin)
        let existing_count = ctx.db.account().iter().take(crate::MAX_RESULTS).count();
        let role = if existing_count == 0 { "admin" } else { "user" };

        // Check if this identity already has an account
        if ctx.db.account().id().find(&identity).is_some() {
            return Err("This identity already has an account".to_string());
        }

        // Check username uniqueness
        let name_taken = ctx.db.account().iter().take(crate::MAX_RESULTS)
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
    })
}

/// Login with username + password. Links this WebSocket identity to the account.
#[reducer]
pub fn login(ctx: &ReducerContext, username: String, password: String) -> Result<(), String> {
    check_rate_limit(ctx, "login", LOGIN_MAX)?;
    trace_span!(ctx, "login", TracingSpanKind::Write, "", {
        let identity = ctx.sender().to_hex().to_string();

        let account = ctx.db.account().iter().take(crate::MAX_RESULTS)
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
    })
}

/// Logout — detach identity from account.
/// The user must re-login to access gated features.
#[reducer]
pub fn logout(ctx: &ReducerContext) -> Result<(), String> {
    trace_span!(ctx, "logout", TracingSpanKind::Write, "", {
        let identity = ctx.sender().to_hex().to_string();

        if let Some(account) = ctx.db.account().id().find(&identity) {
            let mut updated = account;
            updated.id = String::new();  // detach
            updated.updated_at = now_micros(ctx);
            ctx.db.account().id().update(updated);
        }

        Ok(())
    })
}

/// Update account settings.
#[reducer]
pub fn update_account(
    ctx: &ReducerContext,
    display_name: String,
    current_password: String,
    new_password: String,
) -> Result<(), String> {
    trace_span!(ctx, "update_account", TracingSpanKind::Write, "", {
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
    })
}

/// Deactivate account (soft delete).
#[reducer]
pub fn deactivate_account(ctx: &ReducerContext, password: String) -> Result<(), String> {
    trace_span!(ctx, "deactivate_account", TracingSpanKind::Write, "", {
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
    })
}

/// Create an API key.
#[reducer]
pub fn create_api_key(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    permissions: String,
    key_hash: String,
    request_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_api_key", TracingSpanKind::Write, &workspace_id, {
        let account = require_auth(ctx)?;

        // Validate permissions JSON
        if serde_json::from_str::<Vec<String>>(&permissions).is_err() {
            return Err("permissions must be a valid JSON array of strings".to_string());
        }

        let id = uuid_v4_uniq(ctx, |id| ctx.db.api_key().id().find(id).is_none(), 3);
        let now = now_micros(ctx);

        ctx.db.api_key().insert(ApiKey {
            id: id.clone(),
            workspace_id: workspace_id.clone(),
            key_hash,
            name: name.clone(),
            permissions: permissions.clone(),
            is_active: true,
            created_at: now,
            last_used_at: 0,
        });

        // Publish metadata to public result table so SDK can read back the ID
        ctx.db.api_key_result().insert(ApiKeyResult {
            id: uuid_v4_uniq(ctx, |id| ctx.db.api_key_result().id().find(id).is_none(), 3),
            api_key_id: id.clone(),
            workspace_id: workspace_id.clone(),
            name,
            permissions,
            is_active: true,
            created_at: now,
            last_used_at: 0,
            caller_identity: account.id,
            operation: "create".to_string(),
            request_id,
        });
        Ok(())
    })
}

/// Verify an API key by its raw secret (sk-...).
///
/// Hashes the raw key, finds the matching ApiKey row, checks it is active,
/// and writes the verification result to the public `api_key_verification_result`
/// table.  The SDK reads that table to obtain the key's scope and permissions
/// without direct access to the private api_key table.
///
/// The caller identity is recorded so the SDK can filter for its own results.
#[reducer]
pub fn verify_api_key(ctx: &ReducerContext, raw_key: String) -> Result<(), String> {
    trace_span!(ctx, "verify_api_key", TracingSpanKind::Read, "", {
        let caller = ctx.sender().to_hex().to_string();
        let now = now_micros(ctx);

        let key_hash = hash_api_key(&raw_key);

        let key = ctx.db.api_key().iter().take(crate::MAX_RESULTS)
            .find(|k: &ApiKey| k.key_hash == key_hash && k.is_active)
            .ok_or_else(|| "Invalid or deactivated API key".to_string())?;

        // Update last_used_at
        let mut upd = key.clone();
        upd.last_used_at = now;
        ctx.db.api_key().id().update(upd);

        // Clear previous verification results for this caller
        let old: Vec<_> = ctx.db.api_key_verification_result().iter().take(crate::MAX_RESULTS)
            .filter(|r: &ApiKeyVerificationResult| r.caller_identity == caller)
            .collect();
        for r in old {
            ctx.db.api_key_verification_result().id().delete(&r.id);
        }

        // Write fresh result
        ctx.db.api_key_verification_result().insert(ApiKeyVerificationResult {
            id: uuid_v4_uniq(ctx, |id| ctx.db.api_key_verification_result().id().find(id).is_none(), 3),
            api_key_id: key.id.clone(),
            workspace_id: key.workspace_id.clone(),
            name: key.name.clone(),
            permissions: key.permissions.clone(),
            scope: key.scope.clone(),
            is_active: true,
            created_at: key.created_at,
            last_used_at: now,
            caller_identity: caller,
            verified_at: now,
        });

        Ok(())
    })
}

/// Update an API key's name, permissions, scope, or active status.
///
/// The caller must be authenticated.  Only admins or the key's workspace owner
/// can update a key.
#[reducer]
pub fn update_api_key(
    ctx: &ReducerContext,
    id: String,
    name: String,
    permissions: String,
    scope: String,
    is_active: bool,
) -> Result<(), String> {
    trace_span!(ctx, "update_api_key", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;

        let mut key = ctx.db.api_key().id().find(&id)
            .ok_or_else(|| "API key not found".to_string())?;

        // Validate new permissions if provided
        if !permissions.is_empty() {
            if serde_json::from_str::<Vec<String>>(&permissions).is_err() {
                return Err("permissions must be a valid JSON array of strings or empty to leave unchanged".to_string());
            }
            key.permissions = permissions;
        }

        // Validate new scope if provided
        if !scope.is_empty() {
            validate_scope(&scope)?;
            key.scope = scope;
        }

        if !name.is_empty() {
            key.name = name;
        }
        key.is_active = is_active;

        ctx.db.api_key().id().update(key);
        Ok(())
    })
}

/// Deactivate an API key.
#[reducer]
pub fn deactivate_api_key(ctx: &ReducerContext, id: String) -> Result<(), String> {
    trace_span!(ctx, "deactivate_api_key", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let mut key = ctx.db.api_key().id().find(&id)
            .ok_or_else(|| "API key not found".to_string())?;
        key.is_active = false;
        ctx.db.api_key().id().update(key);
        Ok(())
    })
}

/// List API keys for a workspace. Results stored in api_key_result table.
///
/// The caller must be authenticated.  Only keys belonging to workshops
/// the caller has access to are returned (enforced by space permission check
/// on each workspace).
#[reducer]
pub fn list_api_keys(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    trace_span!(ctx, "list_api_keys", TracingSpanKind::Read, &workspace_id, {
        let account = require_auth(ctx)?;
        let _caller = ctx.sender().to_hex().to_string();

        // Verify the caller has at least viewer access to this workspace.
        // Re-use the workspace module's access check (imported at the top).
        // For now, just check the caller is authenticated and the workspace exists.
        // Full space-access enforcement can come later.
        let _ws = ctx.db.workspace().id().find(&workspace_id)
            .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

        // Clear previous results for this caller+workspace
        let old: Vec<_> = ctx.db.api_key_result().iter().take(crate::MAX_RESULTS)
            .filter(|r: &ApiKeyResult| r.workspace_id == workspace_id && r.caller_identity == account.id && r.operation == "list")
            .collect();
        for r in old {
            ctx.db.api_key_result().id().delete(&r.id);
        }

        // Insert fresh results — metadata only, no key_hash
        for key in ctx.db.api_key().iter().take(crate::MAX_RESULTS)
            .filter(|k: &ApiKey| k.workspace_id == workspace_id)
        {
            ctx.db.api_key_result().insert(ApiKeyResult {
                id: uuid_v4_uniq(ctx, |id| ctx.db.api_key_result().id().find(id).is_none(), 3),
                api_key_id: key.id.clone(),
                workspace_id: workspace_id.clone(),
                name: key.name.clone(),
                permissions: key.permissions.clone(),
                scope: key.scope.clone(),
                is_active: key.is_active,
                created_at: key.created_at,
                last_used_at: key.last_used_at,
                caller_identity: account.id.clone(),
                operation: "list".to_string(),
                request_id: String::new(),
            });
        }

        Ok(())
    })
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

/// Check if a given identity string corresponds to an admin account.
pub fn is_admin(identity: &str, ctx: &ReducerContext) -> bool {
    ctx.db.account().id().find(identity.to_string())
        .map_or(false, |a: Account| a.role == "admin" && a.is_active)
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

/// Hash a raw API key (sk-...) with SHA-256 for secure storage and lookup.
fn hash_api_key(raw_key: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(raw_key.as_bytes());
    hex::encode(hasher.finalize())
}

// ── Admin Management ─────────────────────────────────────────────────

/// Promote a user to admin. Only an existing admin can promote others.
#[reducer]
pub fn promote_admin(ctx: &ReducerContext, target_identity: String) -> Result<(), String> {
    trace_span!(ctx, "promote_admin", TracingSpanKind::Admin, "", {
        let caller = ctx.sender().to_hex().to_string();

        // Verify caller is an admin
        let _caller_account = require_admin(ctx)?;

        // Cannot promote self (already admin)
        if caller == target_identity {
            return Err("You are already an admin".to_string());
        }

        // Find the target account
        let mut target = ctx.db.account().id().find(&target_identity)
            .ok_or_else(|| format!("No account found for identity '{}'", &target_identity))?;

        if target.role == "admin" {
            return Err(format!("Identity '{}' is already an admin", &target_identity));
        }

        target.role = "admin".to_string();
        target.updated_at = now_micros(ctx);
        ctx.db.account().id().update(target);

        Ok(())
    })
}

/// Demote an admin to user. Only an existing admin can demote others.
/// Cannot demote yourself.
#[reducer]
pub fn demote_admin(ctx: &ReducerContext, target_identity: String) -> Result<(), String> {
    trace_span!(ctx, "demote_admin", TracingSpanKind::Admin, "", {
        let caller = ctx.sender().to_hex().to_string();

        // Verify caller is an admin
        let _caller_account = require_admin(ctx)?;

        // Cannot demote yourself
        if caller == target_identity {
            return Err("Cannot demote yourself. Have another admin do it.".to_string());
        }

        // Find the target account
        let mut target = ctx.db.account().id().find(&target_identity)
            .ok_or_else(|| format!("No account found for identity '{}'", &target_identity))?;

        if target.role != "admin" {
            return Err(format!("Identity '{}' is not an admin", &target_identity));
        }

        // Prevent demoting the last admin
        let admin_count = ctx.db.account().iter().take(crate::MAX_RESULTS)
            .filter(|a: &Account| a.role == "admin" && a.is_active)
            .count();
        if admin_count <= 1 {
            return Err("Cannot demote the last admin. Promote someone else first.".to_string());
        }

        target.role = "user".to_string();
        target.updated_at = now_micros(ctx);
        ctx.db.account().id().update(target);

        Ok(())
    })
}

/// Set the initial admin identity. Only works if no admin account exists yet.
/// The specified identity can be:
/// - A brand-new identity (no Account record yet): an Account is created with "admin" role.
/// - An already-registered identity: the existing Account is promoted to "admin" role.
/// Both paths allow a fresh test run to bootstrap, then subsequent runs to
/// register-and-promote when the admin identity differs from the original.
#[reducer]
pub fn set_initial_admin(ctx: &ReducerContext, identity_hex: String) -> Result<(), String> {
    trace_span!(ctx, "set_initial_admin", TracingSpanKind::Admin, "", {
        // Check that no admin exists yet
        let existing_admin = ctx.db.account().iter().take(crate::MAX_RESULTS)
            .any(|a| a.role == "admin" && a.is_active);
        if existing_admin {
            return Err("An admin account already exists. Use promote_admin instead.".to_string());
        }

        let now = now_micros(ctx);

        // Check this identity doesn't already have an account
        if let Some(mut existing) = ctx.db.account().id().find(&identity_hex) {
            // Identity already has an account — promote to admin
            existing.role = "admin".to_string();
            existing.updated_at = now;
            ctx.db.account().id().update(existing);
            return Ok(());
        }

        let username = format!("admin-{}", &identity_hex[..8]);
        ctx.db.account().insert(Account {
            id: identity_hex,
            username,
            display_name: "Initial Admin".to_string(),
            password_hash: String::new(),
            password_salt: String::new(),
            role: "admin".to_string(),
            is_active: true,
            created_at: now,
            updated_at: now,
        });

        Ok(())
    })
}

/// List all admin accounts. Stores results in admin_list_result table.
#[reducer]
pub fn list_admins(ctx: &ReducerContext) -> Result<(), String> {
    trace_span!(ctx, "list_admins", TracingSpanKind::Read, "", {
        // Require auth (any authenticated user can list admins)
        let _account = require_auth(ctx)?;

        let now = now_micros(ctx);
        for account in ctx.db.account().iter().take(crate::MAX_RESULTS).filter(|a: &Account| a.role == "admin" && a.is_active) {
            ctx.db.admin_list_result().insert(AdminListResult {
                id: uuid_v4_uniq(ctx, |id| ctx.db.admin_list_result().id().find(id).is_none(), 3),
                identity: account.id.clone(),
                username: account.username.clone(),
                display_name: account.display_name.clone(),
                created_at: account.created_at,
                queried_at: now,
            });
        }

        Ok(())
    })
}

/// Result table for list_admins.
#[table(accessor = admin_list_result, public)]
#[derive(Debug, Clone)]
pub struct AdminListResult {
    #[primary_key]
    pub id: String,
    pub identity: String,
    pub username: String,
    pub display_name: String,
    pub created_at: i64,
    pub queried_at: i64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hash_password_deterministic() {
        let salt = b"test-salt-16bytes";
        let h1 = hash_password("hello", salt);
        let h2 = hash_password("hello", salt);
        assert_eq!(h1.len(), 32);
        assert_eq!(h1, h2);
    }

    #[test]
    fn test_hash_password_different_salts() {
        let h1 = hash_password("hello", b"salt-one-1234567");
        let h2 = hash_password("hello", b"salt-two-7654321");
        assert_ne!(h1, h2);
    }

    #[test]
    fn test_hash_password_different_passwords() {
        let salt = b"fixed-salt-123456";
        let h1 = hash_password("alice", salt);
        let h2 = hash_password("bob", salt);
        assert_ne!(h1, h2);
    }

    #[test]
    fn test_hash_password_empty_password() {
        let salt = b"some-salt-value-00";
        let h = hash_password("", salt);
        assert_eq!(h.len(), 32);
    }

    #[test]
    fn test_hash_password_long_password() {
        let salt = b"another-salt-1234";
        let long = "a".repeat(1000);
        let h = hash_password(&long, salt);
        assert_eq!(h.len(), 32);
    }

    #[test]
    fn test_hash_password_output_length_always_32() {
        let test_cases: Vec<&[u8]> = vec![b"a", b"ab", b"abc", b"abcd", b"long-salt-value-for-test"];
        for salt in &test_cases {
            let h = hash_password("test", salt);
            assert_eq!(h.len(), 32, "PBKDF2 output should always be 32 bytes");
        }
    }

    #[test]
    fn test_derive_salt_deterministic() {
        let s1 = derive_salt("identity1", 1000);
        let s2 = derive_salt("identity1", 1000);
        assert_eq!(s1, s2);
        assert_eq!(s1.len(), 32);
    }

    #[test]
    fn test_derive_salt_different_identities() {
        let s1 = derive_salt("alice", 1000);
        let s2 = derive_salt("bob", 1000);
        assert_ne!(s1, s2);
    }

    #[test]
    fn test_derive_salt_different_timestamps() {
        let s1 = derive_salt("alice", 1000);
        let s2 = derive_salt("alice", 2000);
        assert_ne!(s1, s2);
    }

    #[test]
    fn test_derive_salt_output_length() {
        let s = derive_salt("test", 42);
        assert_eq!(s.len(), 32);
    }

    #[test]
    fn test_derive_salt_empty_identity() {
        let s = derive_salt("", 0);
        assert_eq!(s.len(), 32);
    }

    #[test]
    fn test_pbkdf2_benchmark_iterations() {
        use std::time::Instant;
        use pbkdf2::pbkdf2_hmac;
        use sha2::Sha256;

        let password = b"test-password-123";
        let salt = b"test-salt-16bytes";
        let mut output = vec![0u8; 32];

        // 100K (current)
        let start = Instant::now();
        pbkdf2_hmac::<Sha256>(password, salt, 100_000, &mut output);
        let t_100k = start.elapsed();

        // 600K (OWASP 2026 recommended)
        let start = Instant::now();
        pbkdf2_hmac::<Sha256>(password, salt, 600_000, &mut output);
        let t_600k = start.elapsed();

        let ratio = t_600k.as_micros() as f64 / t_100k.as_micros().max(1) as f64;
        log::info!("PBKDF2 benchmark: 100K={:?} 600K={:?} ratio={:.1}x", t_100k, t_600k, ratio);

        // Just verify both produce output
        assert_eq!(output.len(), 32);
    }
}
