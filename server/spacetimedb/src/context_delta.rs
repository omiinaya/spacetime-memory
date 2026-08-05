use spacetimedb::*;
use crate::auth::require_auth;
use crate::trace_span;
use crate::tracing::TracingSpanKind;
use crate::workspace::check_space_access;

use crate::context_compression::context_pack;
use crate::context_compression::ContextPack;
use crate::memory::memory;
use crate::memory::Memory;
use crate::{now_micros, uuid_v7};

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

/// A delta context pack for token-budgeted retrieval.
/// Agents request a compact context pack within a token budget, and on
/// subsequent requests only delta (changed) context is returned.
#[table(accessor = delta_pack)]
#[derive(Debug, Clone)]
pub struct DeltaPack {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The previous full ContextPack that this delta applies to
    #[index(btree)]
    pub previous_context_pack_id: String,
    pub query_hash: String,
    /// JSON array of memory IDs that have changed (content/summary/etc.)
    pub changed_memory_ids_json: String,
    /// JSON array of memory IDs that have been removed (deactivated)
    pub removed_memory_ids_json: String,
    /// JSON array of full memory objects for new/changed memories
    pub new_memories_json: String,
    pub estimated_tokens: u32,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Compute a simple hex hash for a query string (cache-key).
fn compute_query_hash(text: &str) -> String {
    let mut hasher = DefaultHasher::new();
    text.hash(&mut hasher);
    format!("{:x}", hasher.finish())
}

/// Rough token estimation: content bytes / 4 ≈ tokens.
fn estimate_tokens(content: &str) -> u32 {
    (content.len() / 4).max(1) as u32
}

/// Tier sort key: L0=0, L1=1, L2=2, anything else=3.
fn tier_ord(tier: &str) -> u8 {
    match tier {
        "L0" => 0,
        "L1" => 1,
        "L2" => 2,
        _ => 3,
    }
}

/// Build a serialisable JSON value representing a memory for packing.
fn memory_to_entry(mem: &Memory) -> serde_json::Value {
    serde_json::json!({
        "id": mem.id,
        "content": mem.content,
        "summary": mem.summary,
        "memory_type": mem.memory_type,
        "confidence": mem.confidence,
        "tier": mem.tier,
        "strength": mem.strength,
        "access_count": mem.access_count,
        "created_at": mem.created_at,
        "updated_at": mem.updated_at,
    })
}

/// Filter active memories for a workspace, sort by priority, pack up to
/// `token_budget`, and return (json_string, token_count, filtered_count).
fn build_full_pack(
    ctx: &ReducerContext,
    workspace_id: &str,
    peer_id: &str,
    token_budget: u32,
) -> (String, u32, usize) {
    // Collect all active memories for this workspace (optionally filtered by peer)
    let mut memories: Vec<Memory> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|m| {
            m.workspace_id == workspace_id
                && m.is_active
                && (peer_id.is_empty() || m.peer_id == peer_id)
        })
        .collect();

