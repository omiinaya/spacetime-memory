use crate::auth::require_admin;
use crate::{now_micros, uuid_v4_uniq, MAX_RESULTS};
use p256::elliptic_curve::sec1::ToEncodedPoint;
use p256::pkcs8::DecodePublicKey;
use spacetimedb::*;

// ── Helpers ────────────────────────────────────────────────────────────

/// Parse an EC P-256 public key PEM and return the base64url-encoded
/// x and y coordinates for JWK representation.
fn pubkey_pem_to_jwk_coords(pem: &str) -> Result<(String, String), String> {
    use base64::Engine;
    use p256::PublicKey;

    let pubkey = PublicKey::from_public_key_pem(pem)
        .map_err(|e| format!("Invalid EC P-256 public key PEM: {}", e))?;
    let point = pubkey.to_encoded_point(false); // uncompressed
    let x_bytes = point.x().ok_or("Missing x coordinate")?;
    let y_bytes = point.y().ok_or("Missing y coordinate")?;

    let engine = base64::engine::general_purpose::URL_SAFE_NO_PAD;
    Ok((engine.encode(x_bytes), engine.encode(y_bytes)))
}

// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// A valid SECP256R1 (P-256) public key in PEM format.
    /// Generated with: openssl ecparam -name prime256v1 -genkey -noout | openssl ec -pubout
    const VALID_P256_PEM: &str = "-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE3XQusdYQ0D81uJlj/vqgIVxsOQjC
