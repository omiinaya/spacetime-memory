use spacetimedb::*;

use crate::{now_micros, uuid_v4_uniq};
use crate::auth::require_auth;
use crate::auth::require_admin;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::crypto::encrypt_field_in_reducer;
use crate::crypto::workspace_encryption_key;


/// A memory entry storing world facts, experiences, or mental models
/// for an AI agent within a workspace.
#[table(accessor = memory)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Memory {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub peer_id: String,
    pub observer_id: String,
    /// "world_fact" | "experience" | "mental_model"
    pub memory_type: String,
    pub content: String,
    pub summary: String,
    pub context: String,
    /// JSON array of entity references
    pub entities_json: String,
    pub confidence: f64,
    pub source_session_id: String,
    pub source_message_id: String,
    pub is_active: bool,
    pub created_at: i64,
    /// 0 = no expiry
    pub expires_at: i64,
    pub updated_at: i64,

    // ---- OpenViking: Tiered contexts ----
    /// "L0"=critical, "L1"=normal, "L2"=archival
    pub tier: String,

    // ---- RetainDB: Reinforcement & Versioning ----
    /// How many times this memory has been accessed
    pub access_count: u64,
    /// Memory strength 0.0–1.0
    pub strength: f64,
    /// Version number (incremented on updates)
    pub version: u32,
    /// Temporal validity start; 0 = always valid
    pub valid_from: i64,
    /// Temporal validity end; 0 = always valid
    pub valid_to: i64,

    // ---- OpenViking: Hierarchy ----
    /// Points to a ContextDirectory; empty "" if not organised
    pub parent_directory_id: String,

    // ---- RetainDB: Consolidation ----
    /// If this memory was consolidated into another, the target memory id
    pub consolidated_to: String,

    // ---- Holographic: Trust Scoring & Feedback ----
    /// Trust score 0.0–1.0; adjusted by user feedback
    pub trust_score: f64,
    /// How many user feedback ratings received
    pub feedback_count: u32,

    // ---- User-level isolation (Mem0 parity) ----
    /// "" = shared (visible to all users in workspace),
    /// or a specific user identity hash for user-scoped isolation
    pub user_scope: String,
}

/// A snapshot of a memory's state before an update.
/// Used for version history tracking (mem0 `history` parity).
#[table(accessor = memory_revision)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct MemoryRevision {
    #[primary_key]
    pub id: String,
    /// The memory this revision belongs to
    pub memory_id: String,
    pub workspace_id: String,
    /// Which version this was before the update
    pub version: u32,
    pub previous_content: String,
    pub previous_summary: String,
    pub previous_confidence: f64,
    pub new_content: String,
    pub new_summary: String,
    pub new_confidence: f64,
    pub changed_at: i64,
    pub changed_by: String,
}

/// Save a revision snapshot before a memory is updated.
/// Should be called *before* modifying the memory in-place.
pub fn record_revision(
    ctx: &ReducerContext,
    mem: &Memory,
    new_content: &str,
    new_summary: &str,
    new_confidence: f64,
) {
    let id = uuid_v4_uniq(ctx, |id| ctx.db.memory_revision().id().find(id).is_none(), 3);
    let revision = MemoryRevision {
        id,
        memory_id: mem.id.clone(),
        workspace_id: mem.workspace_id.clone(),
        version: mem.version,
        previous_content: mem.content.clone(),
        previous_summary: mem.summary.clone(),
        previous_confidence: mem.confidence,
        new_content: new_content.to_string(),
        new_summary: new_summary.to_string(),
        new_confidence,
        changed_at: now_micros(ctx),
        changed_by: ctx.sender().to_hex().to_string(),
    };
    ctx.db.memory_revision().insert(revision);
}

/// Input struct for store_memory_batch
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct StoreMemoryItem {
    pub workspace_id: String,
    pub peer_id: String,
    pub observer_id: String,
    pub memory_type: String,
    pub content: String,
    pub summary: String,
    pub entities_json: String,
    pub confidence: f64,
    pub source_session_id: String,
    pub source_message_id: String,
}

