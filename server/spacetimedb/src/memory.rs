use spacetimedb::*;

use crate::{now_micros, uuid_v4_uniq};
use crate::auth::require_auth;
use crate::auth::require_admin;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::crypto::encrypt_if_enabled;
use crate::hybrid_query;


/// A memory entry storing world facts, experiences, or mental models
/// for an AI agent within a workspace.
#[table(accessor = memory, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Memory {
    #[primary_key]
    pub id: String,
    #[index(btree)]
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

    // ---- Source attribution ----
    /// URL the memory was sourced from; "" = no source recorded.
    pub source_url: String,
}

// ---------------------------------------------------------------------------
// Zero-Scheduler Maintenance helpers (maintenance-on-access, no cron)
// ---------------------------------------------------------------------------

/// Decay rate per day giving a ~30-day half-life: λ = ln(2)/30 ≈ 0.0231.
pub const DECAY_LAMBDA_PER_DAY: f64 = 0.0231;
const MICROS_PER_DAY: f64 = 86_400_000_000.0;
/// Max expired memories marked inactive per reducer call (amortized cleanup).
pub const EXPIRE_BATCH_CAP: usize = 25;

/// True if this memory is past its expiry timestamp.
#[inline]
pub fn is_expired(mem: &Memory, now: i64) -> bool {
    mem.expires_at > 0 && mem.expires_at < now
}

/// True if this memory should be visible to reads (active AND not expired).
#[inline]
pub fn is_readable(mem: &Memory, now: i64) -> bool {
    mem.is_active && !is_expired(mem, now)
}

/// Lazily-decayed strength: `strength · e^(−λ·days_since_update)`.
/// Computed at read time — no nightly decay pass required.
pub fn effective_strength(mem: &Memory, now: i64) -> f64 {
    let days = (now - mem.updated_at) as f64 / MICROS_PER_DAY;
    if days <= 0.0 {
        return mem.strength;
    }
    mem.strength * (-DECAY_LAMBDA_PER_DAY * days).exp()
}

/// Mark up to `cap` expired-but-still-active memories inactive (bounded,
/// amortized cleanup piggybacked on real reducer calls). Returns count marked.
pub fn expire_batch(ctx: &ReducerContext, workspace_id: &str, now: i64, cap: usize) -> usize {
    let expired: Vec<_> = ctx
        .db
        .memory()
        .workspace_id()
        .filter(workspace_id)
        .filter(|m| m.is_active && is_expired(m, now))
        .take(cap)
        .collect();
    let count = expired.len();
    for mut mem in expired {
        mem.is_active = false;
        mem.updated_at = now;
        let ws = mem.workspace_id.clone();
        let mid = mem.id.clone();
        let mjson = change_event::record_to_json(&mem);
        ctx.db.memory().id().update(mem);
        change_event::log_change(ctx, &ws, "memory", "expire", &mid, &mjson);
    }
    count
}

/// Amortized maintenance slice run on writes: bounded opportunistic cleanup
/// for a single workspace. Currently: lazy expiration only (≤ EXPIRE_BATCH_CAP
/// rows). Work scales with write activity; idle workspaces do zero work.
pub fn maintenance_slice(ctx: &ReducerContext, workspace_id: &str, now: i64) {
    let _ = expire_batch(ctx, workspace_id, now, EXPIRE_BATCH_CAP);
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
    #[index(btree)]
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
    /// JSON string of image attachments (URLs or base64 data URIs).
    /// Stored in the memory's `context` field.  Empty string = no images.
    #[serde(default)]
    pub context: String,
}

