use spacetimedb::*;

use crate::memory::memory;
use crate::{now_micros, uuid_v4};

/// Tracks consolidation operations (dedup, rollup, decay, version_merge).
#[table(accessor = consolidation_log, public)]
#[derive(Debug, Clone)]
pub struct ConsolidationLog {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// "dedup" | "rollup" | "decay" | "version_merge"
    pub consolidation_type: String,
    /// JSON array of source memory IDs
    pub source_memory_ids: String,
    /// Target memory id (empty if not consolidated into another)
    pub target_memory_id: String,
    pub created_at: i64,
}

/// Merge several source memories into a single new memory.
/// Sources are deactivated and a `ConsolidationLog` entry is created.
#[reducer]
pub fn consolidate_memories(
    ctx: &ReducerContext,
    workspace_id: String,
    source_ids_json: String,
    target_content: String,
    target_summary: String,
) -> Result<(), String> {
    let now = now_micros();
    let id = uuid_v4();

    // Parse source IDs from JSON array
    let source_ids: Vec<String> = serde_json::from_str(&source_ids_json)
        .map_err(|e| format!("Invalid source_ids JSON: {}", e))?;

    // Create the consolidated memory
    let mem = crate::memory::Memory {
        id: id.clone(),
        workspace_id: workspace_id.clone(),
        // Consolidated — no single peer/observer
        peer_id: String::new(),
        observer_id: String::new(),
        memory_type: String::from("consolidated"),
        content: target_content,
        summary: target_summary,
        entities_json: String::from("[]"),
        confidence: 1.0,
        source_session_id: String::new(),
        source_message_id: String::new(),
        is_active: true,
        created_at: now,
        expires_at: 0,
        updated_at: now,
        tier: String::from("L1"),
        access_count: 0,
        strength: 0.7,
        version: 1,
        valid_from: 0,
        parent_directory_id: String::new(),
        consolidated_to: String::new(),
    };
    ctx.db.memory().insert(mem);

    // Deactivate each source memory and point it at the new one
    for sid in &source_ids {
        if let Some(mut src) = ctx.db.memory().id().find(sid) {
            src.is_active = false;
            src.consolidated_to = id.clone();
            src.updated_at = now;
            ctx.db.memory().id().update(src);
        }
    }

    // Log the consolidation
    let log = ConsolidationLog {
        id: uuid_v4(),
        workspace_id,
        consolidation_type: String::from("rollup"),
        source_memory_ids: source_ids_json,
        target_memory_id: id,
        created_at: now,
    };
    ctx.db.consolidation_log().insert(log);

    Ok(())
}

/// Deactivate memories whose strength is below the threshold
/// and have not been updated recently.
#[reducer]
pub fn decay_weak_memories(
    ctx: &ReducerContext,
    workspace_id: String,
    strength_threshold: f64,
) -> Result<(), String> {
    let now = now_micros();
    let stale_cutoff = now - 7 * 86_400_000_000; // 7 days ago in micros

    let weak: Vec<_> = ctx
        .db
        .memory()
        .iter()
        .filter(|m| {
            m.workspace_id == workspace_id
                && m.is_active
                && m.strength < strength_threshold
                && m.updated_at < stale_cutoff
        })
        .collect();

    let source_ids: Vec<String> = weak.iter().map(|m| m.id.clone()).collect();

    for mut mem in weak {
        mem.is_active = false;
        mem.updated_at = now;
        ctx.db.memory().id().update(mem);
    }

    // Log the decay operation
    if !source_ids.is_empty() {
        let ids_json = serde_json::to_string(&source_ids)
            .unwrap_or_else(|_| "[]".to_string());
        let log = ConsolidationLog {
            id: uuid_v4(),
            workspace_id,
            consolidation_type: String::from("decay"),
            source_memory_ids: ids_json,
            target_memory_id: String::new(),
            created_at: now,
        };
        ctx.db.consolidation_log().insert(log);
    }

    Ok(())
}
