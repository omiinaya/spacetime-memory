use spacetimedb::*;

use crate::auth::require_auth;
use crate::{now_micros};
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::workspace::check_space_access;
use crate::memory::memory;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// How much alpha increases on a simple recall (compounding).
pub const COMPOUND_ALPHA_ON_RECALL: f64 = 0.05;
/// How much alpha increases on explicit positive feedback.
pub const FEEDBACK_ALPHA_POSITIVE: f64 = 0.25;
/// How much beta increases on explicit negative feedback.
pub const FEEDBACK_BETA_NEGATIVE: f64 = 0.35;
/// How much alpha increases when a confirmation event fires.
pub const CONFIRM_ALPHA_BOOST: f64 = 0.15;
/// How much beta increases on a contradiction event.
pub const CONTRADICT_BETA_BOOST: f64 = 0.20;
/// Minimum total evidence (alpha + beta) before we consider a memory "established".
pub const MIN_EVIDENCE_FOR_HIGH_TIER: f64 = 3.0;
pub const MIN_EVIDENCE_FOR_CERTAIN_TIER: f64 = 10.0;
/// Confidence threshold for HIGH tier.
pub const CONF_THRESHOLD_HIGH: f64 = 0.80;
/// Confidence threshold for MEDIUM tier.
pub const CONF_THRESHOLD_MEDIUM: f64 = 0.60;
/// Confidence threshold for LOW tier.
pub const CONF_THRESHOLD_LOW: f64 = 0.40;
/// Confidence threshold for CERTAIN tier.
pub const CONF_THRESHOLD_CERTAIN: f64 = 0.90;

// ---------------------------------------------------------------------------
// Tier enumeration
// ---------------------------------------------------------------------------

/// Five veracity tiers, from highest confidence to lowest.
/// Each maps to a string label stored in the `tier` field on memory.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum VeracityTier {
    /// Confirmed: high confidence + abundant evidence; rarely wrong.
    Certain = 4,
    /// High confidence but limited evidence; likely correct.
    High = 3,
    /// Moderate confidence; plausible but needs corroboration.
    Medium = 2,
    /// Low confidence; weak or early signal.
    Low = 1,
    /// Minimal or no evidence; pure conjecture.
    Speculative = 0,
}

impl VeracityTier {
    /// Return the string label used in the `tier` field.
    pub fn label(&self) -> &'static str {
        match self {
            VeracityTier::Certain => "CERTAIN",
            VeracityTier::High => "HIGH",
            VeracityTier::Medium => "MEDIUM",
            VeracityTier::Low => "LOW",
            VeracityTier::Speculative => "SPECULATIVE",
        }
    }

    /// Parse from a string label.
    pub fn from_label(s: &str) -> Self {
        match s {
            "CERTAIN" => VeracityTier::Certain,
            "HIGH" => VeracityTier::High,
            "MEDIUM" => VeracityTier::Medium,
            "LOW" => VeracityTier::Low,
            _ => VeracityTier::Speculative,
        }
    }
}

// ---------------------------------------------------------------------------
// Pure Bayesian functions (no DB access — testable in isolation)
// ---------------------------------------------------------------------------

/// Compute posterior confidence from Beta distribution parameters.
/// Returns `alpha / (alpha + beta)`, clamped to [0.0, 1.0].
pub fn bayesian_confidence(alpha: f64, beta: f64) -> f64 {
    let total = alpha + beta;
    if total <= 0.0 {
        return 0.5; // uniform prior
    }
    (alpha / total).clamp(0.0, 1.0)
}

/// Update Beta posterior given an observation.
///
/// - `outcome = true`: positive evidence (memory confirmed/corroborated)
/// - `outcome = false`: negative evidence (memory contradicted/refuted)
/// - `weight`: how strongly this observation counts
pub fn bayesian_update(alpha: f64, beta: f64, outcome: bool, weight: f64) -> (f64, f64) {
    let w = weight.max(0.0);
    if outcome {
        (alpha + w, beta)
    } else {
        (alpha, beta + w)
    }
}