    // Sort by tier (L0 > L1 > L2), then confidence desc, then strength desc
    memories.sort_by(|a, b| {
        tier_ord(&a.tier)
            .cmp(&tier_ord(&b.tier))
            .then_with(|| {
                b.confidence
                    .partial_cmp(&a.confidence)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                b.strength
                    .partial_cmp(&a.strength)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    let mut pack_entries: Vec<serde_json::Value> = Vec::new();
    let mut total_tokens: u32 = 0;

    for mem in &memories {
        let mem_tokens = estimate_tokens(&mem.content);
        // Stop if adding this memory would exceed budget and we already have at least one
        if total_tokens + mem_tokens > token_budget && !pack_entries.is_empty() {
            break;
        }
        total_tokens += mem_tokens;
        pack_entries.push(memory_to_entry(mem));
    }

    let pack_json = serde_json::json!({
        "memories": pack_entries,
        "token_count": total_tokens,
        "total_memory_count": memories.len(),
    })
    .to_string();

    (pack_json, total_tokens, memories.len())
}

/// Upsert (replace) a ContextPack for a given workspace + query_hash and
/// return the inserted pack's id.
fn upsert_context_pack(
    ctx: &ReducerContext,
    workspace_id: String,
    query_hash: String,
    pack_json: String,
    token_count: u32,
    created_at: i64,
) -> String {
    // Remove any existing pack with same workspace + query_hash
    let existing: Vec<_> = ctx
        .db
        .context_pack()
        .iter().take(crate::MAX_RESULTS)
        .filter(|p| p.workspace_id == workspace_id && p.query_hash == query_hash)
        .collect();
    for p in existing {
        ctx.db.context_pack().id().delete(&p.id);
    }

    let id = uuid_v7(ctx);
    let pack = ContextPack {
        id: id.clone(),
        workspace_id,
        query_hash,
        pack_json,
        token_count,
        created_at,
    };
    ctx.db.context_pack().insert(pack);
    id
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

/// Generate a context pack (full or delta) within a token budget.
///
/// * `workspace_id` - The workspace scope.
/// * `query_text` - Natural-language query used to compute a cache-key hash.
/// * `token_budget` - Maximum estimated tokens for the pack.
/// * `peer_id` - Optional peer filter for personalisation (empty = all peers).
/// * `previous_pack_id` - If set, generate a delta against this previous
///   `ContextPack`.  If empty, generate a full pack.
#[reducer]
pub fn generate_context_pack(
    ctx: &ReducerContext,
    workspace_id: String,
    query_text: String,
    token_budget: u32,
    peer_id: String,
    previous_pack_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "generate_context_pack", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;
    let now = now_micros(ctx);
    let query_hash = compute_query_hash(&query_text);

    if previous_pack_id.is_empty() {
        // -------------------------------------------------------------------
        // FULL PACK MODE – gather memories and store a single ContextPack
        // -------------------------------------------------------------------
        let (pack_json, token_count, _) =
            build_full_pack(ctx, &workspace_id, &peer_id, token_budget);

        upsert_context_pack(ctx, workspace_id.clone(), query_hash, pack_json, token_count, now);

        Ok(())
    } else {
        // -------------------------------------------------------------------
        // DELTA PACK MODE – compare current state with previous ContextPack
        // -------------------------------------------------------------------

        // 1. Locate the previous ContextPack to get its created_at timestamp
        let prev_pack = ctx
            .db
            .context_pack()
            .id()
            .find(&previous_pack_id)
            .ok_or_else(|| format!("Previous context pack '{}' not found", previous_pack_id))?;

        let prev_created_at = prev_pack.created_at;

        // 2. Iterate all memories in workspace; detect changes since prev_pack
        let all_memories: Vec<Memory> = ctx
            .db
            .memory()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|m| {
                m.workspace_id == workspace_id && (peer_id.is_empty() || m.peer_id == peer_id)
            })
            .collect();

        let mut changed_ids: Vec<String> = Vec::new();
        let mut removed_ids: Vec<String> = Vec::new();
        let mut new_entries: Vec<serde_json::Value> = Vec::new();
        let mut delta_tokens: u32 = 0;

        for mem in &all_memories {
            if mem.updated_at > prev_created_at {
                if mem.is_active {
                    // Changed (or newly created) active memory
                    changed_ids.push(mem.id.clone());
                    let entry = memory_to_entry(mem);
                    new_entries.push(entry);
                    delta_tokens += estimate_tokens(&mem.content);
                } else {
                    // Recently deactivated → removed
                    removed_ids.push(mem.id.clone());
                    let entry = serde_json::json!({
                        "id": mem.id,
                        "is_active": false,
                        "updated_at": mem.updated_at,
                    });
                    new_entries.push(entry);
                }
            }
        }

        let changed_json =
            serde_json::to_string(&changed_ids).unwrap_or_else(|_| String::from("[]"));
        let removed_json =
            serde_json::to_string(&removed_ids).unwrap_or_else(|_| String::from("[]"));
        let new_mem_json =
            serde_json::to_string(&new_entries).unwrap_or_else(|_| String::from("[]"));

        // 3. Insert the DeltaPack
        let delta_id = uuid_v7(ctx);
        let delta = DeltaPack {
            id: delta_id,
            workspace_id: workspace_id.clone(),
            previous_context_pack_id: previous_pack_id,
            query_hash: query_hash.clone(),
            changed_memory_ids_json: changed_json,
            removed_memory_ids_json: removed_json,
            new_memories_json: new_mem_json,
            estimated_tokens: delta_tokens,
            created_at: now,
        };
        ctx.db.delta_pack().insert(delta);

        // 4. Also create a new full ContextPack representing the current state
        //    so the *next* delta can be computed against it.
        let (pack_json, token_count, _) =
            build_full_pack(ctx, &workspace_id, &peer_id, token_budget);

        upsert_context_pack(ctx, workspace_id.clone(), query_hash, pack_json, token_count, now);

        Ok(())
    }
    })
}

/// Retrieve a delta pack by its `previous_context_pack_id`.
///
/// Returns an error if no delta exists for the given previous pack id.
/// On success the delta pack is accessible via the client's subscription.
#[reducer]
pub fn get_delta(ctx: &ReducerContext, previous_pack_id: String) -> Result<(), String> {
    trace_span!(ctx, "get_delta", TracingSpanKind::Read, "", {
    let _account = require_auth(ctx)?;
    let delta = ctx
        .db
        .delta_pack()
        .previous_context_pack_id().filter(&previous_pack_id)
        .take(1)
        .next()
        .ok_or_else(|| {
            format!(
                "Delta pack for previous pack '{}' not found",
                previous_pack_id
            )
        })?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &delta.workspace_id, &caller, "viewer")?;

    // The delta pack is now materialised; the client can read its fields
    // from the subscription state.
    let _ = delta;
    Ok(())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_query_hash_deterministic() {
        let h1 = compute_query_hash("hello world");
        let h2 = compute_query_hash("hello world");
        assert_eq!(h1, h2);
    }

    #[test]
    fn test_compute_query_hash_different() {
        let h1 = compute_query_hash("hello");
        let h2 = compute_query_hash("world");
        assert_ne!(h1, h2);
    }

    #[test]
    fn test_estimate_tokens_short() {
        assert_eq!(estimate_tokens("hi"), 1);
    }

    #[test]
    fn test_estimate_tokens_typical() {
        // 100 bytes / 4 = 25 tokens
        let text = "a".repeat(100);
        assert_eq!(estimate_tokens(&text), 25);
    }

    #[test]
    fn test_tier_ord_levels() {
        assert_eq!(tier_ord("L0"), 0);
        assert_eq!(tier_ord("L1"), 1);
        assert_eq!(tier_ord("L2"), 2);
        assert_eq!(tier_ord("L3"), 3);
        assert_eq!(tier_ord("unknown"), 3);
        assert_eq!(tier_ord(""), 3);
    }


    // ── memory_to_entry ──────────────────────────────────────────────────────────

    fn make_test_memory() -> Memory {
        Memory {
            id: "mem-1".to_string(),
            workspace_id: "ws-1".to_string(),
            peer_id: "peer-1".to_string(),
            observer_id: "obs-1".to_string(),
            memory_type: "experience".to_string(),
            content: "Test memory content".to_string(),
            summary: "Test summary".to_string(),
            context: "test context".to_string(),
            entities_json: "[]".to_string(),
            confidence: 0.85,
            source_session_id: "sess-1".to_string(),
            source_message_id: "msg-1".to_string(),
            is_active: true,
            created_at: 1000000,
            expires_at: 0,
            updated_at: 2000000,
            tier: "L1".to_string(),
            access_count: 5,
            strength: 0.75,
            version: 2,
            valid_from: 0,
            valid_to: 0,
            parent_directory_id: "".to_string(),
            consolidated_to: "".to_string(),
            trust_score: 0.9,
            feedback_count: 3,
            user_scope: "".to_string(),
            source_url: String::new(),
        }
    }

    #[test]
    fn test_memory_to_entry_basic() {
        let mem = make_test_memory();
        let entry = memory_to_entry(&mem);
        assert_eq!(entry["id"], "mem-1");
        assert_eq!(entry["content"], "Test memory content");
        assert_eq!(entry["summary"], "Test summary");
        assert_eq!(entry["memory_type"], "experience");
        assert_eq!(entry["tier"], "L1");
    }

    #[test]
    fn test_memory_to_entry_numeric_fields() {
        let mem = make_test_memory();
        let entry = memory_to_entry(&mem);
        assert!((entry["confidence"].as_f64().unwrap() - 0.85).abs() < 1e-6);
        assert!((entry["strength"].as_f64().unwrap() - 0.75).abs() < 1e-6);
        assert_eq!(entry["access_count"], 5);
        assert_eq!(entry["created_at"], 1000000);
        assert_eq!(entry["updated_at"], 2000000);
    }

    #[test]
    fn test_memory_to_entry_serializable() {
        let mem = Memory {
            id: "mem-2".to_string(),
            workspace_id: "ws-2".to_string(),
            peer_id: "peer-2".to_string(),
            observer_id: "obs-2".to_string(),
            memory_type: "world_fact".to_string(),
            content: "Earth is round".to_string(),
            summary: "".to_string(),
            context: "".to_string(),
            entities_json: "[]".to_string(),
            confidence: 0.99,
            source_session_id: "sess-2".to_string(),
            source_message_id: "msg-2".to_string(),
            is_active: true,
            created_at: 3000000,
            expires_at: 0,
            updated_at: 4000000,
            tier: "L0".to_string(),
            access_count: 10,
            strength: 0.95,
            version: 1,
            valid_from: 0,
            valid_to: 0,
            parent_directory_id: "".to_string(),
            consolidated_to: "".to_string(),
            trust_score: 0.8,
            feedback_count: 5,
            user_scope: "".to_string(),
            source_url: String::new(),
        };
        let entry = memory_to_entry(&mem);
        let json_str = serde_json::to_string(&entry).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&json_str).unwrap();
        assert_eq!(parsed["id"], "mem-2");
        assert_eq!(parsed["content"], "Earth is round");
        assert_eq!(parsed["confidence"], 0.99);
    }

    #[test]
    fn test_memory_to_entry_tier_values() {
        let mut mem = make_test_memory();
        
        mem.tier = "L0".to_string();
        let entry = memory_to_entry(&mem);
        assert_eq!(entry["tier"], "L0");
        
        mem.tier = "L2".to_string();
        let entry = memory_to_entry(&mem);
        assert_eq!(entry["tier"], "L2");
        
        mem.tier = "archival".to_string();
        let entry = memory_to_entry(&mem);
        assert_eq!(entry["tier"], "archival");
    }

    #[test]
    fn test_memory_to_entry_empty_strings() {
        let mut mem = make_test_memory();
        mem.content = "".to_string();
        mem.summary = "".to_string();
        
        let entry = memory_to_entry(&mem);
        assert_eq!(entry["content"], "");
        assert_eq!(entry["summary"], "");
    }

    #[test]
    fn test_memory_to_entry_all_fields_present() {
        let mem = make_test_memory();
        let entry = memory_to_entry(&mem);
        
        assert!(entry.get("id").is_some());
        assert!(entry.get("content").is_some());
        assert!(entry.get("summary").is_some());
        assert!(entry.get("memory_type").is_some());
        assert!(entry.get("confidence").is_some());
        assert!(entry.get("tier").is_some());
        assert!(entry.get("strength").is_some());
        assert!(entry.get("access_count").is_some());
        assert!(entry.get("created_at").is_some());
        assert!(entry.get("updated_at").is_some());
    }
}
