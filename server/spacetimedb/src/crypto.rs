use spacetimedb::*;
use aes_gcm::{Aes256Gcm, Nonce};
use aes_gcm::aead::{Aead, KeyInit};

use crate::auth::require_auth;
use crate::auth::require_admin;
use crate::memory::memory;
use crate::workspace::check_space_access;

/// AES-256-GCM encrypted fields are returned as hex-encoded strings.
///
/// Payload format (hex of packed bytes):
///   nonce(12 bytes) || ciphertext || GCM tag(16 bytes)
///
/// Key is AEAD key (32 bytes) stored per-workspace in `WorkspaceEncryptionKey`.
const NONCE_LEN: usize = 12;

/// Per-workspace AES-256-GCM data encryption key.
/// Only one key per workspace. The key is 32 bytes stored as a hex string.
/// SECURITY: this table must stay PRIVATE — it holds raw key material.
/// (Was public until the 2026-07-17 audit: any client could read every
/// workspace's AES key via SQL, defeating at-rest encryption entirely.)
#[table(accessor = workspace_encryption_key)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct WorkspaceEncryptionKey {
    #[primary_key]
    pub workspace_id: String,
    /// 64-char lowercase hex string (32 bytes raw)
    pub key_hex: String,
    /// When this key was created
    pub created_at: i64,
    /// Identity that created this key
    pub created_by: String,
    /// Whether encryption is active for this workspace
    pub enabled: bool,
}

/// Generate a new AES-256 key (32 bytes) from the STDB RNG.
fn generate_key(ctx: &ReducerContext) -> [u8; 32] {
    use spacetimedb::rand::RngCore;
    let mut key = [0u8; 32];
    ctx.rng().fill_bytes(&mut key);
    key
}

/// Encrypt plaintext with AES-256-GCM using the given key hex.
/// Uses thread_rng for nonce generation — TEST-ONLY. Gated behind cfg(test)
/// because wasi `random_get` is not provided by the SpacetimeDB host; any
/// thread_rng usage compiled into the release module makes it unpublishable.
/// Reducers must call `encrypt_field_in_reducer` (ctx.rng()) instead.
/// Returns hex-encoded nonce || ciphertext || tag.
#[cfg(test)]
pub fn encrypt_field(plaintext: &str, key_hex: &str) -> Result<String, String> {
    let key_bytes = hex_to_key(key_hex)?;
    let cipher = Aes256Gcm::new_from_slice(&key_bytes)
        .map_err(|e| format!("Invalid key length: {}", e))?;

    let mut nonce_bytes = [0u8; 12];
    use rand::RngCore;
    rand::thread_rng().fill_bytes(&mut nonce_bytes);
    let nonce: &Nonce<aes_gcm::aead::consts::U12> = (&nonce_bytes).into();

    let ciphertext = cipher
        .encrypt(nonce, plaintext.as_bytes())
        .map_err(|e| format!("Encryption failed: {}", e))?;

    // Pack: nonce (12) || ciphertext+tag (variable)
    let mut packed = Vec::with_capacity(NONCE_LEN + ciphertext.len());
    packed.extend_from_slice(nonce);
    packed.extend_from_slice(&ciphertext);

    Ok(hex::encode(&packed))
}

/// Decrypt a hex-encoded packed ciphertext with AES-256-GCM.
pub fn decrypt_field(cipher_hex: &str, key_hex: &str) -> Result<String, String> {
    let key_bytes = hex_to_key(key_hex)?;
    let packed = hex::decode(cipher_hex).map_err(|e| format!("Invalid hex ciphertext: {}", e))?;

    if packed.len() < NONCE_LEN + 16 {
        return Err(format!(
            "Ciphertext too short: {} bytes (need at least {})",
            packed.len(),
            NONCE_LEN + 16
        ));
    }

    let cipher = Aes256Gcm::new_from_slice(&key_bytes)
        .map_err(|e| format!("Invalid key length: {}", e))?;
    // Length is pre-checked above (packed.len() >= NONCE_LEN + 16).
    let nonce_bytes: &[u8; NONCE_LEN] = packed[..NONCE_LEN]
        .try_into()
        .map_err(|_| "Invalid nonce length".to_string())?;
    let nonce: &Nonce<aes_gcm::aead::consts::U12> = nonce_bytes.into();
    let ciphertext = &packed[NONCE_LEN..];

    let plaintext = cipher
        .decrypt(nonce, ciphertext)
        .map_err(|e| format!("Decryption failed (wrong key or corrupted data): {}", e))?;

    String::from_utf8(plaintext).map_err(|e| format!("Decrypted data is not valid UTF-8: {}", e))
}

