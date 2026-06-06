use spacetimedb::*;

use crate::{uuid_v4, now_micros};
use crate::hybrid_query::{cosine_similarity, parse_embedding_json};
use crate::memory::memory;
use crate::retrieval::search_index;
use crate::workspace::workspace;

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
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

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
        trust_score: 0.5,
        feedback_count: 0,
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
        id: uuid_v4(ctx),
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
    let now = now_micros(ctx);
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
            id: uuid_v4(ctx),
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

// ── Auto-Dedup ─────────────────────────────────────────────────────

/// Levenshtein edit distance between two strings (character-level).
fn edit_distance(a: &str, b: &str) -> usize {
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let m = a_chars.len();
    let n = b_chars.len();
    if m == 0 {
        return n;
    }
    if n == 0 {
        return m;
    }

    let mut prev: Vec<usize> = (0..=n).collect();
    let mut curr: Vec<usize> = vec![0; n + 1];

    for i in 1..=m {
        curr[0] = i;
        for j in 1..=n {
            let cost = if a_chars[i - 1] == b_chars[j - 1] { 0 } else { 1 };
            curr[j] = std::cmp::min(
                std::cmp::min(prev[j] + 1, curr[j - 1] + 1),
                prev[j - 1] + cost,
            );
        }
        std::mem::swap(&mut prev, &mut curr);
    }

    prev[n]
}

/// Find and merge near-duplicate memories within a workspace.
///
/// Two memories are considered duplicates when both conditions hold:
///   1. Embedding cosine similarity >= 0.85
///   2. Character-level Levenshtein distance <= 30% of longer string
///
/// When a pair matches, the older memory is kept and reinforced; the
/// newer one is marked inactive and consolidated_to the older one.
#[reducer]
pub fn dedup_memories(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let now = now_micros(ctx);

    // Collect active memories with their embeddings
    #[allow(clippy::type_complexity)]
    let memories: Vec<(String, String, i64, Vec<f64>)> = ctx
        .db
        .memory()
        .iter()
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .map(|m| {
            let emb = ctx
                .db
                .search_index()
                .iter()
                .find(|si| si.entity_type == "memory" && si.entity_id == m.id)
                .map(|si| parse_embedding_json(&si.embedding_json))
                .unwrap_or_default();
            (m.id.clone(), m.content.clone(), m.created_at, emb)
        })
        .collect();

    if memories.len() < 2 {
        return Ok(());
    }

    for i in 0..memories.len() - 1 {
        for j in i + 1..memories.len() {
            let (id_a, content_a, created_a, emb_a) = &memories[i];
            let (id_b, content_b, created_b, emb_b) = &memories[j];

            // Both must have embeddings
            if emb_a.is_empty() || emb_b.is_empty() {
                continue;
            }

            let cos_sim = cosine_similarity(emb_a, emb_b);
            if cos_sim < 0.85 {
                continue;
            }

            let max_len = std::cmp::max(content_a.len(), content_b.len());
            if max_len == 0 {
                continue;
            }
            let dist = edit_distance(content_a, content_b);
            let norm_dist = dist as f64 / max_len as f64;
            if norm_dist > 0.30 {
                continue;
            }

            // Keep the older, deactivate the newer
            let (keep_id, remove_id) = if created_a < created_b {
                (id_a.clone(), id_b.clone())
            } else {
                (id_b.clone(), id_a.clone())
            };

            if let Some(mut mem) = ctx.db.memory().id().find(&remove_id) {
                mem.is_active = false;
                mem.consolidated_to = keep_id.clone();
                mem.updated_at = now;
                ctx.db.memory().id().update(mem);
            }

            if let Some(mut mem) = ctx.db.memory().id().find(&keep_id) {
                mem.access_count = mem.access_count.saturating_add(1);
                mem.updated_at = now;
                ctx.db.memory().id().update(mem);
            }
        }
    }

    Ok(())
}

// ── Scheduled Maintenance ──────────────────────────────────────────

