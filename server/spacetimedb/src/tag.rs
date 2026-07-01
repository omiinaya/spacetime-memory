use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};

/// A tag that can be attached to memories and other entities.
#[table(accessor = tag)]
#[derive(Debug, Clone, serde::Serialize)]
pub struct Tag {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    pub color: String,
    pub created_at: i64,
}

/// Associates a tag with a memory.
/// Both fields together act as the logical composite key.
#[table(accessor = memory_tag)]
#[derive(Debug, Clone)]
pub struct MemoryTag {
    pub memory_id: String,
    pub tag_id: String,
}

// ---------------------------------------------------------------------------
// Tag reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_tag(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    color: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let tag = Tag {
        id: id.clone(),
        workspace_id,
        name,
        color,
        created_at: now,
    };

    ctx.db.tag().insert(tag);
    Ok(())
}

#[reducer]
pub fn tag_memory(
    ctx: &ReducerContext,
    memory_id: String,
    tag_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let mt = MemoryTag {
        memory_id,
        tag_id,
    };

    ctx.db.memory_tag().insert(mt);
    Ok(())
}

#[reducer]
pub fn untag_memory(
    ctx: &ReducerContext,
    memory_id: String,
    tag_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Delete matching rows (table has no PK, so iterate and delete each row)
    let to_delete: Vec<_> = ctx
        .db
        .memory_tag()
        .iter().take(crate::MAX_RESULTS)
        .filter(|mt| mt.memory_id == memory_id && mt.tag_id == tag_id)
        .collect();
    if to_delete.is_empty() {
        return Err(format!(
            "Tag association not found for memory '{}' with tag '{}'",
            memory_id, tag_id
        ));
    }
    for mt in to_delete {
        ctx.db.memory_tag().delete(mt);
    }

    Ok(())
}

#[reducer]
pub fn list_tags(
    ctx: &ReducerContext,
    _workspace_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Note: list_tags was previously a value-returning reducer. STDB v2.6
    // doesn't support reducer return values. The SDK now queries the `tag`
    // table directly via `_query("tag", workspace_id=ws, columns=[...])`.
    // This reducer still exists for auth-gated identity verification.
    Ok(())
}

/// Batch-attach a tag to multiple memories in a single reducer call.
/// Accepts a tag_id and a JSON array of memory ID strings.
/// Idempotent per-memory (skips already-tagged memories — no-op).
#[reducer]
pub fn batch_tag_memories(ctx: &ReducerContext, tag_id: String, memory_ids_json: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let memory_ids: Vec<String> = serde_json::from_str(&memory_ids_json)
        .map_err(|e| format!("Invalid batch-tag memory IDs JSON: {}", e))?;

    // Build a set of existing taggings to avoid duplicates
    let existing: std::collections::HashSet<(String, String)> = ctx
        .db
        .memory_tag()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|mt| mt.tag_id == tag_id)
        .map(|mt| (mt.memory_id.clone(), mt.tag_id.clone()))
        .collect();

    for mid in &memory_ids {
        if existing.contains(&(mid.clone(), tag_id.clone())) {
            continue; // Idempotent — skip already-tagged
        }
        let mt = MemoryTag {
            memory_id: mid.clone(),
            tag_id: tag_id.clone(),
        };
        ctx.db.memory_tag().insert(mt);
    }

    Ok(())
}

/// Batch-remove a tag from multiple memories in a single reducer call.
/// Accepts a tag_id and a JSON array of memory ID strings.
/// Idempotent per-memory (skips missing associations).
#[reducer]
pub fn batch_untag_memories(ctx: &ReducerContext, tag_id: String, memory_ids_json: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let memory_ids: Vec<String> = serde_json::from_str(&memory_ids_json)
        .map_err(|e| format!("Invalid batch-untag memory IDs JSON: {}", e))?;

    // Collect rows to delete
    let to_delete: Vec<_> = ctx
        .db
        .memory_tag()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|mt| mt.tag_id == tag_id && memory_ids.contains(&mt.memory_id))
        .collect();

    for mt in to_delete {
        ctx.db.memory_tag().delete(mt);
    }

    Ok(())
}

#[reducer]
pub fn delete_tag(
    ctx: &ReducerContext,
    tag_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Find the tag and delete it
    let tag = ctx.db.tag().id().find(&tag_id);
    match tag {
        Some(t) => {
            ctx.db.tag().delete(t);
            // Also delete all associations
            let to_delete: Vec<_> = ctx
                .db
                .memory_tag()
                .iter().take(crate::MAX_RESULTS)
                .filter(|mt| mt.tag_id == tag_id)
                .collect();
            for mt in to_delete {
                ctx.db.memory_tag().delete(mt);
            }
            Ok(())
        }
        None => Err(format!("Tag not found: {}", tag_id)),
    }
}