sQeKqTvXxj2Zs14bOyX02c9GuF7+AvgjVe6K389L/tU87XvKcq2KGJ0Q7g==
-----END PUBLIC KEY-----";

    // ── pubkey_pem_to_jwk_coords ────────────────────────────────────────────

    #[test]
    fn test_pubkey_pem_to_jwk_coords_valid() {
        let (x, y) = pubkey_pem_to_jwk_coords(VALID_P256_PEM).unwrap();
        // Both coordinates should be non-empty base64url strings.
        assert!(!x.is_empty(), "x coordinate should not be empty");
        assert!(!y.is_empty(), "y coordinate should not be empty");
        // P-256 coordinates are 32 bytes -> 43 base64url chars (ceil(32*4/3) with no pad)
        assert_eq!(x.len(), 43, "x should be 43 base64url chars (no padding)");
        assert_eq!(y.len(), 43, "y should be 43 base64url chars (no padding)");
        // Verify they're valid base64url
        use base64::Engine;
        let engine = base64::engine::general_purpose::URL_SAFE_NO_PAD;
        assert!(engine.decode(&x).is_ok(), "x should be valid base64url");
        assert!(engine.decode(&y).is_ok(), "y should be valid base64url");
        // They should be different
        assert_ne!(x, y, "x and y coordinates should differ");
    }

    #[test]
    fn test_pubkey_pem_to_jwk_coords_empty_string() {
        let err = pubkey_pem_to_jwk_coords("").unwrap_err();
        assert!(err.contains("Invalid EC P-256 public key PEM"));
    }

    #[test]
    fn test_pubkey_pem_to_jwk_coords_not_a_pem() {
        let err = pubkey_pem_to_jwk_coords("this is not a PEM key").unwrap_err();
        assert!(err.contains("Invalid EC P-256 public key PEM"));
    }

    #[test]
    fn test_pubkey_pem_to_jwk_coords_wrong_key_type() {
        // RSA public key PEM -- parsing should fail because it's not EC P-256
        let rsa_pem = "-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5ZkE1qC3S6jQkYcQgKjK
1iB6Kw2wHn0KJ0y8pX9f0L0y0p0X0L0y0p0X0L0y0p0X0L0y0p0X0L0y0p0QID
AQAB
-----END PUBLIC KEY-----";
        let err = pubkey_pem_to_jwk_coords(rsa_pem).unwrap_err();
        assert!(err.contains("Invalid EC P-256 public key PEM"));
    }

    #[test]
    fn test_pubkey_pem_to_jwk_coords_truncated_pem() {
        let truncated = "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcD";
        let err = pubkey_pem_to_jwk_coords(truncated).unwrap_err();
        assert!(err.contains("Invalid EC P-256 public key PEM"));
    }

    #[test]
    fn test_pubkey_pem_to_jwk_coords_different_key_gives_different_coords() {
        // A different P-256 public key
        const OTHER_P256_PEM: &str = "-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEq+XvYCYzy5ztHUvqLA26x0Wj083r
LLqQfRdL7sncdkLj9Z/pLW7v5MptpEbzuAMd6VHYfHOtqayCbD/EKEqAuA==
-----END PUBLIC KEY-----";
        let (x1, y1) = pubkey_pem_to_jwk_coords(VALID_P256_PEM).unwrap();
        let (x2, y2) = pubkey_pem_to_jwk_coords(OTHER_P256_PEM).unwrap();
        assert_ne!(
            (x1, y1),
            (x2, y2),
            "different keys should produce different coordinates"
        );
    }
}

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
#[table(accessor = jwt_signing_key_result)]
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
    let dup = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .any(|k: JwtSigningKey| k.key_id == key_id);
    if dup {
        return Err(format!("Key ID '{}' is already registered", key_id));
    }

    let now = now_micros(ctx);

    // Compute the next version number
    let max_version = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .map(|k: JwtSigningKey| k.key_version)
        .max()
        .unwrap_or(0);

    let expires_at = if expires_in_days > 0 {
        now + expires_in_days as i64 * 86_400_000_000
    } else {
        0i64
    };

    let id = uuid_v4_uniq(
        ctx,
        |id| ctx.db.jwt_signing_key().id().find(id).is_none(),
        3,
    );

    // Retire the previous current key (keep it trusted for verification)
    let current_keys: Vec<_> = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .filter(|k: &JwtSigningKey| k.is_current)
        .collect();
    for old_key in &current_keys {
        let mut old_key = old_key.clone();
        old_key.is_current = false;
        old_key.retired_at = now;
        ctx.db.jwt_signing_key().id().update(old_key);
    }

    // Insert the new key as current
    ctx.db.jwt_signing_key().insert(JwtSigningKey {
        id: id.clone(),
        key_version: max_version + 1,
        name: name.clone(),
        key_id: key_id.clone(),
        public_key_pem,
        private_key_path,
        is_current: true,
        is_trusted: true,
        created_at: now,
        retired_at: 0,
        expires_at,
    });

    // Publish to result table
    // Pre-cleanup: remove stale results for this key_id
    for old in ctx.db.jwt_signing_key_result().iter()
        .filter(|r| r.key_id == key_id)
        .collect::<Vec<_>>()
    {
        ctx.db.jwt_signing_key_result().id().delete(&old.id);
    }
    ctx.db.jwt_signing_key_result().insert(JwtSigningKeyResult {
        id: uuid_v4_uniq(
            ctx,
            |id| ctx.db.jwt_signing_key_result().id().find(id).is_none(),
            3,
        ),
        key_version: max_version + 1,
        name: name.clone(),
        key_id: key_id.clone(),
        is_current: true,
        is_trusted: true,
        created_at: now,
        retired_at: 0,
        expires_at,
    });

    // Log the rotation event
    let event_id = uuid_v4_uniq(
        ctx,
        |id| ctx.db.key_rotation_event().id().find(id).is_none(),
        3,
    );
    ctx.db.key_rotation_event().insert(KeyRotationEvent {
        id: event_id,
        event_type: "register".to_string(),
        detail: format!(
            "Registered key '{}' (kid={}, version={}){}",
            name,
            key_id,
            max_version + 1,
            String::new(), // No auto-retire — use rotate_signing_key for rotation
        ),
        created_at: now,
    });

    Ok(())
}

