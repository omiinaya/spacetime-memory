use spacetimedb::*;

use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::{now_micros, uuid_v4_uniq};

// ---------------------------------------------------------------------------
// Observation table
// ---------------------------------------------------------------------------

/// An observation represents a discrete knowledge claim extracted from an
/// agent's experience — a fact, inference, or belief — with an associated
/// confidence level, evidence trail, and lifecycle status.
#[table(accessor = observation)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Observation {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The observation text content.
    pub content: String,
    /// A short summary / description of this observation.
    pub summary: String,
    /// JSON array of memory IDs serving as evidence for this observation.
    pub evidence_json: String,
    /// "fact" | "inference" | "belief"
    pub observation_type: String,
    /// Confidence score 0.0–1.0
    pub confidence: f64,
    /// "active" | "stale" | "superseded"
    pub status: String,
    /// If superseded, the observation ID that superseded this one.
    pub superseded_by: String,
    pub created_at: i64,
    pub updated_at: i64,
    /// Number of memory items in evidence_json (denormalised for fast filtering).
    pub memory_count: u32,
    /// Micros timestamp of last verification (0 = never verified).
    pub last_verified_at: i64,
}

// ---------------------------------------------------------------------------
// Result tables
// ---------------------------------------------------------------------------

/// Result table for `list_observations` queries.
/// Clients read from this table after calling the reducer.
#[table(accessor = observation_list_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ObservationListResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// JSON array of observation rows matching the query.
    pub json_data: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Observation reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_observation(
    ctx: &ReducerContext,
    workspace_id: String,
    content: String,
    summary: String,
    evidence_json: String,
    observation_type: String,
    confidence: f64,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "create_observation", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        // Validate observation_type
        match observation_type.as_str() {
            "fact" | "inference" | "belief" => {}
            _ => {
                return Err(format!(
                    "Invalid observation_type '{}': must be 'fact', 'inference', or 'belief'",
                    observation_type
                ));
            }
        }

        // Compute memory_count from evidence JSON array
        let memory_count: u32 = if evidence_json.is_empty() || evidence_json == "[]" {
            0
        } else {
            serde_json::from_str::<Vec<String>>(&evidence_json)
                .map(|v| v.len() as u32)
                .unwrap_or(0)
        };

        let id = uuid_v4_uniq(ctx, |id| ctx.db.observation().id().find(id).is_none(), 3);

        let obs = Observation {
            id: id.clone(),
            workspace_id,
            content,
            summary,
            evidence_json,
            observation_type,
            confidence,
            status: String::from("active"),
            superseded_by: String::new(),
            created_at: now,
            updated_at: now,
            memory_count,
            last_verified_at: now,
        };

        let obs_json = change_event::record_to_json(&obs);
        ctx.db.observation().insert(obs);
        change_event::log_change(ctx, &ws_id, "observation", "insert", &id, &obs_json);
        Ok(())
    })
}

#[reducer]
pub fn update_observation(
    ctx: &ReducerContext,
    id: String,
    content: String,
    summary: String,
    confidence: f64,
) -> Result<(), String> {
    trace_span!(ctx, "update_observation", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let mut obs = ctx
            .db
            .observation()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Observation '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &obs.workspace_id, &caller, "editor")?;
        let now = now_micros(ctx);

        if !content.is_empty() {
            obs.content = content;
        }
        if !summary.is_empty() {
            obs.summary = summary;
        }
        if confidence > 0.0 {
            obs.confidence = confidence;
        }
        obs.updated_at = now;

        let ws_id = obs.workspace_id.clone();
        let obs_id = obs.id.clone();
        let obs_json = change_event::record_to_json(&obs);
        ctx.db.observation().id().update(obs);
        change_event::log_change(ctx, &ws_id, "observation", "update", &obs_id, &obs_json);
        Ok(())
    })
}

#[reducer]
pub fn delete_observation(ctx: &ReducerContext, id: String) -> Result<(), String> {
    trace_span!(ctx, "delete_observation", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let obs = ctx
            .db
            .observation()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Observation '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &obs.workspace_id, &caller, "editor")?;

        let ws_id = obs.workspace_id.clone();
        let obs_id = obs.id.clone();
        let obs_json = change_event::record_to_json(&obs);
        ctx.db.observation().id().delete(&id);
        change_event::log_change(ctx, &ws_id, "observation", "delete", &obs_id, &obs_json);
        Ok(())
    })
}

