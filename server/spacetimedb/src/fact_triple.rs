use spacetimedb::*;

use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::{now_micros, uuid_v4_uniq};

// ---------------------------------------------------------------------------
// FactTriple table — structured knowledge claims with provenance
// ---------------------------------------------------------------------------

/// A structured fact in subject-predicate-object form with provenance
/// metadata: confidence, source, temporal bounds, and justification.
#[table(accessor = fact_triple)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct FactTriple {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The subject entity ID (links to knowledge graph node)
    pub subject_id: String,
    /// The predicate/relation type (e.g. "works_at", "located_in", "created_by")
    #[index(btree)]
    pub predicate: String,
    /// The object entity ID or literal value
    pub object_id: String,
    /// Whether object_id refers to a KG node ("entity") or a literal ("literal")
    pub object_type: String,
    /// Confidence score 0.0-1.0
    pub confidence: f64,
    /// Source identifier (user_id, connector name, LLM summary, etc.)
    pub source: String,
    /// Optional temporal bounds — unix micros when this fact was valid from/to
    pub valid_from: i64,
    pub valid_until: i64,
    /// Optional human-readable justification or evidence
    pub justification: String,
    pub created_at: i64,
    pub updated_at: i64,
}

// ---------------------------------------------------------------------------
// Result tables
// ---------------------------------------------------------------------------

/// Result table for `list_fact_triples` queries.
/// Clients read from this table after calling the reducer.
#[table(accessor = fact_triple_list_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct FactTripleListResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// JSON array of fact triple rows matching the query.
    pub json_data: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// FactTriple reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn store_fact_triple(
    ctx: &ReducerContext,
    workspace_id: String,
    subject_id: String,
    predicate: String,
    object_id: String,
    object_type: String,
    confidence: f64,
    source: String,
    justification: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "store_fact_triple", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);
        let id = uuid_v4_uniq(ctx, |id| ctx.db.fact_triple().id().find(id).is_none(), 3);

        // Validate confidence range
        let confidence = confidence.clamp(0.0, 1.0);

        // Validate object_type
        let object_type = match object_type.as_str() {
            "entity" | "literal" => object_type,
            _ => {
                return Err(format!(
                    "Invalid object_type '{}' — must be 'entity' or 'literal'",
                    object_type
                ));
            }
        };

        let fact = FactTriple {
            id: id.clone(),
            workspace_id,
            subject_id,
            predicate,
            object_id,
            object_type,
            confidence,
            source,
            valid_from: 0,
            valid_until: 0,
            justification,
            created_at: now,
            updated_at: now,
        };

        let fact_json = change_event::record_to_json(&fact);
        ctx.db.fact_triple().insert(fact);
        change_event::log_change(ctx, &ws_id, "fact_triple", "insert", &id, &fact_json);
        Ok(())
    })
}

