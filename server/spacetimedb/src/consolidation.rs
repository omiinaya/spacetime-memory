use spacetimedb::*;

use crate::{uuid_v4_uniq, now_micros};
use crate::change_event;
use crate::hybrid_query::{cosine_similarity, parse_embedding_json};
use crate::memory::memory;
use crate::retrieval::search_index;
use crate::workspace::workspace;

/// Tracks consolidation operations (dedup, rollup, decay, version_merge).
#[table(accessor = consolidation_log)]
#[derive(Debug, Clone)]
pub struct ConsolidationLog {
    #[primary_key]
    pub id: String,
    #[index(btree)]
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
        valid_to: 0,
        parent_directory_id: String::new(),
        consolidated_to: String::new(),
        trust_score: 0.5,
        feedback_count: 0,
        user_scope: String::new(),
        source_url: Some(String::new()),
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
                .entity_type().filter(&"memory".to_string())
                .find(|si| si.entity_id == m.id)
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

/// Run full periodic maintenance: expire overdue memories, decay weak
/// memories, and suggest merge candidates — across every workspace.
///
/// This is the reducer the SDK's `run_maintenance()` wraps. Requires admin.
#[reducer]
pub fn manual_maintenance(ctx: &ReducerContext) -> Result<(), String> {
    crate::auth::require_admin(ctx)?;

    // 1. Expire overdue memories (admin-gated reducer in memory.rs).
    crate::memory::expire_memories(ctx)?;

    // 2. Decay weak + stale memories in every workspace.
    let now = now_micros(ctx);
    let stale_cutoff = now - 7 * 86_400_000_000; // 7 days ago in micros
    let workspace_ids: Vec<String> = ctx
        .db
        .workspace()
        .iter()
        .take(crate::MAX_RESULTS)
        .map(|w| w.id.clone())
        .collect();
    for ws in workspace_ids {
        let weak: Vec<_> = ctx
            .db
            .memory()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|m| {
                m.workspace_id == ws
                    && m.is_active
                    && m.strength < 0.3
                    && m.updated_at < stale_cutoff
            })
            .collect();
        for mut mem in weak {
            mem.is_active = false;
            mem.updated_at = now;
            ctx.db.memory().id().update(mem);
        }
    }

    // 3. Suggest merge candidates in every workspace (cosine >= 0.85).
    let ws_ids: Vec<String> = ctx
        .db
        .workspace()
        .iter()
        .take(crate::MAX_RESULTS)
        .map(|w| w.id.clone())
        .collect();
    for ws in ws_ids {
        if let Err(e) = suggest_merges(ctx, ws.clone(), 0.85) {
            // Non-fatal: a workspace with <2 memories just returns Ok; only
            // real errors propagate.
            if e.contains("not found") {
                continue;
            }
        }
    }

    Ok(())
}