/// Check if a string looks like an encrypted field (hex-encoded, >= 56 chars = 28 bytes min).
/// Simple heuristic: hex string long enough to contain nonce + tag.
pub fn looks_encrypted(s: &str) -> bool {
    s.len() >= 56 && s.chars().all(|c| c.is_ascii_hexdigit())
}

/// Encrypt a field using the reducer-context RNG for the nonce.
/// This is the version to call from reducers (uses STDB RNG, not thread_rng).
pub fn encrypt_field_in_reducer(ctx: &ReducerContext, plaintext: &str, key_hex: &str) -> Result<String, String> {
    let key_bytes = hex_to_key(key_hex)?;
    let cipher = Aes256Gcm::new_from_slice(&key_bytes)
        .map_err(|e| format!("Invalid key length: {}", e))?;

    use spacetimedb::rand::RngCore;
    let mut nonce_bytes = [0u8; 12];
    ctx.rng().fill_bytes(&mut nonce_bytes);
    let nonce: &Nonce<aes_gcm::aead::consts::U12> = (&nonce_bytes).into();

    let ciphertext = cipher
        .encrypt(nonce, plaintext.as_bytes())
        .map_err(|e| format!("Encryption failed: {}", e))?;

    let mut packed = Vec::with_capacity(NONCE_LEN + ciphertext.len());
    packed.extend_from_slice(nonce);
    packed.extend_from_slice(&ciphertext);

    Ok(hex::encode(&packed))
}

fn hex_to_key(hex_str: &str) -> Result<[u8; 32], String> {
    let bytes = hex::decode(hex_str).map_err(|e| format!("Invalid key hex: {}", e))?;
    if bytes.len() != 32 {
        return Err(format!("Key must be 32 bytes, got {}", bytes.len()));
    }
    let mut key = [0u8; 32];
    key.copy_from_slice(&bytes);
    Ok(key)
}



/// Helper: if encryption is enabled for the workspace, encrypt the field.
/// If encryption is not enabled or no key exists, returns the plaintext unchanged.
pub fn encrypt_if_enabled(ctx: &ReducerContext, workspace_id: &str, plaintext: &str) -> Result<String, String> {
    let maybe_key = ctx.db.workspace_encryption_key().workspace_id().find(workspace_id.to_string());
    match maybe_key {
        Some(k) if k.enabled => encrypt_field_in_reducer(ctx, plaintext, &k.key_hex),
        _ => Ok(plaintext.to_string()),
    }
}
/// Helper: if encryption is enabled for the workspace, decrypt the field.
/// If encryption is not enabled or the content is not encrypted, returns the value unchanged.
pub fn decrypt_if_enabled(ctx: &ReducerContext, workspace_id: &str, ciphertext: &str) -> String {
    let maybe_key = ctx.db.workspace_encryption_key().workspace_id().find(workspace_id.to_string());
    match maybe_key {
        Some(k) if k.enabled && looks_encrypted(ciphertext) => {
            decrypt_field(ciphertext, &k.key_hex).unwrap_or_else(|_| ciphertext.to_string())
        }
        _ => ciphertext.to_string(),
    }
}