#[reducer]
pub fn update_fact_triple_confidence(
    ctx: &ReducerContext,
    id: String,
    confidence: f64,
    justification: String,
) -> Result<(), String> {
    trace_span!(ctx, "update_fact_triple_confidence", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let mut fact = ctx
            .db
            .fact_triple()
            .id()
            .find(&id)
            .ok_or_else(|| format!("FactTriple '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &fact.workspace_id, &caller, "editor")?;
        let now = now_micros(ctx);
        let confidence = confidence.clamp(0.0, 1.0);

        fact.confidence = confidence;
        if !justification.is_empty() {
            fact.justification = justification;
        }
        fact.updated_at = now;

        let ws_id = fact.workspace_id.clone();
        let fact_id = fact.id.clone();
        let fact_json = change_event::record_to_json(&fact);
        ctx.db.fact_triple().id().update(fact);
        change_event::log_change(ctx, &ws_id, "fact_triple", "update", &fact_id, &fact_json);
        Ok(())
    })
}

#[reducer]
pub fn delete_fact_triple(
    ctx: &ReducerContext,
    id: String,
) -> Result<(), String> {
    trace_span!(ctx, "delete_fact_triple", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let fact = ctx
            .db
            .fact_triple()
            .id()
            .find(&id)
            .ok_or_else(|| format!("FactTriple '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &fact.workspace_id, &caller, "editor")?;

        let ws_id = fact.workspace_id.clone();
        let fact_id = fact.id.clone();
        let fact_json = change_event::record_to_json(&fact);
        ctx.db.fact_triple().id().delete(&id);
        change_event::log_change(ctx, &ws_id, "fact_triple", "delete", &fact_id, &fact_json);
        Ok(())
    })
}

#[reducer]
pub fn set_fact_triple_temporal_bounds(
    ctx: &ReducerContext,
    id: String,
    valid_from: i64,
    valid_until: i64,
) -> Result<(), String> {
    trace_span!(ctx, "set_fact_triple_temporal_bounds", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let mut fact = ctx
            .db
            .fact_triple()
            .id()
            .find(&id)
            .ok_or_else(|| format!("FactTriple '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &fact.workspace_id, &caller, "editor")?;
        let now = now_micros(ctx);

        fact.valid_from = valid_from;
        fact.valid_until = valid_until;
        fact.updated_at = now;

        let ws_id = fact.workspace_id.clone();
        let fact_id = fact.id.clone();
        let fact_json = change_event::record_to_json(&fact);
        ctx.db.fact_triple().id().update(fact);
        change_event::log_change(ctx, &ws_id, "fact_triple", "update", &fact_id, &fact_json);
        Ok(())
    })
}

#[reducer]
pub fn list_fact_triples(
    ctx: &ReducerContext,
    workspace_id: String,
    predicate: String,
    subject_id: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "list_fact_triples", TracingSpanKind::Read, &ws_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        let results: Vec<FactTriple> = ctx
            .db
            .fact_triple()
            .iter()
            .filter(|f| {
                if f.workspace_id != workspace_id {
                    return false;
                }
                if !predicate.is_empty() && f.predicate != predicate {
                    return false;
                }
                if !subject_id.is_empty() && f.subject_id != subject_id {
                    return false;
                }
                true
            })
            .take(crate::MAX_RESULTS)
            .collect();

        let json_data = serde_json::to_string(&results).unwrap_or_else(|_| "[]".to_string());

        // Pre-cleanup: remove stale results for this workspace_id
        for old in ctx
            .db
            .fact_triple_list_result()
            .iter()
            .filter(|r| r.workspace_id == workspace_id)
            .collect::<Vec<_>>()
        {
            ctx.db
                .fact_triple_list_result()
                .id()
                .delete(&old.id);
        }

        let result_id = uuid_v4_uniq(
            ctx,
            |rid| ctx.db.fact_triple_list_result().id().find(rid).is_none(),
            3,
        );
        ctx.db
            .fact_triple_list_result()
            .insert(FactTripleListResult {
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
    fn test_fact_triple_initialization() {
        let fact = FactTriple {
            id: "ft_001".to_string(),
            workspace_id: "ws_001".to_string(),
            subject_id: "subj_001".to_string(),
            predicate: "works_at".to_string(),
            object_id: "obj_001".to_string(),
            object_type: "entity".to_string(),
            confidence: 0.95,
            source: "llm_summary".to_string(),
            valid_from: 1_000_000,
            valid_until: 2_000_000,
            justification: "Extracted from conversation history.".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(fact.id, "ft_001");
        assert_eq!(fact.predicate, "works_at");
        assert_eq!(fact.object_type, "entity");
        assert_eq!(fact.confidence, 0.95);
        assert_eq!(fact.source, "llm_summary");
    }

    #[test]
    fn test_fact_triple_literal_object_type() {
        let fact = FactTriple {
            id: "ft_002".to_string(),
            workspace_id: "ws_001".to_string(),
            subject_id: "subj_001".to_string(),
            predicate: "has_age".to_string(),
            object_id: "42".to_string(),
            object_type: "literal".to_string(),
            confidence: 1.0,
            source: "user_input".to_string(),
            valid_from: 0,
            valid_until: 0,
            justification: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(fact.object_type, "literal");
        assert_eq!(fact.object_id, "42");
    }

    #[test]
    fn test_fact_triple_confidence_clamping_high() {
        let mut fact = FactTriple {
            id: "ft_003".to_string(),
            workspace_id: "ws_001".to_string(),
            subject_id: "subj_001".to_string(),
            predicate: "knows".to_string(),
            object_id: "obj_002".to_string(),
            object_type: "entity".to_string(),
            confidence: 1.5,
            source: "test".to_string(),
            valid_from: 0,
            valid_until: 0,
            justification: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        // Manually clamp (replicating reducer logic)
        fact.confidence = fact.confidence.clamp(0.0, 1.0);
        assert_eq!(fact.confidence, 1.0);
    }

    #[test]
    fn test_fact_triple_confidence_clamping_low() {
        let mut fact = FactTriple {
            id: "ft_004".to_string(),
            workspace_id: "ws_001".to_string(),
            subject_id: "subj_001".to_string(),
            predicate: "knows".to_string(),
            object_id: "obj_002".to_string(),
            object_type: "entity".to_string(),
            confidence: -0.5,
            source: "test".to_string(),
            valid_from: 0,
            valid_until: 0,
            justification: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        fact.confidence = fact.confidence.clamp(0.0, 1.0);
        assert_eq!(fact.confidence, 0.0);
    }

    #[test]
    fn test_fact_triple_serde_roundtrip() {
        let fact = FactTriple {
            id: "ft_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            subject_id: "subj_serde".to_string(),
            predicate: "located_in".to_string(),
            object_id: "obj_serde".to_string(),
            object_type: "entity".to_string(),
            confidence: 0.85,
            source: "test".to_string(),
            valid_from: 0,
            valid_until: 0,
            justification: "Serde roundtrip test".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        let json = serde_json::to_string(&fact).expect("serialize");
        let deserialized: FactTriple = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, fact.id);
        assert_eq!(deserialized.predicate, "located_in");
        assert_eq!(deserialized.confidence, 0.85);
    }

    #[test]
    fn test_fact_triple_temporal_bounds() {
        let fact = FactTriple {
            id: "ft_temp".to_string(),
            workspace_id: "ws_temp".to_string(),
            subject_id: "subj_temp".to_string(),
            predicate: "employed_by".to_string(),
            object_id: "obj_temp".to_string(),
            object_type: "entity".to_string(),
            confidence: 0.9,
            source: "hr_system".to_string(),
            valid_from: 1_000_000,
            valid_until: 2_000_000,
            justification: "Employment period verified.".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(fact.valid_from, 1_000_000);
        assert_eq!(fact.valid_until, 2_000_000);
        assert!(fact.valid_from < fact.valid_until);
    }

    #[test]
    fn test_fact_triple_list_result_initialization() {
        let r = FactTripleListResult {
            id: "r_ft_001".to_string(),
            workspace_id: "ws_001".to_string(),
            json_data: r#"[{"id":"ft_001","predicate":"works_at"}]"#.to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(r.workspace_id, "ws_001");
        assert!(r.json_data.contains("ft_001"));
    }

    // -----------------------------------------------------------------------
    // Additional edge case tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_fact_triple_empty_strings() {
        let fact = FactTriple {
            id: "ft_empty".to_string(),
            workspace_id: String::new(),
            subject_id: String::new(),
            predicate: String::new(),
            object_id: String::new(),
            object_type: "literal".to_string(),
            confidence: 0.5,
            source: String::new(),
            valid_from: 0,
            valid_until: 0,
            justification: String::new(),
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(fact.workspace_id, "");
        assert_eq!(fact.subject_id, "");
        assert_eq!(fact.predicate, "");
        assert_eq!(fact.object_id, "");
        assert_eq!(fact.source, "");
    }

    #[test]
    fn test_fact_triple_zero_confidence() {
        let fact = FactTriple {
            id: "ft_zero_conf".to_string(),
            workspace_id: "ws".to_string(),
            subject_id: "subj".to_string(),
            predicate: "knows".to_string(),
            object_id: "obj".to_string(),
            object_type: "entity".to_string(),
            confidence: 0.0,
            source: "test".to_string(),
            valid_from: 0,
            valid_until: 0,
            justification: String::new(),
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(fact.confidence, 0.0);
    }

    #[test]
    fn test_fact_triple_max_confidence() {
        let fact = FactTriple {
            id: "ft_max_conf".to_string(),
            workspace_id: "ws".to_string(),
            subject_id: "subj".to_string(),
            predicate: "knows".to_string(),
            object_id: "obj".to_string(),
            object_type: "entity".to_string(),
            confidence: 1.0,
            source: "test".to_string(),
            valid_from: 0,
            valid_until: 0,
            justification: String::new(),
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(fact.confidence, 1.0);
    }

    #[test]
    fn test_fact_triple_temporal_bounds_equal() {
        // valid_from == valid_until is allowed (instantaneous fact)
        let fact = FactTriple {
            id: "ft_eq_temp".to_string(),
            workspace_id: "ws".to_string(),
            subject_id: "subj".to_string(),
            predicate: "momentary".to_string(),
            object_id: "obj".to_string(),
            object_type: "literal".to_string(),
            confidence: 0.8,
            source: "test".to_string(),
            valid_from: 5_000_000,
            valid_until: 5_000_000,
            justification: String::new(),
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(fact.valid_from, fact.valid_until);
    }

    #[test]
    fn test_fact_triple_long_justification() {
        let long_just = "x".repeat(10_000);
        let fact = FactTriple {
            id: "ft_long".to_string(),
            workspace_id: "ws".to_string(),
            subject_id: "subj".to_string(),
            predicate: "described_by".to_string(),
            object_id: "obj".to_string(),
            object_type: "literal".to_string(),
            confidence: 0.5,
            source: "test".to_string(),
            valid_from: 0,
            valid_until: 0,
            justification: long_just.clone(),
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(fact.justification.len(), 10_000);
        assert!(fact.justification.contains(&long_just));
    }

    #[test]
    fn test_fact_triple_clone_maintains_fields() {
        let fact = FactTriple {
            id: "ft_clone".to_string(),
            workspace_id: "ws".to_string(),
            subject_id: "subj".to_string(),
            predicate: "pred".to_string(),
            object_id: "obj".to_string(),
            object_type: "entity".to_string(),
            confidence: 0.75,
            source: "src".to_string(),
            valid_from: 10,
            valid_until: 20,
            justification: "just".to_string(),
            created_at: 5,
            updated_at: 5,
        };
        let cloned = fact.clone();
        assert_eq!(cloned.id, fact.id);
        assert_eq!(cloned.confidence, fact.confidence);
        assert_eq!(cloned.valid_from, fact.valid_from);
        assert_eq!(cloned.valid_until, fact.valid_until);
    }

    #[test]
    fn test_fact_triple_debug_format() {
        let fact = FactTriple {
            id: "ft_debug".to_string(),
            workspace_id: "ws".to_string(),
            subject_id: "subj".to_string(),
            predicate: "test_predicate".to_string(),
            object_id: "obj".to_string(),
            object_type: "entity".to_string(),
            confidence: 0.5,
            source: "test".to_string(),
            valid_from: 0,
            valid_until: 0,
            justification: "debug test".to_string(),
            created_at: 0,
            updated_at: 0,
        };
        let debug = format!("{:?}", fact);
        assert!(debug.contains("ft_debug"));
        assert!(debug.contains("test_predicate"));
        assert!(debug.contains("debug test"));
    }

    #[test]
    fn test_fact_triple_list_result_serde_roundtrip() {
        let r = FactTripleListResult {
            id: "r_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            json_data: r#"[{"id":"ft_1","predicate":"p1"}]"#.to_string(),
            created_at: 100_000,
        };
        let json = serde_json::to_string(&r).expect("serialize list result");
        let deserialized: FactTripleListResult =
            serde_json::from_str(&json).expect("deserialize list result");
        assert_eq!(deserialized.id, r.id);
        assert_eq!(deserialized.workspace_id, r.workspace_id);
        assert_eq!(deserialized.json_data, r.json_data);
    }

    #[test]
    fn test_fact_triple_list_result_empty_json() {
        let r = FactTripleListResult {
            id: "r_empty".to_string(),
            workspace_id: "ws".to_string(),
            json_data: "[]".to_string(),
            created_at: 0,
        };
        assert_eq!(r.json_data, "[]");
        let parsed: Vec<serde_json::Value> =
            serde_json::from_str(&r.json_data).expect("valid JSON array");
        assert!(parsed.is_empty());
    }
}