#[reducer]
pub fn list_observations(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "list_observations", TracingSpanKind::Read, &ws_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        let observations: Vec<Observation> = ctx
            .db
            .observation()
            .workspace_id()
            .filter(&workspace_id)
            .take(crate::MAX_RESULTS)
            .collect();

        let json_data = serde_json::to_string(&observations).unwrap_or_else(|_| "[]".to_string());

        // Pre-cleanup: remove stale results for this workspace_id
        for old in ctx.db.observation_list_result()
            .iter()
            .filter(|r| r.workspace_id == workspace_id)
            .collect::<Vec<_>>()
        {
            ctx.db.observation_list_result().id().delete(&old.id);
        }

        let result_id = uuid_v4_uniq(
            ctx,
            |rid| ctx.db.observation_list_result().id().find(rid).is_none(),
            3,
        );
        ctx.db.observation_list_result().insert(ObservationListResult {
            id: result_id,
            workspace_id,
            json_data,
            created_at: now,
        });
        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_observation_initialization() {
        let obs = Observation {
            id: "obs_001".to_string(),
            workspace_id: "ws_001".to_string(),
            content: "The agent learned to navigate the maze in under 30 seconds.".to_string(),
            summary: "Agent maze navigation speed".to_string(),
            evidence_json: r#"["mem_001","mem_002"]"#.to_string(),
            observation_type: "fact".to_string(),
            confidence: 0.95,
            status: "active".to_string(),
            superseded_by: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
            memory_count: 2,
            last_verified_at: 1_000_000,
        };
        assert_eq!(obs.id, "obs_001");
        assert_eq!(obs.observation_type, "fact");
        assert_eq!(obs.status, "active");
        assert_eq!(obs.confidence, 0.95);
        assert_eq!(obs.memory_count, 2);
    }

    #[test]
    fn test_observation_status_transitions() {
        let obs = Observation {
            id: "obs_002".to_string(),
            workspace_id: "ws_001".to_string(),
            content: "Initial hypothesis about user intent.".to_string(),
            summary: "User intent hypothesis".to_string(),
            evidence_json: "[]".to_string(),
            observation_type: "inference".to_string(),
            confidence: 0.6,
            status: "active".to_string(),
            superseded_by: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
            memory_count: 0,
            last_verified_at: 1_000_000,
        };
        assert_eq!(obs.status, "active");

        // Simulate superseded
        let superseded = Observation {
            status: "superseded".to_string(),
            superseded_by: "obs_003".to_string(),
            ..obs
        };
        assert_eq!(superseded.status, "superseded");
        assert_eq!(superseded.superseded_by, "obs_003");

        // Simulate stale
        let stale = Observation {
            status: "stale".to_string(),
            ..superseded
        };
        assert_eq!(stale.status, "stale");
    }

    #[test]
    fn test_observation_serde_roundtrip() {
        let obs = Observation {
            id: "obs_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            content: "Serde test observation.".to_string(),
            summary: "Serde test".to_string(),
            evidence_json: "[]".to_string(),
            observation_type: "belief".to_string(),
            confidence: 0.7,
            status: "active".to_string(),
            superseded_by: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
            memory_count: 0,
            last_verified_at: 1_000_000,
        };
        let json = serde_json::to_string(&obs).expect("serialize");
        let deserialized: Observation = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, obs.id);
        assert_eq!(deserialized.observation_type, "belief");
        assert_eq!(deserialized.confidence, 0.7);
    }

    #[test]
    fn test_observation_type_variants() {
        for ot in &["fact", "inference", "belief"] {
            let obs = Observation {
                id: format!("obs_type_{}", ot),
                workspace_id: "ws".to_string(),
                content: format!("Type: {}", ot),
                summary: String::new(),
                evidence_json: String::new(),
                observation_type: ot.to_string(),
                confidence: 0.5,
                status: "active".to_string(),
                superseded_by: String::new(),
                created_at: 0,
                updated_at: 0,
                memory_count: 0,
                last_verified_at: 0,
            };
            assert_eq!(obs.observation_type, *ot);
        }
    }

    #[test]
    fn test_observation_list_result_initialization() {
        let r = ObservationListResult {
            id: "r_001".to_string(),
            workspace_id: "ws_001".to_string(),
            json_data: r#"[{"id":"obs_001"}]"#.to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(r.workspace_id, "ws_001");
        assert!(r.json_data.contains("obs_001"));
    }
}
