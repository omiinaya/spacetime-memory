use spacetimedb::*;

use crate::{uuid_v4_uniq, now_micros};
use crate::context_directory::{context_directory, directory_memory_link};
use crate::hybrid_query::{cosine_similarity, parse_embedding_json};
use crate::knowledge_graph::{kg_community, kg_edge, kg_node};
use crate::memory::memory;
use crate::memory_feedback;
use crate::note::{note, note_block};
use crate::profile::profile;
use crate::retrieval::search_index;
use crate::workspace::workspace;

/// Tracks consolidation operations (dedup, rollup, decay, version_merge).
#[table(accessor = consolidation_log)]
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
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v4_uniq(ctx, |id| ctx.db.consolidation_log().id().find(id).is_none(), 3);

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
        context: String::new(),
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
        user_scope: String::new(),
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
        id: uuid_v4_uniq(ctx, |id| ctx.db.consolidation_log().id().find(id).is_none(), 3),
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
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);
    let stale_cutoff = now - 7 * 86_400_000_000; // 7 days ago in micros

    let weak: Vec<_> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
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
            id: uuid_v4_uniq(ctx, |id| ctx.db.consolidation_log().id().find(id).is_none(), 3),
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

// ── Merge Suggestion System ─────────────────────────────────────────────

/// A suggested merge between two near-duplicate memories, awaiting review.
#[table(accessor = merge_suggestion)]
#[derive(Debug, Clone)]
pub struct MergeSuggestion {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// The memory that would be deactivated / consolidated away.
    pub source_id: String,
    /// The memory that would be kept (the survivor).
    pub target_id: String,
    pub cosine_similarity: f64,
    /// Normalised edit distance (0.0 – 1.0).
    pub edit_distance: f64,
    /// First 100 chars of each memory, concatenated.
    pub content_overlap_preview: String,
    /// "pending" | "approved" | "rejected"
    pub status: String,
    pub created_at: i64,
}

/// Scan all active memories in a workspace and suggest merge candidates.
///
/// For each pair meeting the threshold criteria (cosine >= *threshold* AND
/// edit distance <= 30 %), a `MergeSuggestion` row is created with status
/// "pending".  Any previous "pending" suggestions for the same workspace
/// are cleared first.
#[reducer]
pub fn suggest_merges(
    ctx: &ReducerContext,
    workspace_id: String,
    threshold: f64,
) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);

    // ── Collect active memories with embeddings ────────────────────────
    #[allow(clippy::type_complexity)]
    let memories: Vec<(String, String, i64, Vec<f64>)> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .map(|m| {
            let emb = ctx
                .db
                .search_index()
                .iter()
                .take(crate::MAX_RESULTS)
                .find(|si| si.entity_type == "memory" && si.entity_id == m.id)
                .map(|si| parse_embedding_json(&si.embedding_json))
                .unwrap_or_default();
            (m.id.clone(), m.content.clone(), m.created_at, emb)
        })
        .collect();

    if memories.len() < 2 {
        return Ok(());
    }

    // ── Clear any existing pending suggestions for this workspace ──────
    let stale: Vec<String> = ctx
        .db
        .merge_suggestion()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|s| s.workspace_id == workspace_id && s.status == "pending")
        .map(|s| s.id.clone())
        .collect();
    for sid in stale {
        ctx.db.merge_suggestion().id().delete(sid);
    }

    // ── Pairwise comparison ────────────────────────────────────────────
    for i in 0..memories.len() - 1 {
        for j in i + 1..memories.len() {
            let (id_a, content_a, created_a, emb_a) = &memories[i];
            let (id_b, content_b, created_b, emb_b) = &memories[j];

            if emb_a.is_empty() || emb_b.is_empty() {
                continue;
            }

            let cos_sim = cosine_similarity(emb_a, emb_b);
            if cos_sim < threshold {
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

            // Newer memory = source (to be deactivated), older = target (survivor)
            let (source_id, target_id) = if created_a < created_b {
                (id_b.clone(), id_a.clone())
            } else {
                (id_a.clone(), id_b.clone())
            };

            let preview = format!(
                "{} | {}",
                content_a.chars().take(100).collect::<String>(),
                content_b.chars().take(100).collect::<String>(),
            );

            ctx.db.merge_suggestion().insert(MergeSuggestion {
                id: uuid_v4_uniq(ctx, |id| ctx.db.merge_suggestion().id().find(id).is_none(), 3),
                workspace_id: workspace_id.clone(),
                source_id,
                target_id,
                cosine_similarity: cos_sim,
                edit_distance: norm_dist,
                content_overlap_preview: preview,
                status: String::from("pending"),
                created_at: now,
            });
        }
    }

    Ok(())
}

