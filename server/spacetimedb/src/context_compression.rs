use spacetimedb::*;

use crate::memory::memory;
use crate::{now_micros, uuid_v4};

/// A cached compressed context pack (RetainDB-style).
/// Allows cache-lookup via `query_hash` so repeated queries reuse
/// previously compressed context.
#[table(accessor = context_pack, public)]
#[derive(Debug, Clone)]
pub struct ContextPack {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Hash of the query for cache lookups
    pub query_hash: String,
    /// The compressed context JSON
    pub pack_json: String,
    /// Approximate token count
    pub token_count: u32,
    pub created_at: i64,
}

/// Store (or overwrite) a cached context pack for a workspace + query_hash.
#[reducer]
pub fn store_context_pack(
    ctx: &ReducerContext,
    workspace_id: String,
    query_hash: String,
    pack_json: String,
    token_count: u32,
) -> Result<(), String> {
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

    // Remove any existing pack with the same workspace_id + query_hash
    let existing: Vec<_> = ctx
        .db
        .context_pack()
        .iter()
        .filter(|p| p.workspace_id == workspace_id && p.query_hash == query_hash)
        .collect();
    for pack in existing {
        ctx.db.context_pack().id().delete(&pack.id);
    }

    let pack = ContextPack {
        id,
        workspace_id,
        query_hash,
        pack_json,
        token_count,
        created_at: now,
    };
    ctx.db.context_pack().insert(pack);
    Ok(())
}

/// Reinforce a memory: increment access count and bump strength.
#[reducer]
pub fn reinforce_memory(ctx: &ReducerContext, memory_id: String) -> Result<(), String> {
    let mut mem = ctx
        .db
        .memory()
        .id()
        .find(&memory_id)
        .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;

    mem.access_count = mem.access_count.saturating_add(1);
    mem.strength = (mem.strength + 0.05).min(1.0);
    mem.updated_at = now_micros(ctx);

    // Tier escalation based on strength thresholds
    if mem.strength >= 0.8 && mem.tier != "L0" {
        mem.tier = "L0".to_string();
    } else if mem.strength >= 0.5 && mem.tier == "L2" {
        mem.tier = "L1".to_string();
    } else if mem.strength < 0.2 && mem.tier != "L2" {
        mem.tier = "L2".to_string();
    }

    ctx.db.memory().id().update(mem);
    Ok(())
}

/// Change the tier of a memory.
#[reducer]
pub fn update_memory_tier(ctx: &ReducerContext, memory_id: String, tier: String) -> Result<(), String> {
    // Validate tier
    if tier != "L0" && tier != "L1" && tier != "L2" {
        return Err(format!("Invalid tier '{}'. Must be L0, L1, or L2", tier));
    }

    let mut mem = ctx
        .db
        .memory()
        .id()
        .find(&memory_id)
        .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;

    mem.tier = tier;
    mem.updated_at = now_micros(ctx);

    ctx.db.memory().id().update(mem);
    Ok(())
}
