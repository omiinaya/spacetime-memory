use spacetimedb::*;
use crate::auth::require_admin;
use crate::auth::require_auth;

use crate::{memory::memory, now_micros, uuid_v4};
use crate::workspace::workspace;

/// Records user feedback on a memory for trust scoring.
#[table(accessor = memory_feedback)]
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
#[table(accessor = workspace_config)]
#[derive(Debug, Clone)]
pub struct WorkspaceConfig {
    #[primary_key]
    pub id: String, // workspace_id
    /// Decay model: "linear" (default) or "weibull"
    pub decay_model: String,
    /// Fraction of trust to decay per day (e.g. 0.005 = 0.5% per day) — linear model
    pub decay_rate: f64,
    /// Max age in days before trust hits the floor (0.1) — linear model
    pub max_decay_days: i64,
    /// Weibull shape parameter k (< 1 = rapid-then-slow, 1 = exponential, > 1 = accelerating).
    /// Default: 0.6 — realistic human forgetting curve.
    pub weibull_shape: f64,
    /// Weibull scale parameter λ (characteristic time in days). Default: 30.0.
    /// At t=λ, trust falls to ~37% of initial (1/e).
    pub weibull_scale: f64,
    /// Timestamp (micros) of last decay run
    pub last_decay_at: i64,
}

/// Per-peer reputation tracking across all workspaces.
///
/// Aggregates feedback on memories authored by a peer to compute
/// a reputation score (0.0–1.0) that influences trust in new memories.
#[table(accessor = peer_reputation)]
#[derive(Debug, Clone)]
pub struct PeerReputation {
    #[primary_key]
    pub id: String, // peer_id
    /// Cumulative helpful feedback count
    pub helpful_count: u64,
    /// Cumulative unhelpful feedback count
    pub unhelpful_count: u64,
    /// Total feedback submissions
    pub total_feedback: u64,
    /// Reputation score 0.0–1.0: helpful_count / total_feedback,
    /// with a Bayesian prior of 1 helpful + 1 unhelpful (Laplace smoothing)
    pub reputation_score: f64,
    /// Timestamp (micros) of last feedback
    pub last_feedback_at: i64,
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

    let author_id = mem.peer_id.clone();

    ctx.db.memory().id().update(mem);

    // ── Update peer reputation ─────────────────────────────────
    // Track how often a memory author's work is rated helpful/unhelpful.
    if !author_id.is_empty() {
        let now = now_micros(ctx);
        let is_helpful = score >= 4.0; // 4-5 = helpful, 1-3 = unhelpful

        let existing = ctx.db.peer_reputation().id().find(&author_id);
        if let Some(mut rep) = existing {
            if is_helpful {
                rep.helpful_count += 1;
            } else {
                rep.unhelpful_count += 1;
            }
            rep.total_feedback += 1;
            // Laplace smoothing: (helpful + 1) / (total + 2)
            rep.reputation_score = (rep.helpful_count as f64 + 1.0)
                / (rep.total_feedback as f64 + 2.0);
            rep.last_feedback_at = now;
            ctx.db.peer_reputation().id().update(rep);
        } else {
            ctx.db.peer_reputation().insert(PeerReputation {
                id: author_id.clone(),
                helpful_count: if is_helpful { 1 } else { 0 },
                unhelpful_count: if is_helpful { 0 } else { 1 },
                total_feedback: 1,
                reputation_score: if is_helpful { 0.667 } else { 0.333 },
                last_feedback_at: now,
            });
        }
    }

    Ok(())
}

// ── Time-weighted reputation decay (Holographic) ──

/// Microseconds in one day (24h × 60m × 60s × 1_000_000µs).
const MICROS_PER_DAY: i64 = 86_400_000_000;