/// Scheduler table for periodic maintenance tasks.
/// Inserted by `init` with recurring ScheduleAt durations.
#[table(accessor = maintenance_schedule, scheduled(run_maintenance), public)]
#[derive(Debug, Clone)]
pub struct MaintenanceSchedule {
    #[primary_key]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

/// Periodic maintenance: expire timed-out memories, decay weak ones.
/// Runs via SpacetimeDB scheduler (every 5 minutes, configured in `init`).
#[reducer]
pub fn run_maintenance(ctx: &ReducerContext, _arg: MaintenanceSchedule) -> Result<(), String> {
    _run_maintenance(ctx)
}

/// Manual maintenance trigger — callable from HTTP API (no scheduled arg needed).
#[reducer]
pub fn manual_maintenance(ctx: &ReducerContext) -> Result<(), String> {
    _run_maintenance(ctx)
}

fn _run_maintenance(ctx: &ReducerContext) -> Result<(), String> {
    let now = now_micros(ctx);

    // 1. Expire memories that have passed their expires_at
    let expired: Vec<_> = ctx
        .db
        .memory()
        .iter()
        .filter(|m| m.expires_at > 0 && m.expires_at < now)
        .collect();
    for mut mem in expired {
        mem.is_active = false;
        mem.updated_at = now;
        ctx.db.memory().id().update(mem);
    }

    // 2. Decay weak, stale memories across all workspaces
    let stale_cutoff = now - 7 * 86_400_000_000; // 7 days ago in micros
    for ws in ctx.db.workspace().iter() {
        let weak: Vec<_> = ctx
            .db
            .memory()
            .iter()
            .filter(|m| {
                m.workspace_id == ws.id
                    && m.is_active
                    && m.strength < 0.1
                    && m.updated_at < stale_cutoff
            })
            .collect();

        if weak.is_empty() {
            continue;
        }

        let source_ids: Vec<String> = weak.iter().map(|m| m.id.clone()).collect();
        for mut mem in weak {
            mem.is_active = false;
            mem.updated_at = now;
            ctx.db.memory().id().update(mem);
        }

        let ids_json =
            serde_json::to_string(&source_ids).unwrap_or_else(|_| "[]".to_string());
        ctx.db.consolidation_log().insert(ConsolidationLog {
            id: uuid_v4(ctx),
            workspace_id: ws.id.clone(),
            consolidation_type: String::from("decay"),
            source_memory_ids: ids_json,
            target_memory_id: String::new(),
            created_at: now,
        });
    }

    // 3. Dedup near-duplicate memories per workspace
    for ws in ctx.db.workspace().iter() {
        if let Err(e) = dedup_memories(ctx, ws.id.clone()) {
            // Log but don't halt maintenance on dedup error
            ctx.db.consolidation_log().insert(ConsolidationLog {
                id: uuid_v4(ctx),
                workspace_id: ws.id.clone(),
                consolidation_type: String::from("dedup_error"),
                source_memory_ids: e,
                target_memory_id: String::new(),
                created_at: now,
            });
        }
    }

    Ok(())
}

/// Module initialiser — sets up scheduled maintenance tasks on first publish.
/// Scheduled_id 0,1 = recurring (every 5 min for expire, every 60 min for decay).
#[reducer(init)]
pub fn init(ctx: &ReducerContext) {
    use spacetimedb::TimeDuration;

    // expire: every 5 minutes
    let five_min = TimeDuration::from_micros(5 * 60 * 1_000_000);
    ctx.db.maintenance_schedule().insert(MaintenanceSchedule {
        scheduled_id: 0,
        scheduled_at: five_min.into(),
    });

    // decay: every 60 minutes
    let one_hour = TimeDuration::from_micros(60 * 60 * 1_000_000);
    ctx.db.maintenance_schedule().insert(MaintenanceSchedule {
        scheduled_id: 1,
        scheduled_at: one_hour.into(),
    });
}