/// Rotate the current signing key: retire the existing current key and register
/// a new signing key as the current one.
///
/// This performs a safe, explicit key rotation:
/// - Refuses to rotate if no current key exists (use `register_signing_key` for initial setup).
/// - Retires the previous current key immediately (but keeps it trusted for verification
///   of existing tokens).
/// - Requires `expires_in_days` > 0 for the new key (to prevent accidental permanent keys).
///
/// # Arguments
/// * `name` - Human-readable label for the new key.
/// * `key_id` - SHA-256 fingerprint hex of the new public key (used as JWT `kid`).
/// * `public_key_pem` - The new public key in PEM format.
/// * `private_key_path` - Absolute path to the new private key on the server FS.
/// * `expires_in_days` - Days until the new key expires (must be > 0, use at least 90).
#[reducer]
pub fn rotate_signing_key(
    ctx: &ReducerContext,
    name: String,
    key_id: String,
    public_key_pem: String,
    private_key_path: String,
    expires_in_days: u32,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;

    if expires_in_days == 0 {
        return Err("expires_in_days must be > 0 for rotated keys (use at least 90)".to_string());
    }

    // Find the current trusted signing keys to retire
    let current_keys: Vec<_> = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .filter(|k: &JwtSigningKey| k.is_current && k.is_trusted)
        .collect();

    if current_keys.is_empty() {
        return Err(
            "No current signing key found. Use `register_signing_key` for initial setup instead."
                .to_string(),
        );
    }

    // Validate inputs
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
    let dup = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .any(|k: JwtSigningKey| k.key_id == key_id);
    if dup {
        return Err(format!("Key ID '{}' is already registered", key_id));
    }

    let now = now_micros(ctx);

    // Compute the next version number
    let max_version = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .map(|k: JwtSigningKey| k.key_version)
        .max()
        .unwrap_or(0);

    let expires_at = if expires_in_days > 0 {
        now + expires_in_days as i64 * 86_400_000_000
    } else {
        0i64
    };

    let id = uuid_v4_uniq(
        ctx,
        |id| ctx.db.jwt_signing_key().id().find(id).is_none(),
        3,
    );

    // Retire all previous current keys FIRST
    let mut retired_count = 0u32;
    for mut key in current_keys.clone() {
        key.is_current = false;
        key.retired_at = now;
        ctx.db.jwt_signing_key().id().update(key);
        retired_count += 1;
    }

    // Also update the result table rows for those keys
    for key in &current_keys {
        if let Some(result) = ctx
            .db
            .jwt_signing_key_result()
            .iter()
            .take(MAX_RESULTS)
            .find(|r: &JwtSigningKeyResult| r.key_id == key.key_id)
        {
            let mut updated = result;
            updated.is_current = false;
            updated.retired_at = now;
            ctx.db.jwt_signing_key_result().id().update(updated);
        }
    }

    // Insert the new key as current
    ctx.db.jwt_signing_key().insert(JwtSigningKey {
        id: id.clone(),
        key_version: max_version + 1,
        name: name.clone(),
        key_id: key_id.clone(),
        public_key_pem,
        private_key_path,
        is_current: true,
        is_trusted: true,
        created_at: now,
        retired_at: 0,
        expires_at,
    });

    // Publish to result table
    // Pre-cleanup: remove stale results for this key_id
    for old in ctx.db.jwt_signing_key_result().iter()
        .filter(|r| r.key_id == key_id)
        .collect::<Vec<_>>()
    {
        ctx.db.jwt_signing_key_result().id().delete(&old.id);
    }
    ctx.db.jwt_signing_key_result().insert(JwtSigningKeyResult {
        id: uuid_v4_uniq(
            ctx,
            |id| ctx.db.jwt_signing_key_result().id().find(id).is_none(),
            3,
        ),
        key_version: max_version + 1,
        name: name.clone(),
        key_id: key_id.clone(),
        is_current: true,
        is_trusted: true,
        created_at: now,
        retired_at: 0,
        expires_at,
    });

    // Log the rotation event
    let event_id = uuid_v4_uniq(
        ctx,
        |id| ctx.db.key_rotation_event().id().find(id).is_none(),
        3,
    );
    ctx.db.key_rotation_event().insert(KeyRotationEvent {
        id: event_id,
        event_type: "rotate".to_string(),
        detail: format!(
            "Rotated signing key: retired {} previous key(s), registered new key '{}' (kid={}, version={})",
            retired_count, name, key_id, max_version + 1
        ),
        created_at: now,
    });

    log::info!(
        "Key rotation complete: retired {} key(s), new key '{}' (kid={}, version={})",
        retired_count,
        name,
        key_id,
        max_version + 1
    );

    Ok(())
}

/// List all registered signing keys (metadata only — no private key paths).
/// Results are stored in the public jwt_signing_key_result table.
#[reducer]
pub fn list_signing_keys(ctx: &ReducerContext) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let query_id = format!("list_keys:{}", ctx.sender().to_hex());

    // Clear previous results
    let old: Vec<_> = ctx
        .db
        .jwt_signing_key_result()
        .iter()
        .take(MAX_RESULTS)
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

    let mut key = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .find(|k: &JwtSigningKey| k.key_id == key_id)
        .ok_or_else(|| format!("Signing key '{}' not found", key_id))?;

    if !key.is_trusted {
        return Err(format!("Signing key '{}' is already revoked", key_id));
    }

    // Prevent revoking the only current key
    if key.is_current {
        let other_current = ctx
            .db
            .jwt_signing_key()
            .iter()
            .take(MAX_RESULTS)
            .any(|k: JwtSigningKey| k.is_current && k.key_id != key_id);
        if !other_current {
            return Err(
                "Cannot revoke the only current signing key. Register a new key first.".to_string(),
            );
        }
    }

    let now = now_micros(ctx);
    key.is_current = false;
    key.is_trusted = false;
    key.retired_at = now;
    ctx.db.jwt_signing_key().id().update(key.clone());

    // Log the revocation event
    let event_id = uuid_v4_uniq(
        ctx,
        |id| ctx.db.key_rotation_event().id().find(id).is_none(),
        3,
    );
    ctx.db.key_rotation_event().insert(KeyRotationEvent {
        id: event_id,
        event_type: "revoke".to_string(),
        detail: format!("Revoked signing key '{}' (name={})", key_id, key.name),
        created_at: now,
    });

    Ok(())
}