/// Core decay logic shared by `apply_reputation_decay` and `manual_decay`.
///
/// Iterates all active memories in the given workspace and applies
/// time-weighted reputation decay.
///
/// **Linear model** (``decay_model = "linear"``, default):
///   new_trust = trust_score * (1.0 - decay_rate * days_since_last_access)
///
/// **Weibull model** (``decay_model = "weibull"``):
///   new_trust = initial_trust * exp(-(t/λ)^k)
///
///   - t = days_since_last_access
///   - k = weibull_shape (< 1 = rapid-then-slow forgetting, default 0.6)
///   - λ = weibull_scale (characteristic time in days, default 30.0)
///
///   At t = λ, trust ≈ 37% of initial.  At t = 3λ, trust ≈ 5%.
///   The Weibull model never reaches exactly zero — it decays smoothly.
///
/// Memories older than `max_days` (linear) or with trust below 0.05 are
/// clamped to the floor (0.05 for Weibull, 0.1 for linear).
/// The result is clamped to [0.1, 1.0] for linear, [0.05, 1.0] for Weibull.
pub fn apply_decay_inner(
    ctx: &ReducerContext,
    workspace_id: &str,
    decay_rate: f64,
    max_days: i64,
    decay_model: &str,
    weibull_shape: f64,
    weibull_scale: f64,
) -> Result<(), String> {
    let now = now_micros(ctx);

    // Collect active memories for this workspace
    let memories: Vec<_> = ctx
        .db
        .memory()
        .iter()
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .collect();

    let use_weibull = decay_model == "weibull";
    let floor = if use_weibull { 0.05 } else { 0.1 };

    for mut mem in memories {
        let age_micros = now - mem.updated_at;
        let days_since_last_access = age_micros as f64 / MICROS_PER_DAY as f64;

        let new_trust = if use_weibull {
            // Weibull: trust = initial * exp(-(t/λ)^k)
            let initial = mem.trust_score.max(0.5); // use current trust as initial floor
            let t = days_since_last_access;
            let k = weibull_shape.max(0.1).min(5.0);
            let lambda = weibull_scale.max(1.0);
            let exponent = -(t / lambda).powf(k);
            initial * exponent.exp()
        } else {
            // Linear: new_trust = trust_score * (1.0 - decay_rate * days)
            if days_since_last_access > max_days as f64 {
                floor
            } else {
                mem.trust_score * (1.0 - decay_rate * days_since_last_access)
            }
        };

        mem.trust_score = new_trust.clamp(floor, 1.0);
        // Touch updated_at so repeated runs don't compound the same decay
        mem.updated_at = now;

        ctx.db.memory().id().update(mem);
    }

    // Upsert workspace config — record when we last ran decay
    let found = ctx.db.workspace_config().id().find(workspace_id.to_string());
    if let Some(mut config) = found {
        config.decay_model = decay_model.to_string();
        config.decay_rate = decay_rate;
        config.max_decay_days = max_days;
        config.weibull_shape = weibull_shape;
        config.weibull_scale = weibull_scale;
        config.last_decay_at = now;
        ctx.db.workspace_config().id().update(config);
    } else {
        ctx.db.workspace_config().insert(WorkspaceConfig {
            id: workspace_id.to_string(),
            decay_model: decay_model.to_string(),
            decay_rate,
            max_decay_days: max_days,
            weibull_shape,
            weibull_scale,
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
    apply_decay_inner(ctx, &workspace_id, decay_rate, max_days, "linear", 0.6, 30.0)
}

/// Apply Weibull decay to all active memories in a workspace.
///
/// Uses the Weibull forgetting curve:
///   new_trust = initial_trust * exp(-(t/λ)^k)
///
/// * `workspace_id` — the workspace to operate on
/// * `weibull_shape` — k parameter (< 1 = rapid-then-slow, default 0.6)
/// * `weibull_scale` — λ parameter (characteristic time in days, default 30.0)
///
/// At t = λ, trust falls to ~37% of initial. At t = 3λ, trust ≈ 5%.
#[reducer]
pub fn apply_weibull_decay(
    ctx: &ReducerContext,
    workspace_id: String,
    weibull_shape: f64,
    weibull_scale: f64,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    apply_decay_inner(ctx, &workspace_id, 0.0, 0, "weibull", weibull_shape, weibull_scale)
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
        let decay_model = config
            .as_ref()
            .map(|c| c.decay_model.as_str())
            .unwrap_or("linear");
        let weibull_shape = config
            .as_ref()
            .map(|c| c.weibull_shape)
            .unwrap_or(0.6);
        let weibull_scale = config
            .as_ref()
            .map(|c| c.weibull_scale)
            .unwrap_or(30.0);

        apply_decay_inner(ctx, &ws_id, decay_rate, max_days, decay_model, weibull_shape, weibull_scale)?;
    }

    Ok(())
}

// ── Memory Recommendation Engine (Holographic) ──

/// Recommend memories that need attention (review, reinforce, or discard).
///
/// Sorts active memories by a composite urgency score:
///   urgency = (1.0 - trust_score) * age_weight * feedback_penalty
///
/// - Low trust → needs review
/// - Old memories with no feedback → decaying, may need reinforcement
/// - Feedback penalty: memories with many ratings but low trust are
///   consistently poor — flag for deletion
///
/// Results are stored in a public result table for client consumption.
#[table(accessor = memory_recommendation, public)]
#[derive(Debug, Clone)]
pub struct MemoryRecommendation {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub memory_id: String,
    pub content: String,
    pub trust_score: f64,
    pub feedback_count: u32,
    /// "review" (low trust) | "reinforce" (decaying) | "discard" (consistently poor)
    pub action: String,
    /// Composite urgency score 0.0–1.0 (higher = more urgent)
    pub urgency: f64,
    pub created_at: i64,
}

const MICROS_PER_DAY_REC: i64 = 86_400_000_000;

/// Generate memory recommendations for a workspace.
///
/// * `workspace_id` — target workspace
/// * `limit` — max recommendations (default 20)
/// * `min_urgency` — only return recommendations with urgency >= this (default 0.3)
#[reducer]
pub fn recommend_memories(
    ctx: &ReducerContext,
    workspace_id: String,
    limit: u32,
    min_urgency: f64,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let limit = if limit == 0 { 20 } else { limit };
    let min_urgency = if min_urgency == 0.0 { 0.3 } else { min_urgency };

    // Clear previous recommendations for this workspace
    let old: Vec<_> = ctx.db.memory_recommendation().iter().take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id)
        .collect();
    for r in old {
        ctx.db.memory_recommendation().id().delete(&r.id);
    }

    let mut recommendations: Vec<(String, String, f64, u32, String, f64)> = Vec::new();

    for mem in ctx.db.memory().iter().take(crate::MAX_RESULTS)
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
    {
        let trust = mem.trust_score;
        let feedback = mem.feedback_count as u32;
        let age_micros = now - mem.updated_at;
        let age_days = age_micros as f64 / MICROS_PER_DAY_REC as f64;

        // Age weight: newer memories get higher urgency when trust is low
        // (recent bad memory needs attention faster than old decayed one)
        let age_weight = if age_days < 1.0 { 1.5 }        // < 1 day: urgent
            else if age_days < 7.0 { 1.2 }                 // < 1 week
            else if age_days < 30.0 { 1.0 }                 // < 1 month
            else { 0.8 };                                    // older: less urgent

        // Feedback penalty: many negative ratings = consistently poor
        let feedback_penalty = if feedback >= 3 && trust < 0.3 {
            1.5 // consistently poor — flag aggressively
        } else if feedback >= 5 && trust < 0.5 {
            1.2
        } else {
            1.0
        };

        // Determine action
        let action = if feedback >= 3 && trust < 0.3 {
            "discard"
        } else if feedback == 0 && trust < 0.5 && age_days > 7.0 {
            "reinforce"
        } else {
            "review"
        };

        let urgency = ((1.0 - trust) * age_weight * feedback_penalty).min(1.0);

        if urgency >= min_urgency {
            recommendations.push((
                mem.id.clone(),
                mem.content.clone(),
                trust,
                feedback,
                action.to_string(),
                urgency,
            ));
        }
    }

    // Sort by urgency descending, take top limit
    recommendations.sort_by(|a, b| b.5.partial_cmp(&a.5).unwrap_or(std::cmp::Ordering::Equal));
    recommendations.truncate(limit as usize);

    for (mem_id, content, trust, fb_count, action, urgency) in &recommendations {
        ctx.db.memory_recommendation().insert(MemoryRecommendation {
            id: uuid_v4(ctx),
            workspace_id: workspace_id.clone(),
            memory_id: mem_id.clone(),
            content: content.clone(),
            trust_score: *trust,
            feedback_count: *fb_count,
            action: action.clone(),
            urgency: *urgency,
            created_at: now,
        });
    }

    Ok(())
}
