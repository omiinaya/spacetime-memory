use spacetimedb::*;
use crate::auth::require_admin;
use crate::auth::require_auth;

use crate::{memory::memory, now_micros, uuid_v4};
use crate::workspace::workspace;

/// Records user feedback on a memory for trust scoring.
#[table(accessor = memory_feedback, public)]
#[derive(Debug, Clone)]
pub struct MemoryFeedback {
    #[primary_key]
    pub id: String,
    /// The memory this feedback applies to
    pub memory_id: String,
    /// Original rating string: "helpful", "unhelpful", or "1"-"5"
    pub rating: String,
    /// Numeric score (1.0–5.0) parsed from the rating
    pub score: f64,
    /// The peer who submitted the feedback
    pub peer_id: String,
    pub created_at: i64,
}

/// Per-workspace configuration for reputation decay.
///
/// Controls how memory trust scores decay over time when not reinforced.
/// Each workspace can have its own decay parameters.
#[table(accessor = workspace_config, public)]
#[derive(Debug, Clone)]
pub struct WorkspaceConfig {
    #[primary_key]
    pub id: String, // workspace_id
    /// Fraction of trust to decay per day (e.g. 0.005 = 0.5% per day)
    pub decay_rate: f64,
    /// Max age in days before trust hits the floor (0.1)
    pub max_decay_days: i64,
    /// Timestamp (micros) of last decay run
    pub last_decay_at: i64,
}

/// Rate a memory: records feedback and recalculates its trust_score.
///
/// Accepts a 1–5 scale:
/// - `"helpful"` → score 5
/// - `"unhelpful"` → score 1
/// - `"1"`, `"2"`, `"3"`, `"4"`, `"5"` → score as-is
///
/// Trust score is recomputed as the average of all feedback scores
/// mapped to [0.0, 1.0] (score / 5.0).
#[reducer]
pub fn rate_memory(
    ctx: &ReducerContext,
    memory_id: String,
    rating: String,
    peer_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Parse rating into numeric score 1.0–5.0
    let score: f64 = match rating.as_str() {
        "helpful" => 5.0,
        "unhelpful" => 1.0,
        other => {
            let n: i32 = other
                .parse()
                .map_err(|_| {
                    format!(
                        "Invalid rating '{}'. Must be 'helpful', 'unhelpful', or an integer 1–5",
                        rating
                    )
                })?;
            if !(1..=5).contains(&n) {
                return Err(format!(
                    "Invalid rating '{}'. Must be between 1 and 5",
                    rating
                ));
            }
            n as f64
        }
    };

    // Find the memory
    let mut mem = ctx
        .db
        .memory()
        .id()
        .find(&memory_id)
        .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;

    // Record the feedback
    let feedback = MemoryFeedback {
        id: uuid_v4(ctx),
        memory_id: memory_id.clone(),
        rating: rating.clone(),
        score,
        peer_id,
        created_at: now_micros(ctx),
    };
    ctx.db.memory_feedback().insert(feedback);

    // Recalculate trust_score as average of all feedback scores / 5.0
    let all_scores: Vec<f64> = ctx
        .db
        .memory_feedback()
        .iter()
        .filter(|f| f.memory_id == memory_id)
        .map(|f| f.score)
        .collect();
    let avg_score = if all_scores.is_empty() {
        0.5
    } else {
        all_scores.iter().sum::<f64>() / all_scores.len() as f64
    };
    mem.trust_score = (avg_score / 5.0).clamp(0.0, 1.0);
    mem.feedback_count += 1;
    mem.updated_at = now_micros(ctx);

    ctx.db.memory().id().update(mem);
    Ok(())
}

// ── Time-weighted reputation decay (Holographic) ──

/// Microseconds in one day (24h × 60m × 60s × 1_000_000µs).
const MICROS_PER_DAY: i64 = 86_400_000_000;

/// Core decay logic shared by `apply_reputation_decay` and `manual_decay`.
///
/// Iterates all active memories in the given workspace and applies
/// time-weighted reputation decay:
///   new_trust = trust_score * (1.0 - decay_rate * days_since_last_access)
///
/// Memories older than `max_days` are set to the floor trust score (0.1).
/// The result is clamped to [0.1, 1.0].
pub fn apply_decay_inner(
    ctx: &ReducerContext,
    workspace_id: &str,
    decay_rate: f64,
    max_days: i64,
) -> Result<(), String> {
    let now = now_micros(ctx);

    // Collect active memories for this workspace
    let memories: Vec<_> = ctx
        .db
        .memory()
        .iter()
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .collect();

    for mut mem in memories {
        let age_micros = now - mem.updated_at;
        let days_since_last_access = age_micros as f64 / MICROS_PER_DAY as f64;

        let new_trust = if days_since_last_access > max_days as f64 {
            // Older than max_days → floor trust score
            0.1
        } else {
            mem.trust_score * (1.0 - decay_rate * days_since_last_access)
        };

        mem.trust_score = new_trust.clamp(0.1, 1.0);
        // Touch updated_at so repeated runs don't compound the same decay
        mem.updated_at = now;

        ctx.db.memory().id().update(mem);
    }

    // Upsert workspace config — record when we last ran decay
    let found = ctx.db.workspace_config().id().find(workspace_id.to_string());
    if let Some(mut config) = found {
        config.decay_rate = decay_rate;
        config.max_decay_days = max_days;
        config.last_decay_at = now;
        ctx.db.workspace_config().id().update(config);
    } else {
        ctx.db.workspace_config().insert(WorkspaceConfig {
            id: workspace_id.to_string(),
            decay_rate,
            max_decay_days: max_days,
            last_decay_at: now,
        });
    }

    Ok(())
}

/// Apply time-weighted reputation decay to all active memories in a workspace.
///
/// * `workspace_id` — the workspace to operate on
/// * `decay_rate` — fraction of trust to decay per day (e.g. 0.01 = 1%/day)
/// * `max_days` — memories older than this many days get a floor trust score (0.1)
///
/// The decay formula is:
///   new_trust = trust_score × (1.0 - decay_rate × days_since_last_access)
///
/// Results are clamped to [0.1, 1.0].
#[reducer]
pub fn apply_reputation_decay(
    ctx: &ReducerContext,
    workspace_id: String,
    decay_rate: f64,
    max_days: i64,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    apply_decay_inner(ctx, &workspace_id, decay_rate, max_days)
}

/// Trigger maintenance decay for all workspaces with default parameters.
///
/// Default: `decay_rate = 0.005` (0.5% per day), `max_days = 90`.
/// Per-workspace overrides stored in `WorkspaceConfig` are respected.
/// Intended to be called from the consolidation cron.
#[reducer]
pub fn manual_decay(ctx: &ReducerContext) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    const DEFAULT_DECAY_RATE: f64 = 0.005;
    const DEFAULT_MAX_DAYS: i64 = 90;

    // Collect workspace IDs first to avoid borrow conflicts with ctx
    let workspace_ids: Vec<String> = ctx
        .db
        .workspace()
        .iter()
        .map(|ws| ws.id.clone())
        .collect();

    for ws_id in workspace_ids {
        // Check for per-workspace config overrides
        let config = ctx.db.workspace_config().id().find(&ws_id);
        let decay_rate = config
            .as_ref()
            .map(|c| c.decay_rate)
            .unwrap_or(DEFAULT_DECAY_RATE);
        let max_days = config
            .as_ref()
            .map(|c| c.max_decay_days)
            .unwrap_or(DEFAULT_MAX_DAYS);

        apply_decay_inner(ctx, &ws_id, decay_rate, max_days)?;
    }

    Ok(())
}