/// Compute the veracity tier from Bayesian parameters and total evidence.
pub fn compute_tier(confidence: f64, total_evidence: f64) -> VeracityTier {
    if confidence >= CONF_THRESHOLD_CERTAIN && total_evidence >= MIN_EVIDENCE_FOR_CERTAIN_TIER {
        VeracityTier::Certain
    } else if confidence >= CONF_THRESHOLD_HIGH && total_evidence >= MIN_EVIDENCE_FOR_HIGH_TIER {
        VeracityTier::High
    } else if confidence >= CONF_THRESHOLD_MEDIUM && total_evidence >= MIN_EVIDENCE_FOR_HIGH_TIER {
        VeracityTier::Medium
    } else if confidence >= CONF_THRESHOLD_LOW {
        VeracityTier::Low
    } else {
        VeracityTier::Speculative
    }
}

// ---------------------------------------------------------------------------
// VeracityEvidence table — stores Bayesian parameters per memory
// ---------------------------------------------------------------------------

/// Stores the Bayesian parameters (alpha, beta) for a memory's veracity.
/// The derived `confidence` and `tier` fields on the `Memory` row are
/// computed from these parameters on each mutation.
#[table(accessor = veracity_evidence)]
#[derive(Debug, Clone)]
pub struct VeracityEvidence {
    #[primary_key]
    pub memory_id: String,
    /// Beta prior alpha — evidence *for* the memory being true
    pub alpha: f64,
    /// Beta prior beta — evidence *against* the memory being true
    pub beta: f64,
    /// Last timestamp this record was updated
    pub last_updated: i64,
    /// Total number of evidence events captured
    pub evidence_count: u64,
    /// Number of contradictory evidence events
    pub contradictory_count: u64,
    /// Number of confirmatory evidence events
    pub confirmatory_count: u64,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Insert initial VeracityEvidence for a new memory with a uniform prior.
pub fn insert_initial_evidence(
    ctx: &ReducerContext,
    memory_id: &str,
    now: i64,
) {
    let evidence = VeracityEvidence {
        memory_id: memory_id.to_string(),
        alpha: 1.0,  // uniform Beta(1,1) prior
        beta: 1.0,
        last_updated: now,
        evidence_count: 0,
        contradictory_count: 0,
        confirmatory_count: 0,
    };
    ctx.db.veracity_evidence().insert(evidence);
}

/// Apply a Bayesian update to a memory's veracity and sync the derived
/// `confidence` and `tier` fields on the Memory row.
///
/// Returns the new (confidence, tier_label) if successful.
pub fn update_veracity(
    ctx: &ReducerContext,
    memory_id: &str,
    outcome: bool,
    weight: f64,
) -> Result<(f64, String), String> {
    let now = now_micros(ctx);
    let mid = memory_id.to_string();

    // Load or create VeracityEvidence
    let mut ev = if let Some(e) = ctx.db.veracity_evidence().memory_id().find(mid.clone()) {
        e
    } else {
        // Memory exists but no evidence yet (migration from pre-veracity data)
        VeracityEvidence {
            memory_id: mid.clone(),
            alpha: 1.0,
            beta: 1.0,
            last_updated: now,
            evidence_count: 0,
            contradictory_count: 0,
            confirmatory_count: 0,
        }
    };

    // Apply Bayesian update
    let (new_alpha, new_beta) = bayesian_update(ev.alpha, ev.beta, outcome, weight);
    ev.alpha = new_alpha;
    ev.beta = new_beta;
    ev.evidence_count += 1;
    if outcome {
        ev.confirmatory_count += 1;
    } else {
        ev.contradictory_count += 1;
    }
    ev.last_updated = now;

    let confidence = bayesian_confidence(ev.alpha, ev.beta);
    let total_evidence = (ev.alpha + ev.beta - 2.0).max(0.0);
    let tier = compute_tier(confidence, total_evidence);
    let tier_label = tier.label().to_string();

    // Update the VeracityEvidence row (UPSERT: insert if new, update if exists)
    if ctx.db.veracity_evidence().memory_id().find(mid.clone()).is_some() {
        ctx.db.veracity_evidence().memory_id().update(ev);
    } else {
        ctx.db.veracity_evidence().insert(ev);
    }

    // Sync the derived fields back to the Memory row
    if let Some(mut mem) = ctx.db.memory().id().find(mid) {
        mem.confidence = confidence;
        mem.tier = tier_label.clone();
        mem.updated_at = now;
        ctx.db.memory().id().update(mem);
    }

    Ok((confidence, tier_label))
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

/// Update veracity for a single memory with an observation.
///
/// - `memory_id`: target memory
/// - `outcome`: true = positive/confirmatory, false = negative/contradictory
/// - `weight`: evidence weight (default 1.0, use 0.05 for passive recall compounding)
#[reducer]
pub fn update_memory_veracity(
    ctx: &ReducerContext,
    workspace_id: String,
    memory_id: String,
    outcome: bool,
    weight: f64,
) -> Result<(), String> {
    trace_span!(ctx, "update_memory_veracity", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        // Verify the memory exists and belongs to this workspace
        let mem = ctx.db.memory().id().find(memory_id.clone())
            .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;
        if mem.workspace_id != workspace_id {
            return Err("Memory does not belong to the specified workspace".to_string());
        }

        let _ = update_veracity(ctx, &memory_id, outcome, weight)?;
        Ok(())
    })
}

/// Batch update veracity for multiple memories.
/// Accepts a JSON array of `{memory_id, outcome, weight}` objects.
#[reducer]
pub fn batch_update_veracity(
    ctx: &ReducerContext,
    workspace_id: String,
    items_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "batch_update_veracity", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        let items: Vec<serde_json::Value> = serde_json::from_str(&items_json)
            .map_err(|e| format!("Invalid items_json: {}", e))?;

        for item in &items {
            let mid = item.get("memory_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| "Missing memory_id in batch item".to_string())?;
            let outcome = item.get("outcome")
                .and_then(|v| v.as_bool())
                .unwrap_or(true);
            let weight = item.get("weight")
                .and_then(|v| v.as_f64())
                .unwrap_or(COMPOUND_ALPHA_ON_RECALL);

            // Verify memory belongs to workspace
            let mem = ctx.db.memory().id().find(mid.to_string())
                .ok_or_else(|| format!("Memory '{}' not found", mid))?;
            if mem.workspace_id != workspace_id {
                return Err(format!("Memory '{}' does not belong to workspace", mid));
            }

            update_veracity(ctx, mid, outcome, weight)?;
        }

        Ok(())
    })
}