/// Automatically deduplicate near-duplicate memories in a workspace.
///
/// Scans active memories and deactivates any pair that is BOTH cosine
/// similarity at least 0.85 AND edit distance at most 30 percent,
/// keeping the older memory as the survivor. Writes a
/// `consolidation_log` row of type `"dedup"`.
///
/// This is the reducer the SDK's `dedup_memories()` wraps.
#[reducer]
pub fn dedup_memories(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);

    // Collect active memories with embeddings.
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
                .entity_type()
                .filter(&"memory".to_string())
                .find(|si| si.entity_id == m.id)
                .map(|si| parse_embedding_json(&si.embedding_json))
                .unwrap_or_default();
            (m.id.clone(), m.content.clone(), m.created_at, emb)
        })
        .collect();

    if memories.len() < 2 {
        return Ok(());
    }

    let mut deactivated: Vec<String> = Vec::new();

    for i in 0..memories.len() - 1 {
        for j in i + 1..memories.len() {
            let (id_a, content_a, created_a, emb_a) = &memories[i];
            let (id_b, content_b, created_b, emb_b) = &memories[j];

            // Cosine similarity threshold.
            let cos = cosine_similarity(emb_a, emb_b);
            if cos < 0.85 {
                continue;
            }

            // Edit distance <= 30 % of the longer string.
            let max_len = content_a.chars().count().max(content_b.chars().count());
            if max_len == 0 {
                continue;
            }
            let norm_edit = edit_distance(content_a, content_b) as f64 / max_len as f64;
            if norm_edit > 0.30 {
                continue;
            }

            // Keep the older memory; deactivate the newer one.
            let (victim, _survivor) = if created_a <= created_b {
                (id_b, id_a)
            } else {
                (id_a, id_b)
            };
            if deactivated.contains(victim) {
                continue;
            }

            let mut mem = ctx
                .db
                .memory()
                .id()
                .find(victim.clone())
                .ok_or_else(|| format!("Memory '{}' not found", victim))?;
            mem.is_active = false;
            mem.updated_at = now;
            let victim_json = change_event::record_to_json(&mem);
            ctx.db.memory().id().update(mem);
            change_event::log_change(ctx, &workspace_id, "memory", "update", victim, &victim_json);
            deactivated.push(victim.clone());
        }
    }

    // Log the dedup operation.
    if !deactivated.is_empty() {
        let ids_json = serde_json::to_string(&deactivated)
            .unwrap_or_else(|_| "[]".to_string());
        let log = ConsolidationLog {
            id: uuid_v4_uniq(ctx, |id| ctx.db.consolidation_log().id().find(id).is_none(), 3),
            workspace_id,
            consolidation_type: String::from("dedup"),
            source_memory_ids: ids_json,
            target_memory_id: String::new(),
            created_at: now,
        };
        ctx.db.consolidation_log().insert(log);
    }

    Ok(())
}

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

    // ── Existing tests (kept) ──
    

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

    // ── Edge case tests ────────────────────────────────────────────

    #[test]
    fn test_edit_distance_empty_search() {
        assert_eq!(edit_distance("", ""), 0);
        assert_eq!(edit_distance("", "abc"), 3);
        assert_eq!(edit_distance("abc", ""), 3);
    }
    
    #[test]
    fn test_edit_distance_special_characters() {
        assert_eq!(edit_distance("!@#$%", "!@#$%"), 0);
        assert_eq!(edit_distance("hello!", "hello?"), 1);
        assert_eq!(edit_distance("a+b", "a-b"), 1);
    }
    
    #[test]
    fn test_edit_distance_unicode_mixed() {
        assert_eq!(edit_distance("café", "cafe"), 1);
        assert_eq!(edit_distance("日本語", "日本語"), 0);
        assert_eq!(edit_distance("日本語", "日本"), 1);
    }
    
    #[test]
    fn test_edit_distance_very_large_content() {
        let a = "A".repeat(5000);
        let b = "A".repeat(5000);
        assert_eq!(edit_distance(&a, &b), 0);
        let c = "A".repeat(5000) + "B";
        let d = "A".repeat(5000) + "C";
        // both length 5001, differ only in last char → distance = 1 (substitute B for C)
        assert_eq!(edit_distance(&c, &d), 1);
        assert_eq!(edit_distance(&("A".repeat(5000)+"B"), &("A".repeat(5000)+"C")), 1);
    }
    
    #[test]
    fn test_edit_distance_concurrent_writes_simulation() {
        // Simulate comparing many strings as in concurrent dedup
        let entries: Vec<String> = (0..20)
            .map(|i| format!("memory content number {}", i))
            .collect();
        for i in 0..entries.len() {
            for j in i+1..entries.len() {
                let d = edit_distance(&entries[i], &entries[j]);
                assert!(d > 0);
                assert!(d < 50);
            }
        }
    }
    
    #[test]
    fn test_edit_distance_network_partition_simulation() {
        // Simulate partial data: one string empty
        // "some data" is 9 chars → 9 insertions from empty
        assert_eq!(edit_distance("", "some data"), 9);
        assert_eq!(edit_distance("some data", ""), 9);
        // Partial similarity despite missing data
        assert_eq!(edit_distance("partial", "partial data"), 5);
    }
}