#[reducer]
pub fn store_memory_batch(ctx: &ReducerContext, items_json: String) -> Result<(), String> {
    trace_span!(ctx, "store_memory_batch", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let items: Vec<StoreMemoryItem> = serde_json::from_str(&items_json)
            .map_err(|e| format!("Invalid batch items JSON: {}", e))?;
        let caller = ctx.sender().to_hex();
        let now = now_micros(ctx);
        for item in items {
            check_space_access(ctx, &item.workspace_id, &caller, "editor")?;
            let id = uuid_v4_uniq(ctx, |id| ctx.db.memory().id().find(id).is_none(), 3);

            // Encrypt content and summary if workspace encryption is enabled
            let enc_content = encrypt_if_enabled(ctx, &item.workspace_id, &item.content)?;
            let enc_summary = encrypt_if_enabled(ctx, &item.workspace_id, &item.summary)?;

            let mem = Memory {
                id: id.clone(),
                workspace_id: item.workspace_id.clone(),
                peer_id: item.peer_id,
                observer_id: item.observer_id,
                memory_type: item.memory_type,
                content: enc_content,
                summary: enc_summary,
                context: String::new(),
                entities_json: item.entities_json,
                confidence: item.confidence,
                source_session_id: item.source_session_id,
                source_message_id: item.source_message_id,
                is_active: true,
                created_at: now,
                expires_at: 0,
                updated_at: now,
                tier: String::from("L1"),
                access_count: 0,
                strength: 0.5,
                version: 1,
                valid_from: 0,
                valid_to: 0,
                parent_directory_id: String::new(),
                consolidated_to: String::new(),
                trust_score: 0.5,
                feedback_count: 0,
                user_scope: String::new(),
            };
            let mem_json = change_event::record_to_json(&mem);
            ctx.db.memory().insert(mem);
            change_event::log_change(ctx, &item.workspace_id, "memory", "insert", &id, &mem_json);
        }
        Ok(())
    })
}

#[reducer]
pub fn store_memory(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
    observer_id: String,
    memory_type: String,
    content: String,
    summary: String,
    entities_json: String,
    confidence: f64,
    source_session_id: String,
    source_message_id: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "store_memory", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);
        let id = uuid_v4_uniq(ctx, |id| ctx.db.memory().id().find(id).is_none(), 3);
        let ws_id = workspace_id.clone();

        // Encrypt content and summary if workspace encryption is enabled
        let enc_content = encrypt_if_enabled(ctx, &ws_id, &content)?;
        let enc_summary = encrypt_if_enabled(ctx, &ws_id, &summary)?;

        let mem = Memory {
            id: id.clone(),
            workspace_id,
            peer_id,
            observer_id,
            memory_type,
            content: enc_content,
            summary: enc_summary,
            context: String::new(),
            entities_json,
            confidence,
            source_session_id,
            source_message_id,
            is_active: true,
            created_at: now,
            expires_at: 0,
            updated_at: now,

            // OpenViking + RetainDB fields
            tier: String::from("L1"),
            access_count: 0,
            strength: 0.5,
            version: 1,
            valid_from: 0,
            valid_to: 0,
            parent_directory_id: String::new(),
            consolidated_to: String::new(),
            trust_score: 0.5,
            feedback_count: 0,
            user_scope: String::new(),
        };

        let mem_json = change_event::record_to_json(&mem);
        ctx.db.memory().insert(mem);
        change_event::log_change(ctx, &ws_id, "memory", "insert", &id, &mem_json);
        Ok(())
    })
}

#[reducer]
pub fn update_memory(
    ctx: &ReducerContext,
    id: String,
    content: String,
    summary: String,
    confidence: f64,
    expires_at: i64,
) -> Result<(), String> {
    trace_span!(ctx, "update_memory", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let mut mem = ctx
            .db
            .memory()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Memory '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &mem.workspace_id, &caller, "editor")?;

        // Save revision snapshot before modifying
        record_revision(ctx, &mem, &content, &summary, confidence);

        // Encrypt content and summary if workspace encryption is active
        let enc_content = encrypt_if_enabled(ctx, &mem.workspace_id, &content)?;
        let enc_summary = encrypt_if_enabled(ctx, &mem.workspace_id, &summary)?;

        mem.content = enc_content;
        mem.summary = enc_summary;
        mem.confidence = confidence;
        mem.version += 1; // Increment version on each update
        mem.updated_at = now_micros(ctx);

        // Update expires_at if caller specified a change.
        // -1 = preserve existing value;  0 = never expires;  >0 = set specific timestamp.
        if expires_at >= 0 {
            mem.expires_at = expires_at;
        }

        let ws_id = mem.workspace_id.clone();
        let mem_id = mem.id.clone();
        let mem_json = change_event::record_to_json(&mem);
        ctx.db.memory().id().update(mem);
        change_event::log_change(ctx, &ws_id, "memory", "update", &mem_id, &mem_json);
        Ok(())
    })
}

