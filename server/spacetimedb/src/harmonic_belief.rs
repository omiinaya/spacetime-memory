use spacetimedb::*;
use crate::auth::require_auth;

use crate::trace_span;
use crate::{now_micros, uuid_v7};
use crate::tracing::TracingSpanKind;
use crate::workspace::check_space_access;

/// A harmonized belief produced by the SHMR resonance engine.
///
/// Beliefs are higher-order facts synthesized from memory clusters
/// through iterative resonance and contradiction resolution.
#[table(accessor = harmonic_belief)]
#[derive(Debug, Clone)]
pub struct HarmonicBelief {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// The subject entity (person, org, concept)
    pub subject: String,
    /// The predicate / relationship
    pub predicate: String,
    /// The object or value of the belief
    pub object: String,
    /// Bayesian confidence score [0.0, 1.0]
    pub confidence: f64,
    /// "create" | "update" | "dampen"
    pub action: String,
    /// JSON array of source memory IDs that fed this belief
    pub source_memory_ids_json: String,
    /// ID of the cluster that produced this belief
    pub cluster_id: String,
    /// Which resonance iteration produced this belief
    pub iteration: u32,
    /// One-sentence rationale from the LLM harmonizer
    pub rationale: String,
    /// Harmony score: how well this belief represents its cluster
    pub harmony_score: f64,
    pub created_at: i64,
}

/// Store a set of harmonized beliefs from one resonance round.
///
/// Called by the SDK-side SHMR engine after LLM harmonization.
/// Accepts a JSON array of belief objects so the entire resonance
/// round is stored atomically.
#[reducer]
pub fn store_harmonic_beliefs(
    ctx: &ReducerContext,
    workspace_id: String,
    _peer_id: String,
    beliefs_json: String,
    cluster_id: String,
    iteration: u32,
) -> Result<(), String> {
    trace_span!(ctx, "store_harmonic_beliefs", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);

    // Parse the JSON array of belief objects
    let beliefs: Vec<serde_json::Value> = serde_json::from_str(&beliefs_json)
        .map_err(|e| format!("Invalid beliefs_json: {}", e))?;

    for belief in &beliefs {
        let subject = belief
            .get("subject")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let predicate = belief
            .get("predicate")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let object = belief
            .get("object")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let confidence = belief
            .get("confidence")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.5);
        let action = belief
            .get("action")
            .and_then(|v| v.as_str())
            .unwrap_or("create")
            .to_string();
        let source_ids = belief
            .get("source_memory_ids")
            .map(|v| v.to_string())
            .unwrap_or_else(|| "[]".to_string());
        let rationale = belief
            .get("rationale")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let harmony_score = belief
            .get("harmony_score")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.5);

        let id = uuid_v7(ctx);

        ctx.db.harmonic_belief().insert(HarmonicBelief {
            id,
            workspace_id: workspace_id.clone(),
            subject,
            predicate,
            object,
            confidence,
            action,
            source_memory_ids_json: source_ids,
            cluster_id: cluster_id.clone(),
            iteration,
            rationale,
            harmony_score,
            created_at: now,
        });
    }

    Ok(())
})
}

/// Clear stale beliefs for a workspace (optional cleanup).
#[reducer]
pub fn clear_harmonic_beliefs(
    ctx: &ReducerContext,
    workspace_id: String,
    min_confidence: f64,
) -> Result<(), String> {
    trace_span!(ctx, "clear_harmonic_beliefs", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "admin")?;

    let to_delete: Vec<_> = ctx
        .db
        .harmonic_belief()
        .iter().take(crate::MAX_RESULTS)
        .filter(|b| b.workspace_id == workspace_id && b.confidence < min_confidence)
        .collect();

    for b in to_delete {
        ctx.db.harmonic_belief().id().delete(b.id);
    }

    Ok(())
})
}

/// Record a resonance session for monitoring/debugging.
#[table(accessor = resonance_log)]
#[derive(Debug, Clone)]
pub struct ResonanceLog {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub cluster_count: u32,
    pub beliefs_generated: u32,
    pub contradictions_resolved: u32,
    pub harmony_score_avg: f64,
    pub duration_ms: u64,
    pub created_at: i64,
}

#[reducer]
pub fn log_resonance_session(
    ctx: &ReducerContext,
    workspace_id: String,
    _peer_id: String,
    cluster_count: u32,
    beliefs_generated: u32,
    contradictions_resolved: u32,
    harmony_score_avg: f64,
    duration_ms: u64,
) -> Result<(), String> {
    trace_span!(ctx, "log_resonance_session", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);

    let id = uuid_v7(ctx);
    ctx.db.resonance_log().insert(ResonanceLog {
        id,
        workspace_id: workspace_id.clone(),
        cluster_count,
        beliefs_generated,
        contradictions_resolved,
        harmony_score_avg,
        duration_ms,
        created_at: now,
    });

    Ok(())
})
}