use spacetimedb::*;
use crate::auth::require_admin;
use crate::{now_micros, uuid_v4_uniq, MAX_RESULTS};

// ── Tables ────────────────────────────────────────────────────────────

/// A registered JWT signing key.
///
/// During key rotation, multiple keys may be active simultaneously:
/// - The NEW key signs all new tokens.
/// - The OLD key is kept in the `rotation` set so existing tokens remain
///   valid until they expire or the window closes.
///
/// Once a key's `retired_at` has passed, it can be safely deleted.
#[table(accessor = jwt_signing_key)]
#[derive(Debug, Clone)]
pub struct JwtSigningKey {
    #[primary_key]
    pub id: String,
    /// Monotonically increasing version number. Higher = newer.
    pub key_version: u32,
    /// Human-readable label (e.g., "ecdsa-p256-2026-07").
    pub name: String,
    /// SHA-256 fingerprint of the public key — used as JWT `kid` header.
    pub key_id: String,
    /// Public key PEM text (used by the SpacetimeDB node to verify tokens).
    /// Stored so the module has an authoritative record of all trusted keys.
    pub public_key_pem: String,
    /// Absolute path to the private key on the server filesystem.
    /// The SpacetimeDB node reads this via jwt-priv-key-path in config.toml.
    pub private_key_path: String,
    /// Whether this key is currently active for signing NEW tokens.
    /// Only one key should be `is_current` at a time.
    pub is_current: bool,
    /// Whether this key is still trusted for VERIFICATION.
    /// A retired key will still verify tokens issued before retirement.
    pub is_trusted: bool,
    /// Micros timestamp when this key was created.
    pub created_at: i64,
    /// Micros timestamp when this key was rotated out (0 = still current).
    pub retired_at: i64,
    /// Optional micros expiry — the key will not be trusted after this point.
    pub expires_at: i64,
}

/// Public result table for listing signing keys (no private key paths exposed).
#[table(accessor = jwt_signing_key_result, public)]
#[derive(Debug, Clone)]
pub struct JwtSigningKeyResult {
    #[primary_key]
    pub id: String,
    pub key_version: u32,
    pub name: String,
    pub key_id: String,
    pub is_current: bool,
    pub is_trusted: bool,
    pub created_at: i64,
    pub retired_at: i64,
    pub expires_at: i64,
}

// ── Reducers ──────────────────────────────────────────────────────────

/// Register a new JWT signing key and make it the current signing key.
///
/// The previous current key is automatically retired (but remains trusted
/// for verification until its `expires_at` or until manually revoked).
///
/// Call this AFTER placing the new private key PEM on the server filesystem
/// and updating the SpacetimeDB node's config.toml to point to it.
///
/// # Arguments
/// * `name` - Human-readable label (e.g., "ecdsa-p256-2026-rotation-1").
/// * `key_id` - SHA-256 fingerprint hex of the public key (used as JWT `kid`).
/// * `public_key_pem` - The public key in PEM format.
/// * `private_key_path` - Absolute path to the private key on the server FS.
/// * `expires_in_days` - Optional: days until this key is fully expired (0 = never).
#[reducer]
pub fn register_signing_key(
    ctx: &ReducerContext,
    name: String,
    key_id: String,
    public_key_pem: String,
    private_key_path: String,
    expires_in_days: u32,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;

    if name.trim().is_empty() {
        return Err("Key name cannot be empty".to_string());
    }
    if key_id.trim().is_empty() {
        return Err("Key ID (fingerprint) cannot be empty".to_string());
    }
    if public_key_pem.trim().is_empty() {
        return Err("Public key PEM cannot be empty".to_string());
    }
    if private_key_path.trim().is_empty() {
        return Err("Private key path cannot be empty".to_string());
    }

    // Check for duplicate key_id
    let dup = ctx.db.jwt_signing_key().iter().take(MAX_RESULTS)
        .any(|k: &JwtSigningKey| k.key_id == key_id);
    if dup {
        return Err(format!("Key ID '{}' is already registered", key_id));
    }

    let now = now_micros(ctx);

    // Compute the next version number
    let max_version = ctx.db.jwt_signing_key().iter().take(MAX_RESULTS)
        .map(|k: &JwtSigningKey| k.key_version)
        .max()
        .unwrap_or(0);

    let expires_at = if expires_in_days > 0 {
        now + expires_in_days as i64 * 86_400_000_000
    } else {
        0i64
    };

    let id = uuid_v4_uniq(ctx, |id| ctx.db.jwt_signing_key().id().find(id).is_none(), 3);

    // Retire the previous current key (keep it trusted for verification)
    let current_keys: Vec<_> = ctx.db.jwt_signing_key().iter().take(MAX_RESULTS)
        .filter(|k: &JwtSigningKey| k.is_current)
        .collect();
    for mut old_key in current_keys {
        old_key.is_current = false;
        old_key.retired_at = now;
        ctx.db.jwt_signing_key().id().update(old_key);
    }

    // Insert the new key as current
    ctx.db.jwt_signing_key().insert(JwtSigningKey {
        id: id.clone(),
        key_version: max_version + 1,
        name,
        key_id,
        public_key_pem,
        private_key_path,
        is_current: true,
        is_trusted: true,
        created_at: now,
        retired_at: 0,
        expires_at,
    });

    // Publish to result table
    ctx.db.jwt_signing_key_result().insert(JwtSigningKeyResult {
        id: uuid_v4_uniq(ctx, |id| ctx.db.jwt_signing_key_result().id().find(id).is_none(), 3),
        key_version: max_version + 1,
        name: String::new(),
        key_id: String::new(),
        is_current: true,
        is_trusted: true,
        created_at: now,
        retired_at: 0,
        expires_at,
    });

    Ok(())
}