/// Approve a merge suggestion: deactivate the source memory into the target.
#[reducer]
pub fn approve_merge(ctx: &ReducerContext, suggestion_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);

    let mut suggestion = ctx
        .db
        .merge_suggestion()
        .id()
        .find(&suggestion_id)
        .ok_or_else(|| "Merge suggestion not found".to_string())?;

    if suggestion.status != "pending" {
        return Err(format!(
            "Suggestion is not pending (current status: {})",
            suggestion.status
        ));
    }

    suggestion.status = String::from("approved");
    // Extract fields before moving `suggestion` into the update call
    let source_id = suggestion.source_id.clone();
    let target_id = suggestion.target_id.clone();
    let workspace_id = suggestion.workspace_id.clone();
    ctx.db.merge_suggestion().id().update(suggestion);

    // Deactivate the source memory, pointing it at the target
    if let Some(mut src) = ctx.db.memory().id().find(&source_id) {
        src.is_active = false;
        src.consolidated_to = target_id.clone();
        src.updated_at = now;
        ctx.db.memory().id().update(src);
    }

    // Reinforce the target (bump access count as a "merge reinforcement")
    if let Some(mut tgt) = ctx.db.memory().id().find(&target_id) {
        tgt.access_count = tgt.access_count.saturating_add(1);
        tgt.updated_at = now;
        ctx.db.memory().id().update(tgt);
    }

    // Log the consolidation
    let source_ids_json = serde_json::to_string(&[source_id])
        .unwrap_or_else(|_| "[]".to_string());
    let log = ConsolidationLog {
        id: uuid_v4_uniq(ctx, |id| ctx.db.consolidation_log().id().find(id).is_none(), 3),
        workspace_id,
        consolidation_type: String::from("approved_merge"),
        source_memory_ids: source_ids_json,
        target_memory_id: target_id,
        created_at: now,
    };
    ctx.db.consolidation_log().insert(log);

    Ok(())
}

/// Reject a merge suggestion without merging.
#[reducer]
pub fn reject_merge(ctx: &ReducerContext, suggestion_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let mut suggestion = ctx
        .db
        .merge_suggestion()
        .id()
        .find(&suggestion_id)
        .ok_or_else(|| "Merge suggestion not found".to_string())?;

    if suggestion.status != "pending" {
        return Err(format!(
            "Suggestion is not pending (current status: {})",
            suggestion.status
        ));
    }

    suggestion.status = String::from("rejected");
    ctx.db.merge_suggestion().id().update(suggestion);

    Ok(())
}

// ── Auto-Dedup ─────────────────────────────────────────────────────

/// Levenshtein edit distance between two strings (character-level).
///
/// Used internally by `dedup_memories` and `suggest_merges` to compute
/// normalised edit distance for near-duplicate detection.
///
/// ```ignore
/// // edit_distance is crate-internal; callable via:
/// let d = crate::consolidation::edit_distance("kitten", "sitting");
/// assert_eq!(d, 3);
/// ```
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_edit_distance_identical() {
        assert_eq!(edit_distance("hello", "hello"), 0);
    }

    #[test]
    fn test_edit_distance_empty_vs_nonempty() {
        assert_eq!(edit_distance("", "abc"), 3);
        assert_eq!(edit_distance("abc", ""), 3);
    }

    #[test]
    fn test_edit_distance_two_empty() {
        assert_eq!(edit_distance("", ""), 0);
    }

    #[test]
    fn test_edit_distance_insert() {
        // "cat" -> "cats" requires 1 insertion
        assert_eq!(edit_distance("cat", "cats"), 1);
    }

    #[test]
    fn test_edit_distance_delete() {
        // "cats" -> "cat" requires 1 deletion
        assert_eq!(edit_distance("cats", "cat"), 1);
    }

    #[test]
    fn test_edit_distance_substitute() {
        // "cat" -> "cut" requires 1 substitution
        assert_eq!(edit_distance("cat", "cut"), 1);
    }

    #[test]
    fn test_edit_distance_completely_different() {
        assert_eq!(edit_distance("abc", "xyz"), 3);
    }

    #[test]
    fn test_edit_distance_unicode() {
        // Unicode characters are single chars in Rust
        assert_eq!(edit_distance("café", "cafe"), 1);
    }

    #[test]
    fn test_edit_distance_longer_transposition() {
        // "kitten" -> "sitting" has edit distance 3
        // k->s, e->i, +g
        assert_eq!(edit_distance("kitten", "sitting"), 3);
    }

    #[test]
    fn test_edit_distance_reversed() {
        // Symmetric property
        assert_eq!(edit_distance("abc", "def"), edit_distance("def", "abc"));
    }
}

