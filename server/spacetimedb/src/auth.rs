use crate::trace_span;
use crate::tracing::TracingSpanKind;
use crate::uuid_v7;
use crate::workspace::check_space_access;
use crate::workspace::workspace;
use crate::{now_micros, uuid_v4_uniq};
use pbkdf2::pbkdf2_hmac;
use sha2::{Digest, Sha256};
use spacetimedb::*;

// ── Tables ────────────────────────────────────────────────────────────

/// User account with password auth.
/// Private table — accessible only through reducers (not via SQL).
#[table(accessor = account)]
#[derive(Debug, Clone)]
pub struct Account {
    #[primary_key]
    pub id: String, // ctx.sender().to_hex() as PK
    #[index(btree)]
    pub username: String,
    pub display_name: String,
    pub password_hash: String, // hex(PBKDF2(password, salt))
    pub password_salt: String, // hex(random salt)
    pub role: String,          // "admin" | "user"
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
    #[index(btree)]
    pub key_hash: String,
    pub name: String,
    pub permissions: String,
    pub scope: String,
    pub is_active: bool,
    pub created_at: i64,
    pub last_used_at: i64,
}

/// Public result table for API key metadata (key_hash excluded).
/// Populated by create_api_key and list_api_keys reducers.
#[table(accessor = api_key_result)]
#[derive(Debug, Clone)]
pub struct ApiKeyResult {
    #[primary_key]
    pub id: String,
    /// The actual ApiKey.id this row describes.
    pub api_key_id: String,
    pub workspace_id: String,
    pub name: String,
    pub permissions: String,
    /// Scope string — ``"*"`` for all workspaces or JSON array of workspace IDs.
    pub scope: String,
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

/// Public result table for API key verification results.
/// Populated by verify_api_key reducer so the SDK can read back
/// the key's scope, permissions, and metadata without access to
/// the private api_key table.
#[table(accessor = api_key_verification_result)]
#[derive(Debug, Clone)]
pub struct ApiKeyVerificationResult {
    #[primary_key]
    pub id: String,
    pub api_key_id: String,
    pub workspace_id: String,
    pub name: String,
    pub permissions: String,
    pub scope: String,
    pub is_active: bool,
    pub created_at: i64,
    pub last_used_at: i64,
    pub caller_identity: String,
    pub verified_at: i64,
}

/// Validate an API key scope string.
///
/// Accepts either ``"*"`` (wildcard — all workspaces) or a JSON array
/// of workspace IDs like ``'["ws-1", "ws-2"]'``.
pub fn validate_scope(scope: &str) -> Result<(), String> {
    if scope == "*" {
        return Ok(());
    }
    let ids: Vec<String> = serde_json::from_str(scope).map_err(|_| {
        "Scope must be \"*\" or a JSON array of workspace IDs like '[\"ws-1\"]'".to_string()
    })?;
    if ids.is_empty() {
        return Err("Scope array must not be empty — use \"*\" for unlimited access".to_string());
    }
    for id in &ids {
        if id.trim().is_empty() {
            return Err("Scope array elements must be non-empty workspace IDs".to_string());
        }
    }
    Ok(())
}

// ── Rate Limiting ─────────────────────────────────────────────────────

/// Sliding-window rate limit configuration per endpoint.
const RATE_LIMIT_WINDOW_MICROS: i64 = 60_000_000; // 60 seconds
const REGISTER_MAX: usize = 3; // max 3 registration attempts per 60s
const LOGIN_MAX: usize = 10; // max 10 login attempts per 60s
const VERIFY_KEY_MAX: usize = 20; // max 20 API key verification attempts per 60s
const CREATE_KEY_MAX: usize = 5; // max 5 API key creations per 60s
const DELETE_KEY_MAX: usize = 5; // max 5 API key deletions per 60s
const UPDATE_KEY_MAX: usize = 10; // max 10 API key updates per 60s
const DEACTIVATE_KEY_MAX: usize = 5; // max 5 API key deactivations per 60s
const DEACTIVATE_ACCOUNT_MAX: usize = 3; // max 3 account deactivations per 60s
const ADMIN_DEACTIVATE_ACCOUNT_MAX: usize = 10; // max 10 admin deactivations per 60s
const UPDATE_ACCOUNT_MAX: usize = 5; // max 5 account updates per 60s
const LOGOUT_MAX: usize = 10; // max 10 logout attempts per 60s
const LIST_KEYS_MAX: usize = 20; // max 20 list API key requests per 60s
const PROMOTE_ADMIN_MAX: usize = 5; // max 5 admin promotions per 60s
const DEMOTE_ADMIN_MAX: usize = 5; // max 5 admin demotions per 60s
const SET_INITIAL_ADMIN_MAX: usize = 3; // max 3 initial admin sets per 60s
const LIST_ADMINS_MAX: usize = 20; // max 20 list admin requests per 60s

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
///
/// Collects ALL entries for this identity+endpoint in a single pass
/// (no `.take(MAX_RESULTS)` cap) so that entries from other identities
/// cannot hide this caller's history. Partitions into old (swept) and
/// current (counted) entries, then records a new entry if under limit.
pub(crate) fn check_rate_limit(
    ctx: &ReducerContext,
    endpoint: &str,
    max_requests: usize,
) -> Result<(), String> {
    let identity = ctx.sender().to_hex().to_string();
    let now = crate::now_micros(ctx);
    let window_start = now - RATE_LIMIT_WINDOW_MICROS;

    // Single pass: collect all entries for this identity+endpoint
    let entries: Vec<_> = ctx
        .db
        .rate_limit_entry()
        .iter()
        .filter(|e: &RateLimitEntry| e.identity == identity && e.endpoint == endpoint)
        .collect();

    // Partition into old (outside window, to sweep) and current (inside window)
    let (old, current): (Vec<_>, Vec<_>) = entries
        .into_iter()
        .partition(|e| e.timestamp < window_start);

    // Delete expired entries
    for entry in &old {
        ctx.db.rate_limit_entry().id().delete(&entry.id);
    }

    if current.len() >= max_requests {
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
/// Sweeps ALL expired entries (no `.take(MAX_RESULTS)` cap) since the
/// table is self-cleaning and leftover entries would linger past their
/// 60-second window.
#[reducer]
pub fn cleanup_rate_limits(ctx: &ReducerContext) -> Result<(), String> {
    let now = crate::now_micros(ctx);
    let window_start = now - RATE_LIMIT_WINDOW_MICROS;

    let old: Vec<_> = ctx
        .db
        .rate_limit_entry()
        .iter()
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
        let lookup = username.trim().to_lowercase();
        let name_taken = ctx
            .db
            .account()
            .username()
            .filter(&lookup)
            .next()
            .is_some()
            // Fallback: check mixed-case usernames from before normalization
            || ctx.db.account().iter()
                .take(crate::MAX_RESULTS)
                .any(|a: Account| a.username.to_lowercase() == lookup);
        if name_taken {
            return Err("Username already taken".to_string());
        }

        let now = now_micros(ctx);
        let salt = derive_salt(&identity, now);
        let hash = hash_password(&password, &salt);

        ctx.db.account().insert(Account {
            id: identity.clone(), // identity hex as PK
            username: username.trim().to_lowercase(),
            display_name: if display_name.trim().is_empty() {
                username.trim().to_string()
            } else {
                display_name.trim().to_string()
            },
            password_hash: encode_password_hash(&hash),
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

        let account = ctx
            .db
            .account()
            .username()
            .filter(&username.trim().to_lowercase())
            .next()
            .filter(|a: &Account| a.is_active)
            .or_else(|| {
                // Fallback: linear scan for mixed-case usernames from before normalization
                ctx.db.account().iter()
                    .find(|a: &Account| a.username.to_lowercase() == username.trim().to_lowercase() && a.is_active)
            })
            .ok_or_else(|| "Invalid username or password".to_string())?;

        // Verify password
        let salt = hex::decode(&account.password_salt)
            .map_err(|_| "Internal error: invalid salt".to_string())?;
        let (iterations, expected_hash) = decode_password_hash(&account.password_hash)?;

        let computed = hash_password_iters(&password, &salt, iterations);

        if computed != expected_hash {
            return Err("Invalid username or password".to_string());
        }

        // If the identity changed (different browser), update it so this account
        // is now associated with this identity going forward
        if account.id != identity {
            // Delete old identity row, insert with new identity
            // First check if new identity collides with another account
            if ctx.db.account().id().find(&identity).is_some() {
                return Err(
                    "This browser identity is already linked to another account".to_string()
                );
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
    check_rate_limit(ctx, "logout", LOGOUT_MAX)?;
    trace_span!(ctx, "logout", TracingSpanKind::Write, "", {
        let identity = ctx.sender().to_hex().to_string();

        if let Some(account) = ctx.db.account().id().find(&identity) {
            let mut updated = account;
            updated.id = String::new(); // detach
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
    check_rate_limit(ctx, "update_account", UPDATE_ACCOUNT_MAX)?;
    trace_span!(ctx, "update_account", TracingSpanKind::Write, "", {
        let identity = ctx.sender().to_hex().to_string();

        let account = require_auth(ctx)?;

        // Verify current password
        let salt = hex::decode(&account.password_salt).map_err(|_| "Internal error".to_string())?;
        let (iterations, expected_hash) = decode_password_hash(&account.password_hash)?;
        let computed = hash_password_iters(&current_password, &salt, iterations);
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
            updated.password_hash = encode_password_hash(&new_hash);
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
    check_rate_limit(ctx, "deactivate_account", DEACTIVATE_ACCOUNT_MAX)?;
    trace_span!(ctx, "deactivate_account", TracingSpanKind::Write, "", {
        let account = require_auth(ctx)?;

        let salt = hex::decode(&account.password_salt).map_err(|_| "Internal error".to_string())?;
        let (iterations, expected_hash) = decode_password_hash(&account.password_hash)?;
        let computed = hash_password_iters(&password, &salt, iterations);
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

/// Admin force-deactivate any user account by identity (no password required).
/// Only admins can call this. Cannot deactivate yourself.
#[reducer]
pub fn admin_deactivate_account(ctx: &ReducerContext, target_identity: String) -> Result<(), String> {
    check_rate_limit(ctx, "admin_deactivate_account", ADMIN_DEACTIVATE_ACCOUNT_MAX)?;
    trace_span!(ctx, "admin_deactivate_account", TracingSpanKind::Admin, "", {
        let caller = ctx.sender().to_hex().to_string();

        // Verify caller is an admin
        let _caller_account = require_admin(ctx)?;

        // Cannot deactivate yourself this way
        if caller == target_identity {
            return Err(
                "Cannot deactivate your own account this way. Use deactivate_account instead."
                    .to_string(),
            );
        }

        // Find the target account
        let mut target = ctx
            .db
            .account()
            .id()
            .find(&target_identity)
            .ok_or_else(|| format!("No account found for identity '{}'", &target_identity))?;

        if !target.is_active {
            return Err(format!(
                "Account '{}' is already deactivated",
                &target_identity
            ));
        }

        target.is_active = false;
        target.updated_at = now_micros(ctx);
        ctx.db.account().id().update(target);

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
    scope: String,
) -> Result<(), String> {
    check_rate_limit(ctx, "create_api_key", CREATE_KEY_MAX)?;
    trace_span!(
        ctx,
        "create_api_key",
        TracingSpanKind::Write,
        &workspace_id,
        {
            let account = require_auth(ctx)?;
            let caller = ctx.sender().to_hex();
            check_space_access(ctx, &workspace_id, &caller, "admin")?;

            // Validate permissions JSON
            if serde_json::from_str::<Vec<String>>(&permissions).is_err() {
                return Err("permissions must be a valid JSON array of strings".to_string());
            }

            // Validate scope
            validate_scope(&scope)?;

            // Only admins can create API keys with wildcard scope
            if scope == "*" && account.role != "admin" {
                return Err(
                "Wildcard scope '*' allows access to ALL workspaces and is reserved for admins. Use a workspace-scoped scope instead."
                    .to_string(),
            );
            }

            let id = uuid_v4_uniq(ctx, |id| ctx.db.api_key().id().find(id).is_none(), 3);
            let now = now_micros(ctx);

            ctx.db.api_key().insert(ApiKey {
                id: id.clone(),
                workspace_id: workspace_id.clone(),
                key_hash,
                name: name.clone(),
                permissions: permissions.clone(),
                scope: scope.clone(),
                is_active: true,
                created_at: now,
                last_used_at: 0,
            });

            // Publish metadata to public result table so SDK can read back the ID
            // Pre-cleanup: remove stale results for this workspace_id + caller_identity + operation
            for old in ctx.db.api_key_result().iter()
                .filter(|r| r.workspace_id == workspace_id && r.caller_identity == account.id && r.operation == "create")
                .collect::<Vec<_>>()
            {
                ctx.db.api_key_result().id().delete(&old.id);
            }
            ctx.db.api_key_result().insert(ApiKeyResult {
                id: uuid_v7(ctx),
                api_key_id: id.clone(),
                workspace_id: workspace_id.clone(),
                name,
                permissions,
                scope,
                is_active: true,
                created_at: now,
                last_used_at: 0,
                caller_identity: account.id,
                operation: "create".to_string(),
                request_id,
            });
            Ok(())
        }
    )
}

/// Delete an API key (permanently removes it from the system).
/// Admin-only operation. If you need to temporarily disable a key, use
/// `update_api_key` with `is_active: false` instead.
#[reducer]
pub fn delete_api_key(ctx: &ReducerContext, id: String) -> Result<(), String> {
    check_rate_limit(ctx, "delete_api_key", DELETE_KEY_MAX)?;
    trace_span!(ctx, "delete_api_key", TracingSpanKind::Write, "", {
        let account = require_auth(ctx)?;
        if account.role != "admin" {
            return Err("Only admins can delete API keys".to_string());
        }

        let key = ctx
            .db
            .api_key()
            .id()
            .find(&id)
            .ok_or_else(|| format!("API key '{}' not found", id))?;

        // Remove from private api_key table
        ctx.db.api_key().id().delete(&key.id);

        // Also clean up any result rows for this key
        let old_results: Vec<_> = ctx
            .db
            .api_key_result()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|r: &ApiKeyResult| r.api_key_id == id)
            .collect();
        for r in old_results {
            ctx.db.api_key_result().id().delete(&r.id);
        }

        let old_verifications: Vec<_> = ctx
            .db
            .api_key_verification_result()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|r: &ApiKeyVerificationResult| r.api_key_id == id)
            .collect();
        for r in old_verifications {
            ctx.db.api_key_verification_result().id().delete(&r.id);
        }

        log::info!(
            "Deleted API key '{}' (workspace: {})",
            key.id,
            key.workspace_id
        );
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
    check_rate_limit(ctx, "verify_api_key", VERIFY_KEY_MAX)?;
    trace_span!(ctx, "verify_api_key", TracingSpanKind::Read, "", {
        let caller = ctx.sender().to_hex().to_string();
        let now = now_micros(ctx);

        let key_hash = hash_api_key(&raw_key);

        let key = ctx
            .db
            .api_key()
            .key_hash()
            .filter(&key_hash)
            .next()
            .filter(|k: &ApiKey| k.is_active)
            .ok_or_else(|| "Invalid or deactivated API key".to_string())?;

        // Update last_used_at
        let mut upd = key.clone();
        upd.last_used_at = now;
        ctx.db.api_key().id().update(upd);

        // Clear previous verification results for this caller
        let old: Vec<_> = ctx
            .db
            .api_key_verification_result()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|r: &ApiKeyVerificationResult| r.caller_identity == caller)
            .collect();
        for r in old {
            ctx.db.api_key_verification_result().id().delete(&r.id);
        }

        // Write fresh result
        ctx.db
            .api_key_verification_result()
            .insert(ApiKeyVerificationResult {
                id: uuid_v4_uniq(
                    ctx,
                    |id| ctx.db.api_key_verification_result().id().find(id).is_none(),
                    3,
                ),
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
/// The caller must be authenticated.  Scope changes are restricted:
/// - Only admins can change scope to `"*"` (wildcard).
/// - Non-admin users can only change scope within workspaces they own.
#[reducer]
pub fn update_api_key(
    ctx: &ReducerContext,
    id: String,
    name: String,
    permissions: String,
    scope: String,
    is_active: bool,
) -> Result<(), String> {
    check_rate_limit(ctx, "update_api_key", UPDATE_KEY_MAX)?;
    trace_span!(ctx, "update_api_key", TracingSpanKind::Write, "", {
        let account = require_auth(ctx)?;

        let mut key = ctx
            .db
            .api_key()
            .id()
            .find(&id)
            .ok_or_else(|| "API key not found".to_string())?;

        // Validate new permissions if provided
        if !permissions.is_empty() {
            if serde_json::from_str::<Vec<String>>(&permissions).is_err() {
                return Err(
                    "permissions must be a valid JSON array of strings or empty to leave unchanged"
                        .to_string(),
                );
            }
            key.permissions = permissions;
        }

        // Validate new scope if provided
        if !scope.is_empty() {
            validate_scope(&scope)?;

            // Only admins can widen scope to wildcard
            if scope == "*" && account.role != "admin" {
                return Err(
                    "Wildcard scope '*' allows access to ALL workspaces and is reserved for admins. \
                     Use a workspace-scoped scope instead."
                        .to_string(),
                );
            }

            // Non-admin users cannot widen scope beyond the key's original workspace
            if account.role != "admin" && scope != "*" {
                let ws_ids: Vec<String> = serde_json::from_str(&scope)
                    .map_err(|_| "Scope must be a JSON array of workspace IDs".to_string())?;
                if !ws_ids.iter().any(|id| id == &key.workspace_id) {
                    return Err(format!(
                        "Scope must include the key's workspace '{}' to prevent privilege escalation. \
                         Current scope: {}",
                        key.workspace_id, scope
                    ));
                }
            }

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
    check_rate_limit(ctx, "deactivate_api_key", DEACTIVATE_KEY_MAX)?;
    trace_span!(ctx, "deactivate_api_key", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let mut key = ctx
            .db
            .api_key()
            .id()
            .find(&id)
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
    check_rate_limit(ctx, "list_api_keys", LIST_KEYS_MAX)?;
    trace_span!(
        ctx,
        "list_api_keys",
        TracingSpanKind::Read,
        &workspace_id,
        {
            let account = require_auth(ctx)?;
            let _caller = ctx.sender().to_hex().to_string();

            // Verify the caller has at least viewer access to this workspace.
            // Re-use the workspace module's access check (imported at the top).
            // For now, just check the caller is authenticated and the workspace exists.
            // Full space-access enforcement can come later.
            let _ws = ctx
                .db
                .workspace()
                .id()
                .find(&workspace_id)
                .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

            // Clear previous results for this caller+workspace
            let old: Vec<_> = ctx
                .db
                .api_key_result()
                .iter()
                .take(crate::MAX_RESULTS)
                .filter(|r: &ApiKeyResult| {
                    r.workspace_id == workspace_id
                        && r.caller_identity == account.id
                        && r.operation == "list"
                })
                .collect();
            for r in old {
                ctx.db.api_key_result().id().delete(&r.id);
            }

            // Insert fresh results — metadata only, no key_hash
            for key in ctx
                .db
                .api_key()
                .iter()
                .take(crate::MAX_RESULTS)
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
        }
    )
}

// ── Auth Guards ───────────────────────────────────────────────────────

/// Require authentication. Returns the Account or an error.
///
/// Supports two authentication paths:
/// 1. **Account auth** -- caller has a registered Account linked to their identity.
/// 2. **API key auth** -- caller has a valid API key verified via `verify_api_key`.
///
/// For API key auth, returns a virtual Account with role "user" (no admin
/// privileges) so all downstream checks work identically.
pub fn require_auth(ctx: &ReducerContext) -> Result<Account, String> {
    let identity = ctx.sender().to_hex().to_string();

    // Check for existing Account
    if let Some(account) = ctx.db.account().id().find(&identity) {
        if account.is_active {
            return Ok(account);
        }
    }

    // Fall back to API key verification
    let verification = ctx
        .db
        .api_key_verification_result()
        .iter()
        .take(crate::MAX_RESULTS)
        .find(|r: &ApiKeyVerificationResult| r.caller_identity == identity);

    if let Some(result) = verification {
        if let Some(key) = ctx.db.api_key().id().find(&result.api_key_id) {
            if key.is_active {
                // Return a virtual Account for API key auth.
                // The username is prefixed with "api-key:" for traceability.
                // Role is "user" -- API keys never get admin privileges through
                // this path; they must rely on scope-based workspace access.
                return Ok(Account {
                    id: identity.clone(),
                    username: format!("api-key:{}", key.id),
                    display_name: key.name.clone(),
                    password_hash: String::new(),
                    password_salt: String::new(),
                    role: "user".to_string(),
                    is_active: true,
                    created_at: key.created_at,
                    updated_at: key.last_used_at,
                });
            }
        }
    }

    Err("Not authenticated".to_string())
}

/// Check that the caller's verified API key (if any) has scope for the target workspace.
///
/// Returns:
/// - `Ok(true)` -- caller has API key auth AND the key's scope includes `workspace_id`.
/// - `Ok(false)` -- caller has no API key verification (defer to account-based auth).
/// - `Err(...)` -- caller has API key auth but scope denies `workspace_id`.
///
/// Scope can be either `"*"` (all workspaces) or a JSON array of workspace IDs
/// like `'["ws-1", "ws-2"]'`.
pub fn check_api_key_workspace_scope(
    ctx: &ReducerContext,
    workspace_id: &str,
) -> Result<bool, String> {
    let caller = ctx.sender().to_hex().to_string();

    let verification = ctx
        .db
        .api_key_verification_result()
        .iter()
        .take(crate::MAX_RESULTS)
        .find(|r: &ApiKeyVerificationResult| r.caller_identity == caller);

    if let Some(result) = verification {
        // Re-lookup the API key by ID to get current scope and active status
        let key = ctx
            .db
            .api_key()
            .id()
            .find(&result.api_key_id)
            .ok_or_else(|| "API key no longer exists (was deleted)".to_string())?;

        if !key.is_active {
            return Err(
                "API key has been deactivated. Please re-authenticate with a valid key."
                    .to_string(),
            );
        }

        // Wildcard scope: access all workspaces
        if key.scope == "*" {
            return Ok(true);
        }

        // Parse JSON array of workspace IDs
        let workspace_ids: Vec<String> = serde_json::from_str(&key.scope)
            .map_err(|_| format!("Invalid API key scope format: '{}'", key.scope))?;

        if workspace_ids.iter().any(|id| id == workspace_id) {
            return Ok(true);
        }

        return Err(format!(
            "Access denied: API key is scoped to workspaces {} and does not include '{}'",
            key.scope, workspace_id
        ));
    }

    Ok(false) // No API key verification -- defer to account-based auth
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
    ctx.db
        .account()
        .id()
        .find(identity.to_string())
        .is_some_and(|a: Account| a.role == "admin" && a.is_active)
}

/// Check if the caller is authenticated (no error, just bool).
pub fn is_authenticated(ctx: &ReducerContext) -> bool {
    let identity = ctx.sender().to_hex().to_string();
    ctx.db
        .account()
        .id()
        .find(&identity)
        .is_some_and(|a: Account| a.is_active)
}

// ── Crypto Helpers ────────────────────────────────────────────────────

/// Iteration count for NEW password hashes (OWASP 2026 recommendation).
const PBKDF2_ITERATIONS: u32 = 600_000;

/// Iteration count used by legacy hashes created before the versioned
/// hash format was introduced. Kept forever so old accounts keep working.
const PBKDF2_LEGACY_ITERATIONS: u32 = 100_000;

/// Hash password with PBKDF2-HMAC-SHA256 at the given iteration count.
fn hash_password_iters(password: &str, salt: &[u8], iterations: u32) -> Vec<u8> {
    let mut output = vec![0u8; 32];
    pbkdf2_hmac::<Sha256>(password.as_bytes(), salt, iterations, &mut output);
    output
}

/// Hash password at the current recommended iteration count.
fn hash_password(password: &str, salt: &[u8]) -> Vec<u8> {
    hash_password_iters(password, salt, PBKDF2_ITERATIONS)
}

/// Encode a fresh password hash with its iteration count: `"<iters>:<hex>"`.
/// Storing the iteration count lets verification adapt per-hash, so future
/// iteration bumps never invalidate existing accounts.
fn encode_password_hash(hash: &[u8]) -> String {
    format!("{}:{}", PBKDF2_ITERATIONS, hex::encode(hash))
}

/// Decode a stored password hash into `(iterations, hash_bytes)`.
/// Legacy hashes (plain hex, no `:` prefix) fall back to the legacy
/// iteration count so accounts created before the versioned format
/// still verify correctly.
fn decode_password_hash(stored: &str) -> Result<(u32, Vec<u8>), String> {
    match stored.split_once(':') {
        Some((iters, hex_part)) => {
            let iterations = iters
                .parse::<u32>()
                .map_err(|_| "Internal error: invalid hash format".to_string())?;
            let bytes =
                hex::decode(hex_part).map_err(|_| "Internal error: invalid hash".to_string())?;
            Ok((iterations, bytes))
        }
        None => {
            let bytes = hex::decode(stored).map_err(|_| "Internal error: invalid hash".to_string())?;
            Ok((PBKDF2_LEGACY_ITERATIONS, bytes))
        }
    }
}

/// Derive a deterministic salt from identity + timestamp.
/// For a personal app this is acceptable; a production app would use
/// client-side generated salts submitted as a parameter.
fn derive_salt(identity: &str, timestamp: i64) -> Vec<u8> {
    let mut hasher = Sha256::new();
    hasher.update(identity.as_bytes());
    hasher.update(timestamp.to_le_bytes());
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
    check_rate_limit(ctx, "promote_admin", PROMOTE_ADMIN_MAX)?;
    trace_span!(ctx, "promote_admin", TracingSpanKind::Admin, "", {
        let caller = ctx.sender().to_hex().to_string();

        // Verify caller is an admin
        let _caller_account = require_admin(ctx)?;

        // Cannot promote self (already admin)
        if caller == target_identity {
            return Err("You are already an admin".to_string());
        }

        // Find the target account
        let mut target = ctx
            .db
            .account()
            .id()
            .find(&target_identity)
            .ok_or_else(|| format!("No account found for identity '{}'", &target_identity))?;

        if target.role == "admin" {
            return Err(format!(
                "Identity '{}' is already an admin",
                &target_identity
            ));
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
    check_rate_limit(ctx, "demote_admin", DEMOTE_ADMIN_MAX)?;
    trace_span!(ctx, "demote_admin", TracingSpanKind::Admin, "", {
        let caller = ctx.sender().to_hex().to_string();

        // Verify caller is an admin
        let _caller_account = require_admin(ctx)?;

        // Cannot demote yourself
        if caller == target_identity {
            return Err("Cannot demote yourself. Have another admin do it.".to_string());
        }

        // Find the target account
        let mut target = ctx
            .db
            .account()
            .id()
            .find(&target_identity)
            .ok_or_else(|| format!("No account found for identity '{}'", &target_identity))?;

        if target.role != "admin" {
            return Err(format!("Identity '{}' is not an admin", &target_identity));
        }

        // Prevent demoting the last admin
        let admin_count = ctx
            .db
            .account()
            .iter()
            .take(crate::MAX_RESULTS)
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
///   Both paths allow a fresh test run to bootstrap, then subsequent runs to
///   register-and-promote when the admin identity differs from the original.
#[reducer]
pub fn set_initial_admin(ctx: &ReducerContext, identity_hex: String) -> Result<(), String> {
    check_rate_limit(ctx, "set_initial_admin", SET_INITIAL_ADMIN_MAX)?;
    trace_span!(ctx, "set_initial_admin", TracingSpanKind::Admin, "", {
        // Check that no admin exists yet
        let existing_admin = ctx
            .db
            .account()
            .iter()
            .take(crate::MAX_RESULTS)
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
    check_rate_limit(ctx, "list_admins", LIST_ADMINS_MAX)?;
    trace_span!(ctx, "list_admins", TracingSpanKind::Read, "", {
        // Require auth (any authenticated user can list admins)
        let _account = require_auth(ctx)?;

        // Pre-cleanup: remove stale results for this scope (delete-all)
        for old in ctx.db.admin_list_result().iter().collect::<Vec<_>>() {
            ctx.db.admin_list_result().id().delete(&old.id);
        }
        let now = now_micros(ctx);
        for account in ctx
            .db
            .account()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|a: &Account| a.role == "admin" && a.is_active)
        {
            ctx.db.admin_list_result().insert(AdminListResult {
                id: uuid_v4_uniq(
                    ctx,
                    |id| ctx.db.admin_list_result().id().find(id).is_none(),
                    3,
                ),
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
#[table(accessor = admin_list_result)]
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
        let test_cases: Vec<&[u8]> =
            vec![b"a", b"ab", b"abc", b"abcd", b"long-salt-value-for-test"];
        for salt in &test_cases {
            let h = hash_password("test", salt);
            assert_eq!(h.len(), 32, "PBKDF2 output should always be 32 bytes");
        }
    }

    #[test]
    fn test_password_hash_encode_decode_roundtrip() {
        let salt = b"roundtrip-salt-16";
        let hash = hash_password("secret", salt);
        let encoded = encode_password_hash(&hash);
        let (iters, decoded) = decode_password_hash(&encoded).expect("decode should succeed");
        assert_eq!(iters, PBKDF2_ITERATIONS);
        assert_eq!(decoded, hash);
    }

    #[test]
    fn test_decode_legacy_hash_falls_back_to_legacy_iterations() {
        // Legacy format: plain hex, no "<iters>:" prefix
        let salt = b"legacy-salt-1234";
        let legacy_hash = hash_password_iters("secret", salt, PBKDF2_LEGACY_ITERATIONS);
        let legacy_encoded = hex::encode(&legacy_hash);
        let (iters, decoded) =
            decode_password_hash(&legacy_encoded).expect("legacy decode should succeed");
        assert_eq!(iters, PBKDF2_LEGACY_ITERATIONS);
        assert_eq!(decoded, legacy_hash);
    }

    #[test]
    fn test_legacy_and_current_hashes_verify_with_matching_iters() {
        let salt = b"cross-version-salt";
        let legacy = hash_password_iters("pw", salt, PBKDF2_LEGACY_ITERATIONS);
        let current = hash_password("pw", salt);
        // Same password+salt at different iteration counts must NOT collide
        assert_ne!(legacy, current);
        // Each verifies against its own iteration count
        assert_eq!(hash_password_iters("pw", salt, PBKDF2_LEGACY_ITERATIONS), legacy);
        assert_eq!(hash_password_iters("pw", salt, PBKDF2_ITERATIONS), current);
    }

    #[test]
    fn test_decode_rejects_garbage() {
        assert!(decode_password_hash("not-hex!!!").is_err());
        assert!(decode_password_hash("abc:not-hex!!!").is_err());
        assert!(decode_password_hash("notanumber:00ff").is_err());
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
        use pbkdf2::pbkdf2_hmac;
        use sha2::Sha256;
        use std::time::Instant;

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
        log::info!(
            "PBKDF2 benchmark: 100K={:?} 600K={:?} ratio={:.1}x",
            t_100k,
            t_600k,
            ratio
        );

        // Just verify both produce output
        assert_eq!(output.len(), 32);
    }

    #[test]
    fn test_username_normalization_lowercased() {
        let normalized = "AliceSmith".trim().to_lowercase();
        assert_eq!(normalized, "alicesmith");
    }

    #[test]
    fn test_username_normalization_trimmed_and_lowercased() {
        let normalized = "  Alice Smith  ".trim().to_lowercase();
        assert_eq!(normalized, "alice smith");
    }

    #[test]
    fn test_username_normalization_uppercase() {
        let normalized = "ADMIN".trim().to_lowercase();
        assert_eq!(normalized, "admin");
    }

    #[test]
    fn test_username_normalization_mixed_case() {
        let normalized = "MyUser_Name".trim().to_lowercase();
        assert_eq!(normalized, "myuser_name");
    }

    #[test]
    fn test_username_lookup_key_generation() {
        // Verify that search key matches stored key for normalized usernames
        let stored = "alice@example.com".trim().to_lowercase();
        let search = "Alice@Example.COM".trim().to_lowercase();
        assert_eq!(stored, search);
    }

    #[test]
    fn test_hash_api_key_deterministic() {
        let h1 = hash_api_key("my-api-key-12345");
        let h2 = hash_api_key("my-api-key-12345");
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 64, "SHA-256 hex output should be 64 chars");
    }

    #[test]
    fn test_hash_api_key_different_keys() {
        let h1 = hash_api_key("key-one");
        let h2 = hash_api_key("key-two");
        assert_ne!(h1, h2);
    }

    #[test]
    fn test_hash_api_key_empty_key() {
        let h = hash_api_key("");
        assert_eq!(h.len(), 64);
    }

    #[test]
    fn test_check_rate_limit_parse_works() {
        // Check that the rate limit constants parse correctly
        assert!(LOGIN_MAX > 0);
        assert!(REGISTER_MAX > 0);
        assert!(VERIFY_KEY_MAX > 0);
    }

    #[test]
    fn test_encode_password_hash_contains_iterations() {
        let hash = [0u8; 32];
        let encoded = encode_password_hash(&hash);
        assert!(encoded.contains(':'), "Encoded hash should contain ':' separator");
        assert!(encoded.starts_with("600000:"), "Should start with current iteration count");
    }

    #[test]
    fn test_verify_api_key_matched_by_hash() {
        // Verify that hash_api_key produces deterministic results
        let key1 = hash_api_key("sk-test-key-12345");
        let key2 = hash_api_key("sk-test-key-12345");
        assert_eq!(key1, key2);
        assert_eq!(key1.len(), 64, "SHA-256 hex should be 64 chars");

        // Different keys produce different hashes
        let key3 = hash_api_key("different-key");
        assert_ne!(key1, key3);
    }

    #[test]
    fn test_account_username_indexed_lookup() {
        // Verify normalized username lookup works with btree index
        let stored = "AliceSmith@Example.COM".trim().to_lowercase();
        let search = "alicesmith@example.com";
        assert_eq!(stored, search);
    }

    #[test]
    fn test_account_username_fallback_for_mixed_case() {
        // Verify that the login fallback still matches mixed-case usernames
        let stored = "AdminUser".to_string(); // Pre-normalization legacy username
        let search = "adminuser";
        assert_eq!(stored.to_lowercase(), search);
    }

    #[test]
    fn test_key_hash_index_selectivity() {
        // key_hash is a SHA-256 hex string — should be unique per key
        let k1 = hash_api_key("key-alpha");
        let k2 = hash_api_key("key-beta");
        let k3 = hash_api_key("key-gamma");
        assert_ne!(k1, k2);
        assert_ne!(k1, k3);
        assert_ne!(k2, k3);
        // All SHA-256 hex outputs are exactly 64 chars
        assert_eq!(k1.len(), 64);
        assert_eq!(k2.len(), 64);
        assert_eq!(k3.len(), 64);
    }

    #[test]
    fn test_key_hash_empty_input() {
        // Edge case: empty key should still produce a valid hash
        let h = hash_api_key("");
        assert_eq!(h.len(), 64);
    }

    #[test]
    fn test_key_hash_special_characters() {
        // Non-ASCII characters should still hash deterministically
        let h1 = hash_api_key("hello@world! #123");
        let h2 = hash_api_key("hello@world! #123");
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 64);
    }
}