/// List all registered signing keys (metadata only — no private key paths).
/// Results are stored in the public jwt_signing_key_result table.
#[reducer]
pub fn list_signing_keys(ctx: &ReducerContext) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let query_id = format!("list_keys:{}", ctx.sender().to_hex());

    // Clear previous results
    let old: Vec<_> = ctx.db.jwt_signing_key_result().iter().take(MAX_RESULTS)
        .filter(|r: &JwtSigningKeyResult| r.id.starts_with(&query_id))
        .collect();
    for r in old {
        ctx.db.jwt_signing_key_result().id().delete(&r.id);
    }

    // Insert fresh results
    for key in ctx.db.jwt_signing_key().iter().take(MAX_RESULTS) {
        ctx.db.jwt_signing_key_result().insert(JwtSigningKeyResult {
            id: format!("{}:{}", query_id, key.id),
            key_version: key.key_version,
            name: key.name,
            key_id: key.key_id,
            is_current: key.is_current,
            is_trusted: key.is_trusted,
            created_at: key.created_at,
            retired_at: key.retired_at,
            expires_at: key.expires_at,
        });
    }

    Ok(())
}

/// Revoke a signing key immediately (stops trusting it for verification).
/// Cannot revoke the last current key.
#[reducer]
pub fn revoke_signing_key(ctx: &ReducerContext, key_id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;

    let mut key = ctx.db.jwt_signing_key().iter().take(MAX_RESULTS)
        .find(|k: &JwtSigningKey| k.key_id == key_id)
        .ok_or_else(|| format!("Signing key '{}' not found", key_id))?;

    if !key.is_trusted {
        return Err(format!("Signing key '{}' is already revoked", key_id));
    }

    // Prevent revoking the only current key
    if key.is_current {
        let other_current = ctx.db.jwt_signing_key().iter().take(MAX_RESULTS)
            .any(|k: &JwtSigningKey| k.is_current && k.key_id != key_id);
        if !other_current {
            return Err(
                "Cannot revoke the only current signing key. Register a new key first."
                    .to_string(),
            );
        }
    }

    let now = now_micros(ctx);
    key.is_current = false;
    key.is_trusted = false;
    key.retired_at = now;
    ctx.db.jwt_signing_key().id().update(key);

    Ok(())
}

/// Get the current (active) signing key info.
/// Returns metadata via the jwt_signing_key_result table.
#[reducer]
pub fn get_current_signing_key(ctx: &ReducerContext) -> Result<(), String> {
    let _admin = require_admin(ctx)?;

    let current = ctx.db.jwt_signing_key().iter().take(MAX_RESULTS)
        .find(|k: &JwtSigningKey| k.is_current && k.is_trusted)
        .ok_or_else(|| "No current signing key found".to_string())?;

    let query_id = format!("current_key:{}", ctx.sender().to_hex());

    // Clear previous
    let old: Vec<_> = ctx.db.jwt_signing_key_result().iter().take(MAX_RESULTS)
        .filter(|r: &JwtSigningKeyResult| r.id.starts_with(&query_id))
        .collect();
    for r in old {
        ctx.db.jwt_signing_key_result().id().delete(&r.id);
    }

    ctx.db.jwt_signing_key_result().insert(JwtSigningKeyResult {
        id: format!("{}:{}", query_id, current.id),
        key_version: current.key_version,
        name: current.name.clone(),
        key_id: current.key_id.clone(),
        is_current: true,
        is_trusted: true,
        created_at: current.created_at,
        retired_at: 0,
        expires_at: current.expires_at,
    });

    Ok(())
}

/// Clean up expired signing keys (those past their expires_at).
/// Only removes keys that are no longer current and are past expiry.
/// Returns the count of removed keys via a public key_rotation_event table entry.
#[reducer]
pub fn purge_expired_signing_keys(ctx: &ReducerContext) -> Result<(), String> {
    let _admin = require_admin(ctx)?;

    let now = now_micros(ctx);
    let mut removed: u32 = 0;

    let expired: Vec<_> = ctx.db.jwt_signing_key().iter().take(MAX_RESULTS)
        .filter(|k: &JwtSigningKey| {
            !k.is_current && !k.is_trusted && k.expires_at > 0 && k.expires_at <= now
        })
        .collect();

    for key in &expired {
        ctx.db.jwt_signing_key().id().delete(&key.id);
        removed += 1;
    }

    // Log the event
    if removed > 0 {
        let event_id = uuid_v4_uniq(
            ctx,
            |id| ctx.db.key_rotation_event().id().find(id).is_none(),
            3,
        );
        ctx.db.key_rotation_event().insert(KeyRotationEvent {
            id: event_id,
            event_type: "purge_expired".to_string(),
            detail: format!("Purged {} expired signing keys", removed),
            created_at: now,
        });
    }

    Ok(())
}

/// Event log for key rotation actions.
#[table(accessor = key_rotation_event, public)]
#[derive(Debug, Clone)]
pub struct KeyRotationEvent {
    #[primary_key]
    pub id: String,
    /// "register", "revoke", "purge_expired"
    pub event_type: String,
    pub detail: String,
    pub created_at: i64,
}