/// Get the current (active) signing key info.
/// Returns metadata via the jwt_signing_key_result table.
#[reducer]
pub fn get_current_signing_key(ctx: &ReducerContext) -> Result<(), String> {
    let _admin = require_admin(ctx)?;

    let current = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .find(|k: &JwtSigningKey| k.is_current && k.is_trusted)
        .ok_or_else(|| "No current signing key found".to_string())?;

    let query_id = format!("current_key:{}", ctx.sender().to_hex());

    // Clear previous
    let old: Vec<_> = ctx
        .db
        .jwt_signing_key_result()
        .iter()
        .take(MAX_RESULTS)
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

    let expired: Vec<_> = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
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
#[table(accessor = key_rotation_event)]
#[derive(Debug, Clone)]
pub struct KeyRotationEvent {
    #[primary_key]
    pub id: String,
    /// "register", "revoke", "purge_expired"
    pub event_type: String,
    pub detail: String,
    pub created_at: i64,
}

/// JWK Set result — populated by the `get_jwks` reducer.
/// Stores the full JWK Set JSON that clients can fetch via SQL.
#[table(accessor = jwk_set_result)]
#[derive(Debug, Clone)]
pub struct JwkSetResult {
    #[primary_key]
    pub id: String,
    /// The JWK Set JSON payload.
    pub payload: String,
    /// Timestamp (micros) when this result was generated.
    pub created_at: i64,
}

/// Return all trusted signing keys as a JWK Set (RFC 7517).
///
/// The result is written to the `jwk_set_result` table as a single row
/// with the full JWK Set JSON payload.  Clients should call this reducer,
/// then query `SELECT * FROM jwk_set_result ORDER BY created_at DESC LIMIT 1`.
///
/// This endpoint enables JWT verification against any trusted signing key,
/// which is essential for zero-downtime key rotation: tokens signed with
/// old (but still trusted) keys continue to verify even after the current
/// signing key has been rotated.
///
/// Each key's `kid` in the JWK Set matches the `kid` header in the JWT,
/// so verifiers can select the correct key to check the signature.
#[reducer]
pub fn get_jwks(ctx: &ReducerContext) -> Result<(), String> {
    let _admin = require_admin(ctx)?;

    let trusted_keys: Vec<JwtSigningKey> = ctx
        .db
        .jwt_signing_key()
        .iter()
        .take(MAX_RESULTS)
        .filter(|k: &JwtSigningKey| k.is_trusted)
        .collect();

    // Build JWK array entries
    let mut jwk_keys: Vec<serde_json::Value> = Vec::new();
    for key in &trusted_keys {
        match pubkey_pem_to_jwk_coords(&key.public_key_pem) {
            Ok((x, y)) => {
                jwk_keys.push(serde_json::json!({
                    "kty": "EC",
                    "crv": "P-256",
                    "kid": key.key_id,
                    "use": "sig",
                    "alg": "ES256",
                    "x": x,
                    "y": y,
                }));
            }
            Err(e) => {
                // Skip keys we can't parse, log the issue
                let event_id = uuid_v4_uniq(
                    ctx,
                    |id| ctx.db.key_rotation_event().id().find(id).is_none(),
                    3,
                );
                ctx.db.key_rotation_event().insert(KeyRotationEvent {
                    id: event_id,
                    event_type: "jwks_warn".to_string(),
                    detail: format!("Skipped key '{}' in JWKS: {}", key.key_id, e),
                    created_at: now_micros(ctx),
                });
            }
        }
    }

    let jwks = serde_json::json!({
        "keys": jwk_keys,
    });

    let now = now_micros(ctx);
    let result_id = uuid_v4_uniq(ctx, |id| ctx.db.jwk_set_result().id().find(id).is_none(), 3);

    // Clear old results
    let old: Vec<_> = ctx
        .db
        .jwk_set_result()
        .iter()
        .take(MAX_RESULTS)
        .map(|r: JwkSetResult| r.id)
        .collect();
    for id in old {
        ctx.db.jwk_set_result().id().delete(&id);
    }

    ctx.db.jwk_set_result().insert(JwkSetResult {
        id: result_id,
        payload: jwks.to_string(),
        created_at: now,
    });

    Ok(())
}