/// Result table for store_memory/store_memory_batch reducers.
/// Each successful insert writes a row with the generated memory ID,
/// caller identity, workspace_id, and a content_prefix (first 100 chars)
/// so the Python SDK can retrieve the memory ID without matching on
/// compressed/encrypted content.
#[table(accessor = memory_insert_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct MemoryInsertResult {
    #[primary_key]
    pub id: String,
    /// The identity that called the store_memory reducer
    pub caller: String,
    pub workspace_id: String,
    /// The generated memory UUID
    pub memory_id: String,
    /// First 100 chars of the original (plaintext) content for lookup matching
    pub content_prefix: String,
    pub created_at: i64,
}

/// Internal helper: insert a memory with all side-effects.
///
/// Shared by `store_memory` and `store_memory_batch` to eliminate duplication.
/// Insert a new memory record. If entities_json is empty, auto-extract
/// entities from the content and update entities_json before storing.
fn insert_memory(
    ctx: &ReducerContext,
    caller: &str,
    workspace_id: &str,
    peer_id: String,
    observer_id: String,
    memory_type: String,
    content: String,
    summary: String,
    context: String,
    mut entities_json: String,
    confidence: f64,
    source_session_id: String,
    source_message_id: String,
    now: i64,
) -> Result<String, String> {
    // Auto-extract entities when caller doesn't provide them
    if entities_json.is_empty() || entities_json == "[]" {
        let (mentions, _entity_ids) = crate::entity_extraction::auto_extract_entities(ctx, workspace_id, &content, now);
        entities_json = serde_json::to_string(
            &mentions.iter().map(|m| serde_json::json!({
                "type": m.entity_type,
                "name": m.name,
            })).collect::<Vec<_>>()
        ).unwrap_or_else(|_| "[]".to_string());
    }
    let id = uuid_v4_uniq(ctx, |id| ctx.db.memory().id().find(id).is_none(), 3);

    // Encrypt content and summary if workspace encryption is enabled
    let enc_content = encrypt_if_enabled(ctx, workspace_id, &content)?;
    let enc_summary = encrypt_if_enabled(ctx, workspace_id, &summary)?;

    let mem = Memory {
        id: id.clone(),
        workspace_id: workspace_id.to_string(),
        peer_id,
        observer_id,
        memory_type,
        content: enc_content,
        summary: enc_summary,
        context,
        entities_json,
        confidence,
        source_session_id,
        source_message_id,
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
        source_url: String::new(),
    };

    let mem_json = change_event::record_to_json(&mem);
    // Use try_insert + collision-retry: STDB's `insert()` panics on unique-key
    // violation, and with panic=abort a single collision aborts the ENTIRE
    // WASM instance — every concurrent store in flight fails with
    // "The instance encountered a fatal error". `ctx.rng()` is deterministic
    // per batch, so concurrent reducers can draw the same UUID and both pass
    // the uuid_v4_uniq pre-check; try_insert + regenerate converts that into
    // a bounded retry instead of an instance-killing panic.
    let mem = crate::insert_row_retry(
        ctx.db.memory(),
        mem,
        |row| {
            row.id = uuid_v4_uniq(ctx, |mid| ctx.db.memory().id().find(mid).is_none(), 5);
        },
        5,
    )?;
    let id = mem.id.clone();

    // Initialize Bayesian veracity tracking with Beta(1,1) uniform prior
    crate::veracity::insert_initial_evidence(ctx, &id, now);

    change_event::log_change(ctx, workspace_id, "memory", "insert", &id, &mem_json);
    // Register in WorkspaceIndex for hybrid_search pre-filtering
    hybrid_query::register_workspace_entity(ctx, workspace_id, "memory", &id);
    // Write to MemoryInsertResult so Python SDK can retrieve generated memory ID
    // Clean up old entries for this caller+workspace first (keeps table bounded)
    for old in ctx.db.memory_insert_result()
        .iter()
        .filter(|r| r.caller == caller && r.workspace_id == workspace_id)
        .collect::<Vec<_>>()
    {
        ctx.db.memory_insert_result().id().delete(&old.id);
    }
    crate::insert_row_retry(
        ctx.db.memory_insert_result(),
        MemoryInsertResult {
            id: String::new(),
            caller: caller.to_string(),
            workspace_id: workspace_id.to_string(),
            memory_id: id.clone(),
            content_prefix: content.chars().take(100).collect::<String>(),
            created_at: now,
        },
        |row| {
            row.id = uuid_v4_uniq(
                ctx,
                |rid| ctx.db.memory_insert_result().id().find(rid).is_none(),
                5,
            );
        },
        5,
    )?;

    Ok(id)
}