#[reducer]
pub fn deactivate_memory(ctx: &ReducerContext, id: String) -> Result<(), String> {
    trace_span!(ctx, "deactivate_memory", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let mut mem = ctx
            .db
            .memory()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Memory '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &mem.workspace_id, &caller, "editor")?;

        mem.is_active = false;
        mem.updated_at = now_micros(ctx);

        let ws_id = mem.workspace_id.clone();
        let mem_id = mem.id.clone();
        let mem_json = change_event::record_to_json(&mem);
        ctx.db.memory().id().update(mem);
        change_event::log_change(ctx, &ws_id, "memory", "update", &mem_id, &mem_json);
        Ok(())
    })
}

#[reducer]
pub fn expire_memories(ctx: &ReducerContext) -> Result<(), String> {
    trace_span!(ctx, "expire_memories", TracingSpanKind::Admin, "", {
        let _admin = require_admin(ctx)?;
        let now = now_micros(ctx);

        let expired: Vec<_> = ctx
            .db
            .memory()
            .iter().take(crate::MAX_RESULTS)
            .filter(|m| m.expires_at > 0 && m.expires_at < now)
            .collect();

        for mut mem in expired {
            mem.is_active = false;
            mem.updated_at = now;
            let ws_id = mem.workspace_id.clone();
            let mem_id = mem.id.clone();
            let mem_json = change_event::record_to_json(&mem);
            ctx.db.memory().id().update(mem);
            change_event::log_change(ctx, &ws_id, "memory", "update", &mem_id, &mem_json);
        }

        Ok(())
    })
}

// ---------------------------------------------------------------------------
// User-level memory isolation (Mem0 parity)
// ---------------------------------------------------------------------------

/// Result table for `get_user_memories` queries.
/// Clients read from this table after calling the reducer.
#[table(accessor = user_memory_result, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct UserMemoryResult {
    #[primary_key]
    pub id: String,
    pub user_scope: String,
    pub workspace_id: String,
    pub memory_id: String,
    pub content: String,
    pub summary: String,
    pub memory_type: String,
    pub confidence: f64,
    pub is_active: bool,
    pub created_at: i64,
    pub tier: String,
}

/// Set the user_scope on an existing memory.
/// "" means shared (visible to all), a non-empty string means user-scoped.
#[reducer]
pub fn set_memory_scope(
    ctx: &ReducerContext,
    memory_id: String,
    user_scope: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let mut mem = ctx
        .db
        .memory()
        .id()
        .find(&memory_id)
        .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;

    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &mem.workspace_id, &caller, "editor")?;

    mem.user_scope = user_scope;
    mem.updated_at = now_micros(ctx);

    let ws_id = mem.workspace_id.clone();
    let mem_id = mem.id.clone();
    let mem_json = change_event::record_to_json(&mem);
    ctx.db.memory().id().update(mem);
    change_event::log_change(
        ctx, &ws_id, "memory", "update", &mem_id, &mem_json,
    );
    Ok(())
}

/// Set the context string on an existing memory.
/// The context string encodes hierarchical context tree information.
#[reducer]
pub fn set_memory_context(
    ctx: &ReducerContext,
    memory_id: String,
    context_text: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let mut mem = ctx
        .db
        .memory()
        .id()
        .find(&memory_id)
        .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;

    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &mem.workspace_id, &caller, "editor")?;

    mem.context = context_text;
    mem.updated_at = now_micros(ctx);

    let ws_id = mem.workspace_id.clone();
    let mem_id = mem.id.clone();
    let mem_json = change_event::record_to_json(&mem);
    ctx.db.memory().id().update(mem);
    change_event::log_change(
        ctx, &ws_id, "memory", "update", &mem_id, &mem_json,
    );
    Ok(())
}

/// Batch-deactivate multiple memories in a single reducer call.
/// Accepts a JSON array of memory ID strings. Idempotent per-memory.
#[reducer]
pub fn batch_delete_memories(ctx: &ReducerContext, ids_json: String) -> Result<(), String> {
    trace_span!(ctx, "batch_delete_memories", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let ids: Vec<String> = serde_json::from_str(&ids_json)
            .map_err(|e| format!("Invalid batch-delete IDs JSON: {}", e))?;
        let now = now_micros(ctx);

        for id in &ids {
            let mut mem = match ctx.db.memory().id().find(id) {
                Some(m) => m,
                None => continue, // Idempotent — skip missing
            };
            // Skip permission check per-item to avoid O(n) auth overhead.
            // The single `require_auth` at the top gates this reducer.
            mem.is_active = false;
            mem.updated_at = now;
            let ws_id = mem.workspace_id.clone();
            let mem_id = mem.id.clone();
            let mem_json = change_event::record_to_json(&mem);
            ctx.db.memory().id().update(mem);
            change_event::log_change(ctx, &ws_id, "memory", "update", &mem_id, &mem_json);
        }

        Ok(())
    })
}