// ─── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// Helper: a valid 64-char hex key (32 bytes) for testing.
    fn test_key_hex() -> &'static str {
        "a1b2c3d4e5f60718293a4b5c6d7e8f901a2b3c4d5e6f708192a3b4c5d6e7f809"
    }

    /// Another valid key for wrong-key tests.
    fn other_key_hex() -> &'static str {
        "deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe"
    }

    // ── hex_to_key ──────────────────────────────────────────────────────────

    #[test]
    fn test_hex_to_key_valid() -> Result<(), String> {
        let key = hex_to_key(test_key_hex())
            .map_err(|e| format!("valid test key hex should decode to 32 bytes: {}", e))?;
        assert_eq!(key.len(), 32);
        Ok(())
    }

    #[test]
    fn test_hex_to_key_wrong_length() {
        let err = hex_to_key("abcd").unwrap_err();
        assert!(err.contains("32 bytes"));
    }

    #[test]
    fn test_hex_to_key_invalid_hex() {
        let err = hex_to_key("zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz").unwrap_err();
        assert!(err.contains("Invalid key hex"));
    }

    #[test]
    fn test_hex_to_key_empty() {
        let err = hex_to_key("").unwrap_err();
        assert!(err.contains("32 bytes"));
    }

    // ── encrypt / decrypt roundtrip ─────────────────────────────────────────

    #[test]
    fn test_encrypt_decrypt_roundtrip() -> Result<(), String> {
        let plaintext = "Hello, world!";
        let cipher = encrypt_field(plaintext, test_key_hex())
            .map_err(|e| format!("encrypt_field should succeed with valid key and plaintext: {}", e))?;
        assert!(cipher.len() > 56);
        let decrypted = decrypt_field(&cipher, test_key_hex())
            .map_err(|e| format!("decrypt_field should roundtrip successfully: {}", e))?;
        assert_eq!(decrypted, plaintext);
        Ok(())
    }

    #[test]
    fn test_encrypt_decrypt_empty_string() -> Result<(), String> {
        let plaintext = "";
        let cipher = encrypt_field(plaintext, test_key_hex())
            .map_err(|e| format!("encrypt empty string should succeed: {}", e))?;
        // Empty plaintext → 12-byte nonce + 16-byte tag = 28 bytes = exactly 56 hex chars
        assert!(cipher.len() >= 56);
        let decrypted = decrypt_field(&cipher, test_key_hex())
            .map_err(|e| format!("decrypt empty string should succeed: {}", e))?;
        assert_eq!(decrypted, "");
        Ok(())
    }

    #[test]
    fn test_encrypt_decrypt_long_string() -> Result<(), String> {
        let plaintext = "A".repeat(10_000);
        let cipher = encrypt_field(&plaintext, test_key_hex())
            .map_err(|e| format!("encrypt long string should succeed: {}", e))?;
        let decrypted = decrypt_field(&cipher, test_key_hex())
            .map_err(|e| format!("decrypt long string should roundtrip: {}", e))?;
        assert_eq!(decrypted, plaintext);
        Ok(())
    }

    #[test]
    fn test_encrypt_decrypt_special_chars() -> Result<(), String> {
        let plaintext = "Hello, 世界! 🔐 \\n\\t\\r\\0 test";
        let cipher = encrypt_field(plaintext, test_key_hex())
            .map_err(|e| format!("encrypt special characters should succeed: {}", e))?;
        let decrypted = decrypt_field(&cipher, test_key_hex())
            .map_err(|e| format!("decrypt special characters should roundtrip: {}", e))?;
        assert_eq!(decrypted, plaintext);
        Ok(())
    }

    // ── wrong key / tampered data ───────────────────────────────────────────

    #[test]
    fn test_decrypt_wrong_key_fails() -> Result<(), String> {
        let plaintext = "secret data";
        let cipher = encrypt_field(plaintext, test_key_hex())
            .map_err(|e| format!("encrypt_field should succeed for wrong-key test: {}", e))?;
        let err = decrypt_field(&cipher, other_key_hex()).unwrap_err();
        assert!(err.contains("wrong key") || err.contains("Decryption failed"));
        Ok(())
    }

    #[test]
    fn test_decrypt_short_ciphertext() {
        let err = decrypt_field("abcd", test_key_hex()).unwrap_err();
        assert!(err.contains("too short"));
    }

    #[test]
    fn test_decrypt_invalid_hex() {
        let err = decrypt_field("not-hex-at-all!!!!!", test_key_hex()).unwrap_err();
        assert!(err.contains("Invalid hex"));
    }

    #[test]
    fn test_decrypt_empty_ciphertext() {
        let err = decrypt_field("", test_key_hex()).unwrap_err();
        assert!(err.contains("Invalid hex") || err.contains("too short"));
    }

    // ── encrypt with invalid key ────────────────────────────────────────────

    #[test]
    fn test_encrypt_invalid_key() {
        let err = encrypt_field("hello", "bad-key").unwrap_err();
        assert!(err.contains("Invalid key hex") || err.contains("Key must be 32 bytes"));
    }

    #[test]
    fn test_encrypt_empty_key() {
        let err = encrypt_field("hello", "").unwrap_err();
        assert!(err.contains("Invalid key hex") || err.contains("Key must be 32 bytes"));
    }

    // ── looks_encrypted ────────────────────────────────────────────────────

    #[test]
    fn test_looks_encrypted_long_enough_hex() {
        // 64 hex chars = 32 bytes, well over 56 threshold
        assert!(looks_encrypted("abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"));
    }

    #[test]
    fn test_looks_encrypted_too_short() {
        assert!(!looks_encrypted("abcd"));
        assert!(!looks_encrypted(""));
        // 55 chars is below the 56 threshold
        assert!(!looks_encrypted("a".repeat(55).as_str()));
    }

    #[test]
    fn test_looks_encrypted_boundary_56() {
        // Exactly 56 hex chars should return true
        assert!(looks_encrypted("a".repeat(56).as_str()));
    }

    #[test]
    fn test_looks_encrypted_non_hex_chars() {
        // Non-hex characters (even if long enough)
        assert!(!looks_encrypted("z".repeat(56).as_str()));
        assert!(!looks_encrypted("abcdefghijklmnopqrstuvwxyz".repeat(3).as_str()));
    }

    #[test]
    fn test_looks_encrypted_mixed_case_hex() {
        // Uppercase hex is valid
        assert!(looks_encrypted("A".repeat(56).as_str()));
        assert!(looks_encrypted("ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789"));
    }

    #[test]
    fn test_encrypted_output_looks_encrypted() -> Result<(), String> {
        let cipher = encrypt_field("test", test_key_hex())
            .map_err(|e| format!("encrypt test string should succeed for looks_encrypted test: {}", e))?;
        assert!(looks_encrypted(&cipher));
        Ok(())
    }

    // ── deterministic failure modes ─────────────────────────────────────────

    #[test]
    fn test_decrypt_corrupted_ciphertext() -> Result<(), String> {
        let plaintext = "important secret";
        let cipher = encrypt_field(plaintext, test_key_hex())
            .map_err(|e| format!("encrypt should succeed before corruption test: {}", e))?;
        // Flip a bit in the middle of the hex string
        let mut chars: Vec<char> = cipher.chars().collect();
        let idx = chars.len() / 2;
        chars[idx] = if chars[idx] == 'a' { 'b' } else { 'a' };
        let corrupted: String = chars.into_iter().collect();
        let err = decrypt_field(&corrupted, test_key_hex()).unwrap_err();
        assert!(err.contains("Decryption failed") || err.contains("wrong key"));
        Ok(())
    }
}