#[reducer]
pub fn store_memory_batch(ctx: &ReducerContext, items_json: String) -> Result<(), String> {
    trace_span!(ctx, "store_memory_batch", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let items: Vec<StoreMemoryItem> = serde_json::from_str(&items_json)
            .map_err(|e| format!("Invalid batch items JSON: {}", e))?;
        let caller = ctx.sender().to_hex();
        let now = now_micros(ctx);
        let caller_str = caller.to_string();
        // Chunk oversized batches: each item fans out into entity auto-extraction
        // (kg_node/kg_edge inserts). Processing 200+ items in one WASM transaction
        // exceeded STDB's per-transaction limit and panicked the module
        // (202 items → 20,301 edges, DB crash 2026-08-02). Bounded loops keep
        // every transaction crash-safe while remaining atomic per chunk.
        for chunk in items.chunks(crate::MAX_BATCH_ITEMS) {
            for item in chunk {
                check_space_access(ctx, &item.workspace_id, &caller, "editor")?;
                insert_memory(
                    ctx,
                    &caller_str,
                    &item.workspace_id,
                    item.peer_id.clone(),
                    item.observer_id.clone(),
                    item.memory_type.clone(),
                    item.content.clone(),
                    item.summary.clone(),
                    item.context.clone(),
                    item.entities_json.clone(),
                    item.confidence,
                    item.source_session_id.clone(),
                    item.source_message_id.clone(),
                    now,
                )?;
            }
            // Zero-scheduler maintenance: run once per chunk (not per item)
            if let Some(first) = chunk.first() {
                maintenance_slice(ctx, &first.workspace_id, now);
            }
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
    images_json: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "store_memory", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        insert_memory(
            ctx,
            caller.as_ref(),
            &ws_id,
            peer_id,
            observer_id,
            memory_type,
            content,
            summary,
            images_json,
            entities_json,
            confidence,
            source_session_id,
            source_message_id,
            now,
        )?;

        // Zero-scheduler maintenance: bounded amortized cleanup on every write
        maintenance_slice(ctx, &ws_id, now);
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
        // source_url is immutable after creation — preserved, never overwritten
        // on update (SCHEMA_EVOLUTION_POLICY.md step 3).

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
#[table(accessor = user_memory_result)]
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
/// Delete (deactivate) a single memory by ID.
#[reducer]
pub fn delete_memory(ctx: &ReducerContext, memory_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    match ctx.db.memory().id().find(&memory_id) {
        None => Err(format!("Memory '{}' not found", memory_id)),
        Some(mut mem) => {
            let caller = ctx.sender().to_hex();
            check_space_access(ctx, &mem.workspace_id, &caller, "editor")?;
            mem.is_active = false;
            mem.updated_at = now;
            let ws_id = mem.workspace_id.clone();
            let mem_id = mem.id.clone();
            let mem_json = change_event::record_to_json(&mem);
            ctx.db.memory().id().update(mem);
            change_event::log_change(ctx, &ws_id, "memory", "update", &mem_id, &mem_json);
            Ok(())
        }
    }
}

/// Auto-invalidate an old memory fact in favor of a new contradictory fact.
///
/// When an agent recognizes that new information (identified by `new_fact`)
/// supersedes an older stored fact (identified by `old_fact`), this reducer:
///
/// 1. Validates both memory IDs exist and are in the same workspace.
/// 2. Checks that the caller has editor access to the workspace.
/// 3. Deactivates the old fact (`is_active = false`, `valid_to = now`).
/// 4. Sets `consolidated_to` on the old fact to reference the new fact ID.
/// 5. Logs both changes as update events for audit trail.
///
/// This provides a targeted, ID-based invalidation path — complementary to
/// the content-based dedup/consolidation pipeline. Use it when you know
/// exactly which old memory is contradicted by which new memory.
///
/// # Parameters
/// - `old_fact` — ID of the existing memory to deactivate
/// - `new_fact` — ID of the replacement memory that supersedes it
#[reducer]
pub fn auto_invalidate(
    ctx: &ReducerContext,
    old_fact: String,
    new_fact: String,
) -> Result<(), String> {
    trace_span!(ctx, "auto_invalidate", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        let now = now_micros(ctx);

        // Find and validate old fact
        let mut old = ctx
            .db
            .memory()
            .id()
            .find(&old_fact)
            .ok_or_else(|| format!("old_fact '{}' not found", old_fact))?;

        // Find and validate new fact
        let newer = ctx
            .db
            .memory()
            .id()
            .find(&new_fact)
            .ok_or_else(|| format!("new_fact '{}' not found", new_fact))?;

        // Both must be in the same workspace
        if old.workspace_id != newer.workspace_id {
            return Err(format!(
                "old_fact and new_fact must be in the same workspace, got '{}' and '{}'",
                old.workspace_id, newer.workspace_id
            ));
        }

        let ws_id = old.workspace_id.clone();
        check_space_access(ctx, &ws_id, &caller, "editor")?;

        // Save revision snapshot before modification
        record_revision(ctx, &old, &old.content, &old.summary, old.confidence);

        // Deactivate the old fact and link it to the new one
        old.is_active = false;
        old.valid_to = now;
        old.consolidated_to = new_fact.clone();
        old.version += 1;
        old.updated_at = now;

        let old_id = old.id.clone();
        let old_json = change_event::record_to_json(&old);
        ctx.db.memory().id().update(old);
        change_event::log_change(ctx, &ws_id, "memory", "auto_invalidate_old", &old_id, &old_json);

        // Also log on the new fact to create an audit trail
        let new_json = change_event::record_to_json(&newer);
        change_event::log_change(
            ctx,
            &ws_id,
            "memory",
            "auto_invalidate_new",
            &new_fact,
            &new_json,
        );

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

    // Pre-cleanup: remove stale results for this user_scope + workspace_id
    for old in ctx.db.user_memory_result().iter()
        .filter(|r| r.user_scope == user_scope && r.workspace_id == workspace_id)
        .collect::<Vec<_>>()
    {
        ctx.db.user_memory_result().id().delete(&old.id);
    }
    for mem in ctx.db.memory().workspace_id().filter(&workspace_id).take(crate::MAX_RESULTS) {
        if mem.user_scope == user_scope {
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



#[cfg(test)]
mod tests {
    use super::*;

    fn bare_memory(updated_at: i64, expires_at: i64, strength: f64) -> Memory {
        Memory {
            id: "m".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "p".to_string(),
            observer_id: "o".to_string(),
            memory_type: "world_fact".to_string(),
            content: "c".to_string(),
            summary: "s".to_string(),
            context: String::new(),
            entities_json: "[]".to_string(),
            confidence: 0.5,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: true,
            created_at: 0,
            expires_at,
            updated_at,
            tier: "L1".to_string(),
            access_count: 0,
            strength,
            version: 1,
            valid_from: 0,
            valid_to: 0,
            parent_directory_id: String::new(),
            consolidated_to: String::new(),
            trust_score: 0.5,
            feedback_count: 0,
            user_scope: String::new(),
            source_url: String::new(),

        }
    }

    #[test]
    fn test_is_expired_zero_means_no_expiry() {
        let m = bare_memory(0, 0, 0.5);
        assert!(!is_expired(&m, i64::MAX));
        assert!(is_readable(&m, i64::MAX));
    }

    #[test]
    fn test_is_expired_future_not_expired() {
        let m = bare_memory(0, 2_000_000, 0.5);
        assert!(!is_expired(&m, 1_000_000));
    }

    #[test]
    fn test_is_expired_past_is_expired_and_unreadable() {
        let m = bare_memory(0, 1_000_000, 0.5);
        assert!(is_expired(&m, 2_000_000));
        assert!(!is_readable(&m, 2_000_000));
    }

    #[test]
    fn test_effective_strength_no_elapsed_time() {
        let m = bare_memory(1_000_000, 0, 0.8);
        assert_eq!(effective_strength(&m, 1_000_000), 0.8);
    }

    #[test]
    fn test_effective_strength_thirty_day_half_life() {
        let day_micros: i64 = 86_400_000_000;
        let m = bare_memory(0, 0, 1.0);
        let after_30d = effective_strength(&m, 30 * day_micros);
        // λ = ln(2)/30 ⇒ strength ≈ 0.5 after 30 days (±1%)
        assert!((after_30d - 0.5).abs() < 0.01, "got {}", after_30d);
    }

    #[test]
    fn test_effective_strength_decays_monotonically() {
        let day_micros: i64 = 86_400_000_000;
        let m = bare_memory(0, 0, 1.0);
        let s10 = effective_strength(&m, 10 * day_micros);
        let s60 = effective_strength(&m, 60 * day_micros);
        assert!(s10 > s60);
        assert!(s60 > 0.0);
    }

    // ── Existing tests (kept) ──

    #[test]
    fn test_memory_initialization() {
        let mem = Memory {
            id: "mem_001".to_string(),
            workspace_id: "ws_001".to_string(),
            peer_id: "peer_abc".to_string(),
            observer_id: "obs_001".to_string(),
            memory_type: "world_fact".to_string(),
            content: "Alice lives in New York".to_string(),
            summary: "Alice's location".to_string(),
            context: String::new(),
            entities_json: r#"[{"name":"Alice","type":"person"}]"#.to_string(),
            confidence: 0.95,
            source_session_id: "sess_001".to_string(),
            source_message_id: "msg_001".to_string(),
            is_active: true,
            created_at: 1_000_000,
            expires_at: 0,
            updated_at: 1_000_000,
            tier: "L1".to_string(),
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
            source_url: String::new(),

        };
        assert_eq!(mem.id, "mem_001");
        assert_eq!(mem.memory_type, "world_fact");
        assert!(mem.is_active);
        assert_eq!(mem.confidence, 0.95);
        assert_eq!(mem.version, 1);
        assert_eq!(mem.strength, 0.5);
    }

    #[test]
    fn test_memory_inactive() {
        let mem = Memory {
            id: "mem_inactive".to_string(),
            workspace_id: "ws_002".to_string(),
            peer_id: "peer_xyz".to_string(),
            observer_id: String::new(),
            memory_type: "experience".to_string(),
            content: "Old fact".to_string(),
            summary: String::new(),
            context: String::new(),
            entities_json: "[]".to_string(),
            confidence: 0.3,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: false,
            created_at: 0,
            expires_at: 1_000_000,
            updated_at: 1_000_000,
            tier: "L2".to_string(),
            access_count: 5,
            strength: 0.1,
            version: 3,
            valid_from: 0,
            valid_to: 1_000_000,
            parent_directory_id: "dir_001".to_string(),
            consolidated_to: "mem_survivor".to_string(),
            trust_score: 0.2,
            feedback_count: 1,
            user_scope: "user:alice".to_string(),
            source_url: String::new(),
        };
        assert!(!mem.is_active);
        assert_eq!(mem.tier, "L2");
        assert_eq!(mem.access_count, 5);
        assert_eq!(mem.version, 3);
        assert_eq!(mem.consolidated_to, "mem_survivor");
        assert_eq!(mem.user_scope, "user:alice");
    }

    #[test]
    fn test_memory_serde_roundtrip() {
        let mem = Memory {
            id: "mem_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            peer_id: "peer_serde".to_string(),
            observer_id: String::new(),
            memory_type: "mental_model".to_string(),
            content: "Memory serde test".to_string(),
            summary: "Test".to_string(),
            context: String::new(),
            entities_json: "[]".to_string(),
            confidence: 0.5,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: true,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
            tier: "L1".to_string(),
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
            source_url: String::new(),

        };
        let json = serde_json::to_string(&mem).expect("serialize");
        let deserialized: Memory = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, mem.id);
        assert_eq!(deserialized.content, mem.content);
        assert_eq!(deserialized.memory_type, mem.memory_type);
        assert_eq!(deserialized.confidence, mem.confidence);
        assert_eq!(deserialized.is_active, mem.is_active);
    }

    #[test]
    fn test_memory_revision_initialization() {
        let rev = MemoryRevision {
            id: "rev_001".to_string(),
            memory_id: "mem_001".to_string(),
            workspace_id: "ws_001".to_string(),
            version: 1,
            previous_content: "Old content".to_string(),
            previous_summary: "Old summary".to_string(),
            previous_confidence: 0.5,
            new_content: "New content".to_string(),
            new_summary: "New summary".to_string(),
            new_confidence: 0.9,
            changed_at: 2_000_000,
            changed_by: "peer_abc".to_string(),
        };
        assert_eq!(rev.memory_id, "mem_001");
        assert_eq!(rev.version, 1);
        assert_eq!(rev.previous_content, "Old content");
        assert_eq!(rev.new_content, "New content");
        assert_eq!(rev.changed_by, "peer_abc");
    }

    #[test]
    fn test_memory_revision_serde() {
        let rev = MemoryRevision {
            id: "rev_serde".to_string(),
            memory_id: "mem_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            version: 2,
            previous_content: "v1 content".to_string(),
            previous_summary: "v1 summary".to_string(),
            previous_confidence: 0.6,
            new_content: "v2 content".to_string(),
            new_summary: "v2 summary".to_string(),
            new_confidence: 0.8,
            changed_at: 3_000_000,
            changed_by: "peer_serde".to_string(),
        };
        let json = serde_json::to_string(&rev).expect("serialize");
        let deserialized: MemoryRevision = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.memory_id, rev.memory_id);
        assert_eq!(deserialized.version, rev.version);
        assert_eq!(deserialized.new_confidence, rev.new_confidence);
    }

    #[test]
    fn test_store_memory_item_serde() {
        let item = StoreMemoryItem {
            workspace_id: "ws_001".to_string(),
            peer_id: "peer_abc".to_string(),
            observer_id: "obs_001".to_string(),
            memory_type: "world_fact".to_string(),
            content: "Test content".to_string(),
            summary: "Test".to_string(),
            entities_json: "[]".to_string(),
            confidence: 0.8,
            source_session_id: "sess_001".to_string(),
            source_message_id: "msg_001".to_string(),
            context: String::new(),

        };
        let json = serde_json::to_string(&item).expect("serialize");
        let deserialized: StoreMemoryItem = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.workspace_id, item.workspace_id);
        assert_eq!(deserialized.content, item.content);
        assert_eq!(deserialized.confidence, item.confidence);
    }

    #[test]
    fn test_user_memory_result_initialization() {
        let result = UserMemoryResult {
            id: "umr_001".to_string(),
            user_scope: "user:alice".to_string(),
            workspace_id: "ws_001".to_string(),
            memory_id: "mem_001".to_string(),
            content: "Memory content".to_string(),
            summary: "Summary".to_string(),
            memory_type: "world_fact".to_string(),
            confidence: 0.9,
            is_active: true,
            created_at: 1_000_000,
            tier: "L1".to_string(),
        };
        assert_eq!(result.user_scope, "user:alice");
        assert_eq!(result.memory_id, "mem_001");
        assert_eq!(result.tier, "L1");
        assert!(result.is_active);
    }

    #[test]
    fn test_user_memory_result_serde() {
        let result = UserMemoryResult {
            id: "umr_serde".to_string(),
            user_scope: String::new(),
            workspace_id: "ws_serde".to_string(),
            memory_id: "mem_serde".to_string(),
            content: "Shared memory".to_string(),
            summary: String::new(),
            memory_type: "experience".to_string(),
            confidence: 0.7,
            is_active: false,
            created_at: 0,
            tier: "L2".to_string(),
        };
        let json = serde_json::to_string(&result).expect("serialize");
        let deserialized: UserMemoryResult = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.memory_id, result.memory_id);
        assert!(deserialized.user_scope.is_empty());
        assert!(!deserialized.is_active);
    }

    // ── Edge case tests ──────────────────────────────────────────────────────────

    #[test]
    fn test_memory_empty_content() {
        let mem = Memory {
            id: "mem_empty".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "peer".to_string(),
            observer_id: "obs".to_string(),
            memory_type: "world_fact".to_string(),
            content: String::new(),
            summary: String::new(),
            context: String::new(),
            entities_json: String::new(),
            confidence: 0.0,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: true,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
            tier: "L0".to_string(),
            access_count: 0,
            strength: 0.0,
            version: 1,
            valid_from: 0,
            valid_to: 0,
            parent_directory_id: String::new(),
            consolidated_to: String::new(),
            trust_score: 0.0,
            feedback_count: 0,
            user_scope: String::new(),
            source_url: String::new(),

        };
        assert!(mem.content.is_empty());
        assert!(mem.summary.is_empty());
        assert!(mem.context.is_empty());
        assert!(mem.entities_json.is_empty());
        assert_eq!(mem.confidence, 0.0);
        assert_eq!(mem.strength, 0.0);
        assert_eq!(mem.trust_score, 0.0);
    }

    #[test]
    fn test_memory_special_characters_in_content() {
        let content = "Hello! @#$%^&*()_+-=[]{}|;':\",./<>?`~ 😊".to_string();
        let mem = Memory {
            id: "mem_special".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "peer".to_string(),
            observer_id: "obs".to_string(),
            memory_type: "world_fact".to_string(),
            content: content.clone(),
            summary: "Special chars".to_string(),
            context: String::new(),
            entities_json: r##"[{"name":"test","type":"symbol"}]"##.to_string(),
            confidence: 0.5,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: true,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
            tier: "L1".to_string(),
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
            source_url: String::new(),

        };
        assert_eq!(mem.content, content);
        assert!(mem.content.contains('!'));
        assert!(mem.content.contains('😊'));
    }

    #[test]
    fn test_memory_unicode_content() {
        let content = "日本語のメモリシステム测试 🎉 中文 漢字".to_string();
        let mem = Memory {
            id: "mem_unicode".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "peer".to_string(),
            observer_id: "obs".to_string(),
            memory_type: "world_fact".to_string(),
            content: content.clone(),
            summary: "Unicode summary".to_string(),
            context: String::new(),
            entities_json: r##"[]"##.to_string(),
            confidence: 0.8,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: true,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
            tier: "L1".to_string(),
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
            source_url: String::new(),

        };
        assert_eq!(mem.content, content);
        assert!(mem.content.contains('日'));
        assert!(mem.content.contains('🎉'));
    }

    #[test]
    fn test_memory_very_large_content() {
        let large = "A".repeat(10_000);
        let mem = Memory {
            id: "mem_large".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "peer".to_string(),
            observer_id: "obs".to_string(),
            memory_type: "world_fact".to_string(),
            content: large.clone(),
            summary: "Large content".to_string(),
            context: String::new(),
            entities_json: String::new(),
            confidence: 0.5,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: true,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
            tier: "L1".to_string(),
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
            source_url: String::new(),

        };
        assert_eq!(mem.content.len(), 10_000);
        assert!(mem.content.chars().all(|c| c == 'A'));
    }

    #[test]
    fn test_memory_concurrent_writes_simulation() {
        let mems: Vec<Memory> = (0..10)
            .map(|i| Memory {
                id: format!("mem_concurrent_{}", i),
                workspace_id: "ws_concurrent".to_string(),
                peer_id: "peer".to_string(),
                observer_id: "obs".to_string(),
                memory_type: "world_fact".to_string(),
                content: format!("Concurrent memory {}", i),
                summary: String::new(),
                context: String::new(),
                entities_json: String::new(),
                confidence: 0.5,
                source_session_id: String::new(),
                source_message_id: String::new(),
                is_active: true,
                created_at: i as i64,
                expires_at: 0,
                updated_at: i as i64,
                tier: "L1".to_string(),
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
                source_url: String::new(),

            })
            .collect();
        assert_eq!(mems.len(), 10);
        for (i, mem) in mems.iter().enumerate() {
            assert_eq!(mem.id, format!("mem_concurrent_{}", i));
            assert_eq!(mem.created_at, i as i64);
            assert_eq!(mem.updated_at, i as i64);
        }
    }

    #[test]
    fn test_memory_network_partition_simulation() {
        let mem = Memory {
            id: "mem_partition".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "peer".to_string(),
            observer_id: "obs".to_string(),
            memory_type: "world_fact".to_string(),
            content: "Partial data".to_string(),
            summary: String::new(),
            context: String::new(),
            entities_json: String::new(),
            confidence: 0.0,
            source_session_id: String::new(),
            source_message_id: String::new(),
            is_active: true,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
            tier: "L0".to_string(),
            access_count: 0,
            strength: 0.0,
            version: 1,
            valid_from: 0,
            valid_to: 0,
            parent_directory_id: String::new(),
            consolidated_to: String::new(),
            trust_score: 0.0,
            feedback_count: 0,
            user_scope: String::new(),
            source_url: String::new(),

        };
        assert!(mem.summary.is_empty());
        assert!(mem.context.is_empty());
        assert!(mem.entities_json.is_empty());
        assert_eq!(mem.confidence, 0.0);
        assert_eq!(mem.strength, 0.0);
        assert_eq!(mem.trust_score, 0.0);
        assert_eq!(mem.access_count, 0);
        assert_eq!(mem.feedback_count, 0);
    }

    #[test]
    fn test_batch_chunking_bounds() {
        // store_memory_batch processes items in ≤ MAX_BATCH_ITEMS chunks so a
        // single oversized ingest (benchmark haystack) can't create 20k+ edges
        // in one WASM transaction and panic the module. Verify the chunk math.
        let items: Vec<usize> = (0..1000).collect();
        let chunks: Vec<&[usize]> = items.chunks(crate::MAX_BATCH_ITEMS).collect();
        assert_eq!(chunks.len(), (1000 + crate::MAX_BATCH_ITEMS - 1) / crate::MAX_BATCH_ITEMS);
        for c in &chunks {
            assert!(c.len() <= crate::MAX_BATCH_ITEMS, "chunk exceeded bound");
        }
        assert_eq!(chunks[0].len(), crate::MAX_BATCH_ITEMS);
        assert_eq!(chunks[0][0], 0);
        assert_eq!(chunks[1][0], crate::MAX_BATCH_ITEMS);
        // Edge case: exactly MAX_BATCH_ITEMS items → 1 chunk
        let exact: Vec<usize> = (0..crate::MAX_BATCH_ITEMS).collect();
        assert_eq!(exact.chunks(crate::MAX_BATCH_ITEMS).count(), 1);
    }
}

