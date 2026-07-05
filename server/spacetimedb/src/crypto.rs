use spacetimedb::*;
use aes_gcm::{Aes256Gcm, Key, Nonce};
use aes_gcm::aead::{Aead, KeyInit};

use crate::auth::require_auth;
use crate::auth::require_admin;
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
#[table(accessor = workspace_encryption_key, public)]
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
/// Uses OsRng for nonce generation (works outside reducers).
/// Returns hex-encoded nonce || ciphertext || tag.
pub fn encrypt_field(plaintext: &str, key_hex: &str) -> Result<String, String> {
    let key_bytes = hex_to_key(key_hex)?;
    let key = Key::<Aes256Gcm>::from_slice(&key_bytes);
    let cipher = Aes256Gcm::new(key);

    let mut nonce_bytes = [0u8; 12];
    use rand::RngCore;
    rand::thread_rng().fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

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

    let key = Key::<Aes256Gcm>::from_slice(&key_bytes);
    let cipher = Aes256Gcm::new(key);
    let nonce = Nonce::from_slice(&packed[..NONCE_LEN]);
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
    let key = Key::<Aes256Gcm>::from_slice(&key_bytes);
    let cipher = Aes256Gcm::new(key);

    use spacetimedb::rand::RngCore;
    let mut nonce_bytes = [0u8; 12];
    ctx.rng().fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

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
        created_by: caller,
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
#[table(accessor = decrypted_memory_result, public)]
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
        .filter(|r| r.caller == caller)
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
        caller,
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