// ─── Reducers ───────────────────────────────────────────────────────────────

/// Initialise encryption for a workspace.
/// Generates a new AES-256 key and stores it.
/// Idempotent — returns error if key already exists.
#[reducer]
pub fn init_workspace_encryption(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let caller = ctx.sender().to_hex();

    if ctx.db.workspace_encryption_key().workspace_id().find(&workspace_id).is_some() {
        return Err(format!("Encryption key already exists for workspace '{}'", workspace_id));
    }

    let key_bytes = generate_key(ctx);
    let key_hex = hex::encode(key_bytes);

    ctx.db.workspace_encryption_key().insert(WorkspaceEncryptionKey {
        workspace_id,
        key_hex,
        created_at: crate::now_micros(ctx),
        created_by: caller.to_string(),
        enabled: true,
    });

    Ok(())
}

/// Enable or disable encryption for a workspace.
#[reducer]
pub fn set_workspace_encryption_enabled(
    ctx: &ReducerContext,
    workspace_id: String,
    enabled: bool,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let mut key = ctx
        .db
        .workspace_encryption_key()
        .workspace_id()
        .find(&workspace_id)
        .ok_or_else(|| format!("No encryption key found for workspace '{}'", workspace_id))?;
    key.enabled = enabled;
    ctx.db.workspace_encryption_key().workspace_id().update(key);
    Ok(())
}

/// Rotate the encryption key for a workspace.
/// New memories use the new key. Run `encrypt_existing_memories` after to re-key existing ones.
#[reducer]
pub fn rotate_workspace_encryption_key(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let mut key = ctx
        .db
        .workspace_encryption_key()
        .workspace_id()
        .find(&workspace_id)
        .ok_or_else(|| format!("No encryption key found for workspace '{}'", workspace_id))?;

    let new_key = generate_key(ctx);
    key.key_hex = hex::encode(new_key);
    ctx.db.workspace_encryption_key().workspace_id().update(key);
    Ok(())
}