/// Compound veracity for memories returned by a search (called from retrieval).
/// Each hit gets a small positive Bayesian update.
pub fn compound_search_hits(
    ctx: &ReducerContext,
    memory_ids: &[String],
    weight: f64,
) {
    for mid in memory_ids {
        if let Some(ev) = ctx.db.veracity_evidence().memory_id().find(mid.clone()) {
            // Only update if total evidence isn't saturated (cap at 1000)
            let total_ev = ev.alpha + ev.beta - 2.0;
            if total_ev < 1000.0 {
                let _ = update_veracity(ctx, mid, true, weight);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

/// Get veracity evidence for a single memory.
#[reducer]
pub fn get_memory_veracity(
    ctx: &ReducerContext,
    workspace_id: String,
    memory_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    let ev = ctx.db.veracity_evidence().memory_id().find(memory_id)
        .ok_or_else(|| "No veracity evidence for memory".to_string())?;

    let confidence = bayesian_confidence(ev.alpha, ev.beta);
    let total_evidence = (ev.alpha + ev.beta - 2.0).max(0.0);
    let tier = compute_tier(confidence, total_evidence);

    let result = serde_json::json!({
        "memory_id": ev.memory_id,
        "alpha": ev.alpha,
        "beta": ev.beta,
        "confidence": confidence,
        "tier": tier.label(),
        "evidence_count": ev.evidence_count,
        "confirmatory_count": ev.confirmatory_count,
        "contradictory_count": ev.contradictory_count,
        "total_evidence": total_evidence,
        "last_updated": ev.last_updated,
    });

    // Write result to a temporary table for the client to read
    let id = format!("veracity:{}:{}", workspace_id, crate::now_micros(ctx));
    ctx.db.veracity_evidence_result().insert(VeracityEvidenceResult {
        id,
        workspace_id,
        result_json: serde_json::to_string(&result).unwrap_or_default(),
    });

    Ok(())
}

/// List veracity evidence for all memories in a workspace (paginated).
#[reducer]
pub fn list_workspace_veracity(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    let results: Vec<serde_json::Value> = ctx.db.veracity_evidence()
        .iter().take(crate::MAX_RESULTS)
        .filter_map(|ev| {
            // Only include memories that belong to this workspace
            let mid = ev.memory_id.clone();
            let mem = ctx.db.memory().id().find(mid)?;
            if mem.workspace_id != workspace_id {
                return None;
            }
            let confidence = bayesian_confidence(ev.alpha, ev.beta);
            let total_evidence = (ev.alpha + ev.beta - 2.0).max(0.0);
            let tier = compute_tier(confidence, total_evidence);
            Some(serde_json::json!({
                "memory_id": ev.memory_id,
                "confidence": confidence,
                "tier": tier.label(),
                "evidence_count": ev.evidence_count,
                "total_evidence": total_evidence,
            }))
        })
        .collect();

    let id = format!("list_veracity:{}:{}", workspace_id, crate::now_micros(ctx));
    ctx.db.veracity_evidence_result().insert(VeracityEvidenceResult {
        id,
        workspace_id,
        result_json: serde_json::to_string(&results).unwrap_or_default(),
    });

    Ok(())
}

// ---------------------------------------------------------------------------
// Result table for query responses
// ---------------------------------------------------------------------------

/// Temporary table holding query results for veracity evidence.
#[table(accessor = veracity_evidence_result)]
#[derive(Debug, Clone)]
pub struct VeracityEvidenceResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub result_json: String,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // Pure Bayesian function tests (no SpacetimeDB needed)
    // -----------------------------------------------------------------------

    #[test]
    fn test_bayesian_confidence_default_prior() {
        // Beta(1,1) prior → confidence = 1/(1+1) = 0.5
        let c = bayesian_confidence(1.0, 1.0);
        assert!((c - 0.5).abs() < 1e-10);
    }

    #[test]
    fn test_bayesian_confidence_high_alpha() {
        // 10 confirmations, 1 contradiction → 10/11 ≈ 0.909
        let c = bayesian_confidence(10.0, 1.0);
        assert!((c - 10.0 / 11.0).abs() < 1e-10);
    }

    #[test]
    fn test_bayesian_confidence_low_alpha() {
        // 1 confirmation, 10 contradictions → 1/11 ≈ 0.0909
        let c = bayesian_confidence(1.0, 10.0);
        assert!((c - 1.0 / 11.0).abs() < 1e-10);
    }

    #[test]
    fn test_bayesian_confidence_zero_params() {
        // Edge case: no evidence → uniform prior
        let c = bayesian_confidence(0.0, 0.0);
        assert!((c - 0.5).abs() < 1e-10);
    }

    #[test]
    fn test_bayesian_update_positive() {
        let (a, b) = bayesian_update(1.0, 1.0, true, 0.5);
        assert!((a - 1.5).abs() < 1e-10);
        assert!((b - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_bayesian_update_negative() {
        let (a, b) = bayesian_update(1.0, 1.0, false, 0.5);
        assert!((a - 1.0).abs() < 1e-10);
        assert!((b - 1.5).abs() < 1e-10);
    }

    #[test]
    fn test_bayesian_update_zero_weight() {
        let (a, b) = bayesian_update(3.0, 2.0, true, 0.0);
        assert!((a - 3.0).abs() < 1e-10);
        assert!((b - 2.0).abs() < 1e-10);
    }

    #[test]
    fn test_bayesian_update_negative_weight_clamped() {
        let (a, b) = bayesian_update(3.0, 2.0, true, -1.0);
        assert!((a - 3.0).abs() < 1e-10); // same as zero weight
        assert!((b - 2.0).abs() < 1e-10);
    }

    #[test]
    fn test_bayesian_update_multiple() {
        // Simulate 3 confirmations of weight 0.5 each
        let (mut a, mut b) = (1.0, 1.0);
        let result = bayesian_update(a, b, true, 0.5);
        a = result.0; b = result.1;
        let result = bayesian_update(a, b, true, 0.5);
        a = result.0; b = result.1;
        let result = bayesian_update(a, b, true, 0.5);
        a = result.0; b = result.1;
        // a = 1 + 0.5 + 0.5 + 0.5 = 2.5, b = 1.0
        // confidence = 2.5 / (2.5 + 1.0) = 2.5 / 3.5 ≈ 0.714
        let c = bayesian_confidence(a, b);
        assert!((c - 2.5 / 3.5).abs() < 1e-10);
    }

    // -----------------------------------------------------------------------
    // Tier computation tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_tier_certain() {
        // confidence >= 0.90 AND evidence >= 10
        assert_eq!(compute_tier(0.95, 10.0), VeracityTier::Certain);
    }

    #[test]
    fn test_tier_certain_missing_evidence() {
        // High confidence but not enough evidence → HIGH (not CERTAIN)
        assert_eq!(compute_tier(0.95, 5.0), VeracityTier::High);
    }

    #[test]
    fn test_tier_high() {
        // confidence >= 0.80 AND evidence >= 3
        assert_eq!(compute_tier(0.85, 5.0), VeracityTier::High);
    }

    #[test]
    fn test_tier_medium() {
        // confidence >= 0.60 AND evidence >= 3
        assert_eq!(compute_tier(0.65, 4.0), VeracityTier::Medium);
    }

    #[test]
    fn test_tier_low() {
        // confidence >= 0.40
        assert_eq!(compute_tier(0.45, 1.0), VeracityTier::Low);
    }

    #[test]
    fn test_tier_speculative() {
        // confidence < 0.40
        assert_eq!(compute_tier(0.35, 0.0), VeracityTier::Speculative);
    }

    #[test]
    fn test_tier_edge_boundaries() {
        // At exact boundary: 0.90 confidence with 9 evidence → HIGH (not enough evidence)
        assert_eq!(compute_tier(0.90, 9.0), VeracityTier::High);
        // At exact boundary: 0.90 confidence with 10 evidence → CERTAIN
        assert_eq!(compute_tier(0.90, 10.0), VeracityTier::Certain);

        // At exact boundary: 0.80 confidence with 3 evidence → HIGH
        assert_eq!(compute_tier(0.80, 3.0), VeracityTier::High);
        // 0.79 confidence with 100 evidence → still low confidence, stays medium
        assert_eq!(compute_tier(0.79, 100.0), VeracityTier::Medium);
    }

    #[test]
    fn test_tier_full_progression() {
        // Start SPECULATIVE, progress through all tiers
        // Evidence 0, confidence 0.5
        assert_eq!(compute_tier(0.5, 0.0), VeracityTier::Low);

        // Evidence builds but not enough for HIGH yet
        assert_eq!(compute_tier(0.7, 2.0), VeracityTier::Low); // not enough evidence for MEDIUM

        // Enough evidence for MEDIUM
        assert_eq!(compute_tier(0.7, 3.0), VeracityTier::Medium);

        // High enough confidence for HIGH
        assert_eq!(compute_tier(0.85, 5.0), VeracityTier::High);

        // Very high confidence + lots of evidence → CERTAIN
        assert_eq!(compute_tier(0.95, 15.0), VeracityTier::Certain);
    }

    // -----------------------------------------------------------------------
    // Tier label tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_tier_labels() {
        assert_eq!(VeracityTier::Certain.label(), "CERTAIN");
        assert_eq!(VeracityTier::High.label(), "HIGH");
        assert_eq!(VeracityTier::Medium.label(), "MEDIUM");
        assert_eq!(VeracityTier::Low.label(), "LOW");
        assert_eq!(VeracityTier::Speculative.label(), "SPECULATIVE");
    }

    #[test]
    fn test_tier_from_label() {
        assert_eq!(VeracityTier::from_label("CERTAIN"), VeracityTier::Certain);
        assert_eq!(VeracityTier::from_label("HIGH"), VeracityTier::High);
        assert_eq!(VeracityTier::from_label("MEDIUM"), VeracityTier::Medium);
        assert_eq!(VeracityTier::from_label("LOW"), VeracityTier::Low);
        assert_eq!(VeracityTier::from_label("SPECULATIVE"), VeracityTier::Speculative);
        assert_eq!(VeracityTier::from_label("UNKNOWN_LABEL"), VeracityTier::Speculative);
    }

    #[test]
    fn test_tier_ordering() {
        assert!(VeracityTier::Certain > VeracityTier::High);
        assert!(VeracityTier::High > VeracityTier::Medium);
        assert!(VeracityTier::Medium > VeracityTier::Low);
        assert!(VeracityTier::Low > VeracityTier::Speculative);
    }

    // -----------------------------------------------------------------------
    // Edge cases
    // -----------------------------------------------------------------------

    #[test]
    fn test_bayesian_confidence_very_large() {
        // After very many updates, confidence should still be well-behaved
        let c = bayesian_confidence(1e6, 1e3);
        // ≈ 1000000/1001000 ≈ 0.999
        assert!(c > 0.99 && c < 1.0);
    }

    #[test]
    fn test_oscillating_evidence() {
        // Simulate alternating confirmations and contradictions
        let (mut a, mut b) = (1.0, 1.0);

        // Pattern: 3 confirms, 1 contradicts, 3 confirms
        for _ in 0..3 {
            let result = bayesian_update(a, b, true, 1.0);
            a = result.0; b = result.1;
        }
        let result = bayesian_update(a, b, false, 1.0);
        a = result.0; b = result.1;
        for _ in 0..3 {
            let result = bayesian_update(a, b, true, 1.0);
            a = result.0; b = result.1;
        }

        // a = 1 + 3 + 3 = 7, b = 1 + 1 = 2
        // confidence = 7/9 ≈ 0.778
        let c = bayesian_confidence(a, b);
        assert!((c - 7.0 / 9.0).abs() < 1e-10);
    }

    #[test]
    fn test_veracity_compounding_decay() {
        // Simulate many small confirmations (recall compounding)
        let (mut a, mut b) = (1.0, 1.0);

        for _ in 0..100 {
            let result = bayesian_update(a, b, true, 0.05);
            a = result.0; b = result.1;
        }

        // a = 1 + 100*0.05 = 6.0, b = 1.0
        // confidence ≈ 6/7 ≈ 0.857
        let c = bayesian_confidence(a, b);
        assert!((c - 6.0 / 7.0).abs() < 1e-10);

        // Total evidence (excluding prior): 6 + 1 - 2 = 5.0 → should be HIGH tier
        let total_evidence = a + b - 2.0;
        let tier = compute_tier(c, total_evidence);
        assert_eq!(tier, VeracityTier::High);
    }
}