/// Find and merge near-duplicate memories within a workspace.
///
/// Two memories are considered duplicates when both conditions hold:
///   1. Embedding cosine similarity >= 0.85
///   2. Character-level Levenshtein distance <= 30% of longer string
///
/// When a pair matches, the older memory is kept and reinforced; the
/// newer one is marked inactive and consolidated_to the older one.
/// All MemoryTag associations and KG edges referencing the duplicate are
/// migrated to the survivor, and the duplicate's entities_json is merged
/// into the survivor's.
#[reducer]
pub fn dedup_memories(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);

    // Collect active memories with their embeddings
    #[allow(clippy::type_complexity)]
    let memories: Vec<(String, String, i64, Vec<f64>)> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .map(|m| {
            let emb = ctx
                .db
                .search_index()
                .iter()
                .take(crate::MAX_RESULTS)
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

            // ── Migrate MemoryTag associations from duplicate → survivor ──
            let tags_to_migrate: Vec<crate::tag::MemoryTag> = ctx
                .db
                .memory_tag()
                .iter()
                .filter(|mt| mt.memory_id == remove_id)
                .collect();
            for mt in &tags_to_migrate {
                // Only add if survivor doesn't already have this tag
                let already = ctx
                    .db
                    .memory_tag()
                    .iter()
                    .any(|existing| existing.memory_id == keep_id && existing.tag_id == mt.tag_id);
                if !already {
                    ctx.db.memory_tag().insert(crate::tag::MemoryTag {
                        memory_id: keep_id.clone(),
                        tag_id: mt.tag_id.clone(),
                    });
                }
                // Remove the old association
                ctx.db.memory_tag().delete(mt.clone());
            }

            // ── Migrate KG edges whose source_memory_id points to duplicate ──
            let edges_to_migrate: Vec<crate::knowledge_graph::KgEdge> = ctx
                .db
                .kg_edge()
                .iter()
                .filter(|e| e.source_memory_id == remove_id)
                .collect();
            for mut edge in edges_to_migrate {
                edge.source_memory_id = keep_id.clone();
                edge.metadata_json = edge
                    .metadata_json
                    .trim_end_matches('}')
                    .to_string()
                    + &format!(",\"merged_from\":\"{}\"", remove_id)
                    + "}";
                ctx.db.kg_edge().id().update(edge);
            }

            // ── Merge entities_json from duplicate into survivor ──
            if let Some(mut survivor) = ctx.db.memory().id().find(&keep_id) {
                // Parse entities from both, deduplicate by name, merge arrays
                let existing_entities: Vec<serde_json::Value> =
                    serde_json::from_str(&survivor.entities_json)
                        .unwrap_or_default();
                let mut dedup_map: std::collections::HashMap<String, serde_json::Value> =
                    std::collections::HashMap::new();
                for ent in existing_entities {
                    if let Some(name) = ent.get("name").and_then(|v| v.as_str()) {
                        dedup_map.insert(name.to_string(), ent);
                    }
                }
                // Add duplicate's entities
                if let Some(dup) = ctx.db.memory().id().find(&remove_id) {
                    let dup_entities: Vec<serde_json::Value> =
                        serde_json::from_str(&dup.entities_json).unwrap_or_default();
                    for ent in dup_entities {
                        if let Some(name) = ent.get("name").and_then(|v| v.as_str()) {
                            dedup_map.entry(name.to_string()).or_insert(ent);
                        }
                    }
                }
                let merged_entities: Vec<serde_json::Value> =
                    dedup_map.into_values().collect();
                survivor.entities_json =
                    serde_json::to_string(&merged_entities).unwrap_or_else(|_| "[]".to_string());
                survivor.access_count = survivor.access_count.saturating_add(1);
                survivor.updated_at = now;
                ctx.db.memory().id().update(survivor);
            }

            // Deactivate the duplicate
            if let Some(mut mem) = ctx.db.memory().id().find(&remove_id) {
                mem.is_active = false;
                mem.consolidated_to = keep_id.clone();
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
    let _admin = crate::auth::require_admin(ctx)?;
    _run_maintenance(ctx)
}

/// Manual maintenance trigger — callable from HTTP API (no scheduled arg needed).
#[reducer]
pub fn manual_maintenance(ctx: &ReducerContext) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    _run_maintenance(ctx)
}

fn _run_maintenance(ctx: &ReducerContext) -> Result<(), String> {
    let now = now_micros(ctx);

    // 1. Expire memories that have passed their expires_at
    let expired: Vec<_> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|m| m.expires_at > 0 && m.expires_at < now)
        .collect();
    for mut mem in expired {
        mem.is_active = false;
        mem.updated_at = now;
        ctx.db.memory().id().update(mem);
    }

    // 2. Decay weak, stale memories across all workspaces
    let stale_cutoff = now - 7 * 86_400_000_000; // 7 days ago in micros
    for ws in ctx.db.workspace().iter().take(crate::MAX_RESULTS) {
        let weak: Vec<_> = ctx
            .db
            .memory()
            .iter()
            .take(crate::MAX_RESULTS)
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
            id: uuid_v4_uniq(ctx, |id| ctx.db.consolidation_log().id().find(id).is_none(), 3),
            workspace_id: ws.id.clone(),
            consolidation_type: String::from("decay"),
            source_memory_ids: ids_json,
            target_memory_id: String::new(),
            created_at: now,
        });
    }

    // 3. Dedup near-duplicate memories per workspace
    for ws in ctx.db.workspace().iter().take(crate::MAX_RESULTS) {
        if let Err(e) = dedup_memories(ctx, ws.id.clone()) {
            // Log but don't halt maintenance on dedup error
            ctx.db.consolidation_log().insert(ConsolidationLog {
                id: uuid_v4_uniq(ctx, |id| ctx.db.consolidation_log().id().find(id).is_none(), 3),
                workspace_id: ws.id.clone(),
                consolidation_type: String::from("dedup_error"),
                source_memory_ids: e,
                target_memory_id: String::new(),
                created_at: now,
            });
        }
    }

    // 4. Apply reputation decay for all workspaces (default params)
    const DEFAULT_DECAY_RATE: f64 = 0.005;
    const DEFAULT_MAX_DAYS: i64 = 90;
    for ws in ctx.db.workspace().iter().take(crate::MAX_RESULTS) {
        if let Err(e) = memory_feedback::apply_decay_inner(
            ctx, &ws.id, DEFAULT_DECAY_RATE, DEFAULT_MAX_DAYS,
            "linear", 0.6, 30.0,
        ) {
            // Log but don't halt maintenance on decay error
            ctx.db.consolidation_log().insert(ConsolidationLog {
                id: uuid_v4_uniq(ctx, |id| ctx.db.consolidation_log().id().find(id).is_none(), 3),
                workspace_id: ws.id.clone(),
                consolidation_type: String::from("decay_error"),
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

// ── Backup / Restore ──────────────────────────────────────────────────────

/// A backup entry storing the JSON-serialised state of a single record.
#[table(accessor = backup_entry)]
#[derive(Debug, Clone)]
pub struct BackupEntry {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Name of the source table (e.g. "memory", "kg_node").
    pub table_name: String,
    /// Primary-key value of the original record.
    pub record_id: String,
    /// JSON-encoded record data.
    pub data_json: String,
    /// Timestamp (micros) when this backup entry was created.
    pub exported_at: i64,
}

/// Export all relevant tables for a workspace into `backup_entry` rows.
///
/// Exported tables: memory, profile, kg_node, kg_edge, kg_community,
/// note, note_block, directory_memory_link, context_directory.
#[reducer]
pub fn export_backup(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);

    let insert_entry = |table_name: &str, record_id: String, data_json: String| {
        ctx.db.backup_entry().insert(BackupEntry {
            id: uuid_v4_uniq(ctx, |id| ctx.db.backup_entry().id().find(id).is_none(), 3),
            workspace_id: workspace_id.clone(),
            table_name: table_name.to_string(),
            record_id,
            data_json,
            exported_at: now,
        });
    };

    // ── memory (filtered by workspace) ────────────────────────────────
    for m in ctx.db.memory().iter().take(crate::MAX_RESULTS).filter(|m| m.workspace_id == workspace_id) {
        let json = serde_json::to_string(&m)
            .map_err(|e| format!("Serialize memory: {}", e))?;
        insert_entry("memory", m.id.clone(), json);
    }

    // ── profile (no workspace_id field — export all) ──────────────────
    for p in ctx.db.profile().iter().take(crate::MAX_RESULTS) {
        let json = serde_json::to_string(&p)
            .map_err(|e| format!("Serialize profile: {}", e))?;
        insert_entry("profile", p.id.clone(), json);
    }

    // ── kg_node ───────────────────────────────────────────────────────
    for n in ctx.db.kg_node().iter().take(crate::MAX_RESULTS).filter(|n| n.workspace_id == workspace_id) {
        let json = serde_json::to_string(&n)
            .map_err(|e| format!("Serialize kg_node: {}", e))?;
        insert_entry("kg_node", n.id.clone(), json);
    }

    // ── kg_edge ───────────────────────────────────────────────────────
    for e in ctx.db.kg_edge().iter().take(crate::MAX_RESULTS).filter(|e| e.workspace_id == workspace_id) {
        let json = serde_json::to_string(&e)
            .map_err(|e| format!("Serialize kg_edge: {}", e))?;
        insert_entry("kg_edge", e.id.clone(), json);
    }

    // ── kg_community ──────────────────────────────────────────────────
    for c in ctx.db.kg_community().iter().take(crate::MAX_RESULTS).filter(|c| c.workspace_id == workspace_id) {
        let json = serde_json::to_string(&c)
            .map_err(|e| format!("Serialize kg_community: {}", e))?;
        insert_entry("kg_community", c.id.to_string(), json);
    }

    // ── note ──────────────────────────────────────────────────────────
    for n in ctx.db.note().iter().take(crate::MAX_RESULTS).filter(|n| n.workspace_id == workspace_id) {
        let json = serde_json::to_string(&n)
            .map_err(|e| format!("Serialize note: {}", e))?;
        insert_entry("note", n.id.clone(), json);
    }

    // ── note_block ────────────────────────────────────────────────────
    for nb in ctx.db.note_block().iter().take(crate::MAX_RESULTS) {
        // note_block doesn't have workspace_id — export all
        let json = serde_json::to_string(&nb)
            .map_err(|e| format!("Serialize note_block: {}", e))?;
        insert_entry("note_block", nb.id.clone(), json);
    }

    // ── directory_memory_link ─────────────────────────────────────────
    for dl in ctx.db.directory_memory_link().iter().take(crate::MAX_RESULTS).filter(|dl| dl.workspace_id == workspace_id) {
        let json = serde_json::to_string(&dl)
            .map_err(|e| format!("Serialize directory_memory_link: {}", e))?;
        insert_entry("directory_memory_link", dl.id.clone(), json);
    }

    // ── context_directory ─────────────────────────────────────────────
    for cd in ctx.db.context_directory().iter().take(crate::MAX_RESULTS).filter(|cd| cd.workspace_id == workspace_id) {
        let json = serde_json::to_string(&cd)
            .map_err(|e| format!("Serialize context_directory: {}", e))?;
        insert_entry("context_directory", cd.id.clone(), json);
    }

    Ok(())
}

/// Restore records for a workspace from `backup_entry` rows.
///
/// Currently restores: memory, kg_node.
/// Skips records whose primary key already exists in the target table.
/// Validates that `data_json` is well-formed JSON before attempting restore.
#[reducer]
pub fn restore_backup(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let entries: Vec<_> = ctx
        .db
        .backup_entry()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|e| e.workspace_id == workspace_id)
        .collect();

    for entry in &entries {
        // Validate JSON first
        serde_json::from_str::<serde_json::Value>(&entry.data_json)
            .map_err(|e| {
                format!(
                    "Invalid JSON in backup entry {} (table={}, record_id={}): {}",
                    entry.id, entry.table_name, entry.record_id, e
                )
            })?;

        match entry.table_name.as_str() {
            "memory" => {
                if ctx.db.memory().id().find(&entry.record_id).is_none() {
                    let mem: crate::memory::Memory = serde_json::from_str(&entry.data_json)
                        .map_err(|e| format!("Deserialize memory: {}", e))?;
                    ctx.db.memory().insert(mem);
                }
            }
            "kg_node" => {
                if ctx.db.kg_node().id().find(&entry.record_id).is_none() {
                    let node: crate::knowledge_graph::KgNode =
                        serde_json::from_str(&entry.data_json)
                            .map_err(|e| format!("Deserialize kg_node: {}", e))?;
                    ctx.db.kg_node().insert(node);
                }
            }
            // Other tables are not auto-restored — they can be re-inserted
            // manually or via a future extension. Silently skip.
            _ => {}
        }
    }

    Ok(())
}