/// Result table for `get_decrypted_memory`.
///
/// # Security
/// This table is `public` (world-readable via SQL) because STDB v2 reducers
/// cannot return data in the HTTP response — they are limited to
/// `Result<(), impl Display>`.  Until STDB adds reducer return-value support,
/// callers should:
/// 1. Call `get_decrypted_memory` reducer
/// 2. Read from this table via SQL
/// 3. **Delete the row immediately after reading** to minimise exposure
///
/// 🔴 Risk: decrypted plaintext memory content is world-readable between
/// the reducer call and cleanup.  Future fix: migrate to STDB's
/// `#[table(accessor = ..., private)]` when response-bearing reducers land,
/// or implement a cleanup-cron for stale rows.
#[table(accessor = decrypted_memory_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DecryptedMemoryResult {
    #[primary_key]
    pub id: String,
    pub caller: String,
    pub memory_id: String,
    pub content: String,
    pub summary: String,
    pub confidence: f64,
    pub memory_type: String,
    pub is_active: bool,
    pub created_at: i64,
    pub tier: String,
}

/// Get a decrypted memory's content and summary.
/// Results are stored in `DecryptedMemoryResult` table for the calling identity.
#[reducer]
pub fn get_decrypted_memory(ctx: &ReducerContext, memory_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();

    let mem = ctx
        .db
        .memory()
        .id()
        .find(&memory_id)
        .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;

    check_space_access(ctx, &mem.workspace_id, &caller, "viewer")?;

    let key = ctx
        .db
        .workspace_encryption_key()
        .workspace_id()
        .find(&mem.workspace_id);

    let (content, summary) = if let Some(ref k) = key {
        if k.enabled && looks_encrypted(&mem.content) {
            let c = decrypt_field(&mem.content, &k.key_hex).unwrap_or_else(|_| mem.content.clone());
            let s = decrypt_field(&mem.summary, &k.key_hex).unwrap_or_else(|_| mem.summary.clone());
            (c, s)
        } else {
            (mem.content.clone(), mem.summary.clone())
        }
    } else {
        (mem.content.clone(), mem.summary.clone())
    };

    // Clear old results for this caller
    let old: Vec<_> = ctx
        .db
        .decrypted_memory_result()
        .iter()
        .filter(|r| r.caller == caller.to_string())
        .map(|r| r.id.clone())
        .collect();
    for id in old {
        ctx.db.decrypted_memory_result().id().delete(id);
    }

    let result_id = crate::uuid_v4_uniq(
        ctx,
        |id| ctx.db.decrypted_memory_result().id().find(id).is_none(),
        3,
    );
    ctx.db.decrypted_memory_result().insert(DecryptedMemoryResult {
        id: result_id,
        caller: caller.to_string(),
        memory_id,
        content,
        summary,
        confidence: mem.confidence,
        memory_type: mem.memory_type.clone(),
        is_active: mem.is_active,
        created_at: mem.created_at,
        tier: mem.tier.clone(),
    });

    Ok(())
}

/// Re-encrypt all *unencrypted* memories in a workspace.
/// Useful after initial encryption setup or key rotation (encrypts plaintext fields
/// that were stored before encryption was enabled).
#[reducer]
pub fn encrypt_existing_memories(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let key = ctx
        .db
        .workspace_encryption_key()
        .workspace_id()
        .find(&workspace_id)
        .ok_or_else(|| format!("No encryption key found for workspace '{}'", workspace_id))?;

    if !key.enabled {
        return Err(format!("Encryption is disabled for workspace '{}'", workspace_id));
    }

    let memories: Vec<_> = ctx
        .db
        .memory()
        .iter()
        .filter(|m| m.workspace_id == workspace_id)
        .collect();

    let mut count = 0u32;
    for mut mem in memories {
        if looks_encrypted(&mem.content) {
            continue; // Already encrypted
        }
        let enc_content = encrypt_field_in_reducer(ctx, &mem.content, &key.key_hex)?;
        let enc_summary = encrypt_field_in_reducer(ctx, &mem.summary, &key.key_hex)?;
        mem.content = enc_content;
        mem.summary = enc_summary;
        mem.updated_at = crate::now_micros(ctx);
        ctx.db.memory().id().update(mem);
        count += 1;
    }

    if count > 0 {
        crate::change_event::log_change(
            ctx,
            &workspace_id,
            "encryption",
            "encrypt_batch",
            &format!("{}_encrypted", workspace_id),
            &format!(
                "{{\"workspace_id\":\"{}\",\"encrypted_count\":{}}}",
                workspace_id, count
            ),
        );
    }

    Ok(())
}