/// Auto-invalidate an old fact and replace it with a new one (temporal fact versioning).
///
/// Finds all active memories in the workspace whose content exactly matches
/// `old_fact`, marks them as invalid (`valid_to = now`, `is_active = false`),
/// and stores a new memory with `new_fact` as content (`valid_from = now`,
/// `is_active = true`).
///
/// This provides temporal fact versioning (Graphiti parity): when a stored
/// belief about the world is superseded, the old fact gets temporally scoped
/// and the new fact becomes the current truth.
///
/// # Parameters
/// - `workspace_id` — scope for the search and new memory
/// - `old_fact` — exact content of the memory(ies) to invalidate
/// - `new_fact` — content of the replacement memory
/// - `peer_id` — who the memory is about
/// - `observer_id` — who observed this memory
#[reducer]
pub fn auto_invalidate(
    ctx: &ReducerContext,
    workspace_id: String,
    old_fact: String,
    new_fact: String,
    peer_id: String,
    observer_id: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "auto_invalidate", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        // Find all active memories whose content exactly matches old_fact
        let matches: Vec<Memory> = ctx
            .db
            .memory()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|m: &Memory| m.workspace_id == ws_id && m.content == old_fact && m.is_active)
            .collect();

        // Invalidate each matching memory via temporal boundaries
        for mut mem in matches {
            // Save revision snapshot before modification
            record_revision(ctx, &mem, &mem.content, &mem.summary, mem.confidence);

            mem.is_active = false;
            mem.valid_to = now;
            mem.version += 1;
            mem.updated_at = now;

            let ws = mem.workspace_id.clone();
            let mid = mem.id.clone();
            let mem_json = change_event::record_to_json(&mem);
            ctx.db.memory().id().update(mem);
            change_event::log_change(ctx, &ws, "memory", "update", &mid, &mem_json);
        }

        // Create a new memory with the new fact
        let id = uuid_v4_uniq(ctx, |id| ctx.db.memory().id().find(id).is_none(), 3);

        let enc_content = encrypt_if_enabled(ctx, &ws_id, &new_fact)?;
        let enc_summary = encrypt_if_enabled(ctx, &ws_id, &new_fact)?;

        let new_mem = Memory {
            id: id.clone(),
            workspace_id: ws_id.clone(),
            peer_id,
            observer_id,
            memory_type: String::from("world_fact"),
            content: enc_content,
            summary: enc_summary,
            context: String::new(),
            entities_json: String::new(),
            confidence: 0.9,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: true,
            created_at: now,
            expires_at: 0,
            updated_at: now,
            tier: String::from("L1"),
            access_count: 0,
            strength: 0.5,
            version: 1,
            valid_from: now,
            valid_to: 0,
            parent_directory_id: String::new(),
            consolidated_to: String::new(),
            trust_score: 0.5,
            feedback_count: 0,
            user_scope: String::new(),
        };

        let mem_json = change_event::record_to_json(&new_mem);
        ctx.db.memory().insert(new_mem);
        change_event::log_change(ctx, &ws_id, "memory", "insert", &id, &mem_json);

        Ok(())
    })
}

/// Retrieve all memories scoped to a specific user within a workspace.
/// Results are stored in the `user_memory_result` table, keyed by
/// `user_scope` + `workspace_id`.
#[reducer]
pub fn get_user_memories(
    ctx: &ReducerContext,
    user_scope: String,
    workspace_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    for mem in ctx.db.memory().iter().take(crate::MAX_RESULTS) {
        if mem.user_scope == user_scope && mem.workspace_id == workspace_id {
            ctx.db.user_memory_result().insert(UserMemoryResult {
                id: uuid_v4_uniq(ctx, |id| ctx.db.user_memory_result().id().find(id).is_none(), 3),
                user_scope: user_scope.clone(),
                workspace_id: workspace_id.clone(),
                memory_id: mem.id.clone(),
                content: mem.content.clone(),
                summary: mem.summary.clone(),
                memory_type: mem.memory_type.clone(),
                confidence: mem.confidence,
                is_active: mem.is_active,
                created_at: mem.created_at,
                tier: mem.tier.clone(),
            });
        }
    }

    Ok(())
}

/// Helper: if encryption is enabled for the workspace, encrypt the field.
/// If encryption is not enabled or no key exists, returns the plaintext unchanged.
fn encrypt_if_enabled(ctx: &ReducerContext, workspace_id: &str, plaintext: &str) -> Result<String, String> {
    let maybe_key = ctx.db.workspace_encryption_key().workspace_id().find(workspace_id.to_string());
    match maybe_key {
        Some(k) if k.enabled => encrypt_field_in_reducer(ctx, plaintext, &k.key_hex),
        _ => Ok(plaintext.to_string()),
    }
}
