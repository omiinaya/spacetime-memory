use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v4_uniq};
use crate::trace_span;
use crate::tracing::TracingSpanKind;

/// A profile accumulates static facts and dynamic context about a peer.
#[table(accessor = profile)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Profile {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub peer_id: String,
    /// JSON array of stable facts
    pub static_facts_json: String,
    /// JSON array of recent activity / dynamic context
    pub dynamic_context_json: String,
    /// JSON object of preferences
    pub preferences_json: String,
    /// JSON array of tags
    pub tags_json: String,
    pub updated_at: i64,
}

#[reducer]
pub fn upsert_profile(
    ctx: &ReducerContext,
    peer_id: String,
    static_facts_json: String,
    dynamic_context_json: String,
    preferences_json: String,
    tags_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "upsert_profile", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        // Attempt to find existing profile for this peer
        let existing = ctx.db.profile().peer_id().filter(&peer_id).find(|p| p.peer_id == peer_id);

        if let Some(mut p) = existing {
            p.static_facts_json = static_facts_json;
            p.dynamic_context_json = dynamic_context_json;
            p.preferences_json = preferences_json;
            p.tags_json = tags_json;
            p.updated_at = now;
            ctx.db.profile().id().update(p);
        } else {
            // Create new profile
            let id = uuid_v4_uniq(ctx, |id| ctx.db.profile().id().find(id).is_none(), 3);
            let p = Profile {
                id: id.clone(),
                peer_id,
                static_facts_json,
                dynamic_context_json,
                preferences_json,
                tags_json,
                updated_at: now,
            };
            ctx.db.profile().insert(p);
        }

        Ok(())
    })
}

#[reducer]
pub fn add_profile_fact(ctx: &ReducerContext, peer_id: String, fact: String) -> Result<(), String> {
    trace_span!(ctx, "add_profile_fact", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        let existing = ctx.db.profile().peer_id().filter(&peer_id).find(|p| p.peer_id == peer_id);

        if let Some(mut p) = existing {
            // Append fact to static_facts_json array — use serde_json for safety
            let mut facts: Vec<String> = match serde_json::from_str(&p.static_facts_json) {
                Ok(v) => v,
                Err(e) => {
                    log::info!("Failed to parse static_facts_json: {}", e);
                    Vec::new()
                }
            };
            facts.push(fact);
            p.static_facts_json = serde_json::to_string(&facts).unwrap_or_else(|_| "[]".to_string());
            p.updated_at = now;
            ctx.db.profile().id().update(p);
        } else {
            // Create a new profile with just this fact
            let id = uuid_v4_uniq(ctx, |id| ctx.db.profile().id().find(id).is_none(), 3);
            let facts = format!("[\"{}\"]", fact.replace('"', "\\\""));
            let p = Profile {
                id: id.clone(),
                peer_id,
                static_facts_json: facts,
                dynamic_context_json: String::from("[]"),
                preferences_json: String::from("{}"),
                tags_json: String::from("[]"),
                updated_at: now,
            };
            ctx.db.profile().insert(p);
        }

        Ok(())
    })
}

#[reducer]
pub fn add_dynamic_context(
    ctx: &ReducerContext,
    peer_id: String,
    context: String,
) -> Result<(), String> {
    trace_span!(ctx, "add_dynamic_context", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        let existing = ctx.db.profile().peer_id().filter(&peer_id).find(|p| p.peer_id == peer_id);

        if let Some(mut p) = existing {
            // Append context entry to dynamic_context_json — use serde_json for safety
            let mut entries: Vec<String> = match serde_json::from_str(&p.dynamic_context_json) {
                Ok(v) => v,
                Err(e) => {
                    log::info!("Failed to parse dynamic_context_json: {}", e);
                    Vec::new()
                }
            };
            entries.push(context);
            p.dynamic_context_json = serde_json::to_string(&entries).unwrap_or_else(|_| "[]".to_string());
            p.updated_at = now;
            ctx.db.profile().id().update(p);
        } else {
            // Create a new profile with just this context entry
            let id = uuid_v4_uniq(ctx, |id| ctx.db.profile().id().find(id).is_none(), 3);
            let context_entry = serde_json::to_string(&vec![&context]).unwrap_or_else(|_| "[]".to_string());
            let p = Profile {
                id: id.clone(),
                peer_id,
                static_facts_json: String::from("[]"),
                dynamic_context_json: context_entry,
                preferences_json: String::from("{}"),
                tags_json: String::from("[]"),
                updated_at: now,
            };
            ctx.db.profile().insert(p);
        }

        Ok(())
    })
}

// =========================================================================
// Fact table — peer facts (Facts project parity)
// =========================================================================

/// A static or dynamic fact about a peer (Facts project parity).
#[table(accessor = fact)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Fact {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub peer_id: String,
    pub fact_type: String, // "static" or "dynamic"
    pub category: String, // "preference", "behavior", "knowledge", "relationship", "custom"
    pub content: String,
    pub confidence: f64,
    pub source: String, // "manual", "extracted", "inferred", "imported"
    pub tier: String, // "L0", "L1", "L2"
    pub is_active: bool,
    pub created_at: i64,
    pub expires_at: i64,
    pub updated_at: i64,
}

/// Result table for list_facts / search_facts queries.
#[table(accessor = fact_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct FactResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub query_hash: String,
    pub json_data: String,
    pub created_at: i64,
}

/// Compute the expiry offset in microseconds for a given memory tier.
/// L0 = 30 days, L1 = 90 days, L2 = 365 days. Unknown tiers default to 90 days.
fn tier_expires_offset(tier: &str) -> i64 {
    match tier {
        "L0" => 30 * 86400 * 1_000_000_i64,
        "L1" => 90 * 86400 * 1_000_000_i64,
        "L2" => 365 * 86400 * 1_000_000_i64,
        _ => 90 * 86400 * 1_000_000_i64,
    }
}

// -------------------------------------------------------------------------
// Fact reducers
// -------------------------------------------------------------------------

#[reducer]
pub fn add_fact(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
    fact_type: String,
    category: String,
    content: String,
    confidence: f64,
    source: String,
    tier: String,
) -> Result<(), String> {
    trace_span!(ctx, "add_fact", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);
        let id = uuid_v4_uniq(ctx, |id| ctx.db.fact().id().find(id).is_none(), 3);

        // Determine expires_at using the tier-based offset
        let expires_offset = tier_expires_offset(&tier);

        let fact = Fact {
            id,
            workspace_id: workspace_id.clone(),
            peer_id,
            fact_type,
            category,
            content,
            confidence,
            source,
            tier,
            is_active: true,
            created_at: now,
            expires_at: now + expires_offset,
            updated_at: now,
        };
        ctx.db.fact().insert(fact);
        Ok(())
    })
}

#[reducer]
pub fn update_fact(
    ctx: &ReducerContext,
    fact_id: String,
    content: String,
    confidence: f64,
    category: String,
    tier: String,
) -> Result<(), String> {
    trace_span!(ctx, "update_fact", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);
        let existing = ctx.db.fact().id().find(&fact_id);

        match existing {
            Some(mut fact) => {
                if !content.is_empty() {
                    fact.content = content;
                }
                if confidence > 0.0 {
                    fact.confidence = confidence;
                }
                if !category.is_empty() {
                    fact.category = category;
                }
                if !tier.is_empty() {
                    fact.tier = tier;
                    // Recompute expires_at based on new tier
                    let expires_offset = tier_expires_offset(&fact.tier);
                    fact.expires_at = now + expires_offset;
                }
                fact.updated_at = now;
                ctx.db.fact().id().update(fact);
                Ok(())
            }
            None => Err(format!("Fact '{}' not found", fact_id)),
        }
    })
}

#[reducer]
pub fn delete_fact(ctx: &ReducerContext, fact_id: String) -> Result<(), String> {
    trace_span!(ctx, "delete_fact", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);
        let existing = ctx.db.fact().id().find(&fact_id);

        match existing {
            Some(mut fact) => {
                fact.is_active = false;
                fact.updated_at = now;
                ctx.db.fact().id().update(fact);
                Ok(())
            }
            None => Err(format!("Fact '{}' not found", fact_id)),
        }
    })
}

#[reducer]
pub fn list_facts(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
    fact_type: String,
    tier: String,
    category: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let facts: Vec<Fact> = ctx
        .db
        .fact()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
        .filter(|f| {
            if !f.is_active {
                return false;
            }
            if !peer_id.is_empty() && f.peer_id != peer_id {
                return false;
            }
            if !fact_type.is_empty() && f.fact_type != fact_type {
                return false;
            }
            if !tier.is_empty() && f.tier != tier {
                return false;
            }
            if !category.is_empty() && f.category != category {
                return false;
            }
            true
        })
        .collect();

    let json_data = serde_json::to_string(&facts).unwrap_or_else(|_| "[]".to_string());
    let query_hash = format!("{}:{}:{}:{}:{}", workspace_id, peer_id, fact_type, tier, category);
    let result_id = uuid_v4_uniq(ctx, |id| ctx.db.fact_result().id().find(id).is_none(), 3);

    // Pre-cleanup: remove stale results for this workspace_id + query_hash
    for old in ctx.db.fact_result().iter()
        .filter(|r| r.workspace_id == workspace_id && r.query_hash == query_hash)
        .collect::<Vec<_>>()
    {
        ctx.db.fact_result().id().delete(&old.id);
    }
    let result = FactResult {
        id: result_id,
        workspace_id,
        query_hash,
        json_data,
        created_at: now,
    };
    ctx.db.fact_result().insert(result);
    Ok(())
}

#[reducer]
pub fn search_facts(
    ctx: &ReducerContext,
    workspace_id: String,
    query: String,
    tier: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let query_lower = query.to_lowercase();
    let facts: Vec<Fact> = ctx
        .db
        .fact()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
        .filter(|f| {
            if !f.is_active {
                return false;
            }
            if !tier.is_empty() && f.tier != tier {
                return false;
            }
            f.content.to_lowercase().contains(&query_lower)
        })
        .collect();

    let json_data = serde_json::to_string(&facts).unwrap_or_else(|_| "[]".to_string());
    let result_id = uuid_v4_uniq(ctx, |id| ctx.db.fact_result().id().find(id).is_none(), 3);

    // Pre-cleanup: remove stale results for this workspace_id + query_hash
    for old in ctx.db.fact_result().iter()
        .filter(|r| r.workspace_id == workspace_id && r.query_hash == format!("search:{}:{}", query, tier))
        .collect::<Vec<_>>()
    {
        ctx.db.fact_result().id().delete(&old.id);
    }
    let result = FactResult {
        id: result_id,
        workspace_id,
        query_hash: format!("search:{}:{}", query, tier),
        json_data,
        created_at: now,
    };
    ctx.db.fact_result().insert(result);
    Ok(())
}

// -------------------------------------------------------------------------
// Unit tests
// -------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // tier_expires_offset
    // -----------------------------------------------------------------------

    #[test]
    fn test_tier_expires_offset_l0() {
        let got = tier_expires_offset("L0");
        assert_eq!(got, 30 * 86400 * 1_000_000_i64);
    }

    #[test]
    fn test_tier_expires_offset_l1() {
        let got = tier_expires_offset("L1");
        assert_eq!(got, 90 * 86400 * 1_000_000_i64);
    }

    #[test]
    fn test_tier_expires_offset_l2() {
        let got = tier_expires_offset("L2");
        assert_eq!(got, 365 * 86400 * 1_000_000_i64);
    }

    #[test]
    fn test_tier_expires_offset_default() {
        let got = tier_expires_offset("L3");
        assert_eq!(got, 90 * 86400 * 1_000_000_i64);
    }

    #[test]
    fn test_tier_expires_offset_empty_string() {
        let got = tier_expires_offset("");
        assert_eq!(got, 90 * 86400 * 1_000_000_i64);
    }

    #[test]
    fn test_tier_expires_offset_case_sensitive() {
        let got = tier_expires_offset("l0");
        assert_eq!(got, 90 * 86400 * 1_000_000_i64);
    }

    #[test]
    fn test_tier_expires_offset_monotonicity() {
        let l0 = tier_expires_offset("L0");
        let l1 = tier_expires_offset("L1");
        let l2 = tier_expires_offset("L2");
        assert!(l0 < l1, "L0 expiry must be shorter than L1");
        assert!(l1 < l2, "L1 expiry must be shorter than L2");
    }

    #[test]
    fn test_tier_expires_offset_no_overflow() {
        let l2 = tier_expires_offset("L2");
        assert!(l2 > 0, "L2 offset must be positive");
        assert!(l2 < i64::MAX / 2, "L2 offset should not be near i64::MAX");
    }

    // -----------------------------------------------------------------------
    // Profile struct
    // -----------------------------------------------------------------------

    #[test]
    fn test_profile_initialization() {
        let p = Profile {
            id: "prof_001".to_string(),
            peer_id: "peer_abc".to_string(),
            static_facts_json: r#"["speaks English","loves Rust"]"#.to_string(),
            dynamic_context_json: r#"["last seen in #general"]"#.to_string(),
            preferences_json: r#"{"theme":"dark","language":"en"}"#.to_string(),
            tags_json: r#"["developer","rustacean"]"#.to_string(),
            updated_at: 1_000_000,
        };
        assert_eq!(p.id, "prof_001");
        assert_eq!(p.peer_id, "peer_abc");
        assert!(p.static_facts_json.contains("speaks English"));
        assert!(p.dynamic_context_json.contains("last seen"));
        assert!(p.preferences_json.contains("dark"));
        assert!(p.tags_json.contains("rustacean"));
    }

    #[test]
    fn test_profile_empty_json_fields() {
        let p = Profile {
            id: "prof_empty".to_string(),
            peer_id: "peer_empty".to_string(),
            static_facts_json: "[]".to_string(),
            dynamic_context_json: "[]".to_string(),
            preferences_json: "{}".to_string(),
            tags_json: "[]".to_string(),
            updated_at: 0,
        };
        assert_eq!(p.static_facts_json, "[]");
        assert_eq!(p.dynamic_context_json, "[]");
        assert_eq!(p.preferences_json, "{}");
        assert_eq!(p.tags_json, "[]");
    }

    #[test]
    fn test_profile_serde_roundtrip() {
        let p = Profile {
            id: "prof_serde".to_string(),
            peer_id: "peer_serde".to_string(),
            static_facts_json: r#"["fact1","fact2"]"#.to_string(),
            dynamic_context_json: r#"["ctx1"]"#.to_string(),
            preferences_json: r#"{"key":"val"}"#.to_string(),
            tags_json: r#"["tag1","tag2","tag3"]"#.to_string(),
            updated_at: 2_000_000,
        };
        let json = serde_json::to_string(&p).expect("serialize Profile");
        let deserialized: Profile = serde_json::from_str(&json).expect("deserialize Profile");
        assert_eq!(deserialized.id, p.id);
        assert_eq!(deserialized.peer_id, p.peer_id);
        assert_eq!(deserialized.static_facts_json, p.static_facts_json);
        assert_eq!(deserialized.dynamic_context_json, p.dynamic_context_json);
        assert_eq!(deserialized.preferences_json, p.preferences_json);
        assert_eq!(deserialized.tags_json, p.tags_json);
        assert_eq!(deserialized.updated_at, p.updated_at);
    }

    #[test]
    fn test_profile_clone_maintains_all_fields() {
        let p = Profile {
            id: "prof_clone".to_string(),
            peer_id: "peer_clone".to_string(),
            static_facts_json: "[]".to_string(),
            dynamic_context_json: "[]".to_string(),
            preferences_json: "{}".to_string(),
            tags_json: "[]".to_string(),
            updated_at: 42,
        };
        let cloned = p.clone();
        assert_eq!(cloned.id, p.id);
        assert_eq!(cloned.peer_id, p.peer_id);
        assert_eq!(cloned.updated_at, 42);
    }

    #[test]
    fn test_profile_debug_format() {
        let p = Profile {
            id: "prof_debug".to_string(),
            peer_id: "peer_debug".to_string(),
            static_facts_json: "[]".to_string(),
            dynamic_context_json: "[]".to_string(),
            preferences_json: "{}".to_string(),
            tags_json: "[]".to_string(),
            updated_at: 0,
        };
        let debug = format!("{:?}", p);
        assert!(debug.contains("prof_debug"));
        assert!(debug.contains("peer_debug"));
    }

    #[test]
    fn test_profile_large_json_fields() {
        let large_fact = "x".repeat(10_000);
        let large_json = format!(r#"["{}"]"#, large_fact);
        let p = Profile {
            id: "prof_large".to_string(),
            peer_id: "peer_large".to_string(),
            static_facts_json: large_json.clone(),
            dynamic_context_json: "[]".to_string(),
            preferences_json: "{}".to_string(),
            tags_json: "[]".to_string(),
            updated_at: 1,
        };
        assert!(p.static_facts_json.len() > 10_000);
        assert!(p.static_facts_json.contains(&large_fact));
    }

    #[test]
    fn test_profile_preferences_json_variants() {
        let empty_obj = Profile {
            id: "p1".to_string(),
            peer_id: "peer".to_string(),
            static_facts_json: "[]".to_string(),
            dynamic_context_json: "[]".to_string(),
            preferences_json: "{}".to_string(),
            tags_json: "[]".to_string(),
            updated_at: 0,
        };
        assert_eq!(empty_obj.preferences_json, "{}");

        let with_prefs = Profile {
            id: "p2".to_string(),
            peer_id: "peer".to_string(),
            static_facts_json: "[]".to_string(),
            dynamic_context_json: "[]".to_string(),
            preferences_json: r#"{"theme":"light","notifications":true}"#.to_string(),
            tags_json: "[]".to_string(),
            updated_at: 0,
        };
        assert!(with_prefs.preferences_json.contains("theme"));
        assert!(with_prefs.preferences_json.contains("light"));
    }

    // -----------------------------------------------------------------------
    // Fact struct
    // -----------------------------------------------------------------------

    #[test]
    fn test_fact_initialization() {
        let fact = Fact {
            id: "fact_001".to_string(),
            workspace_id: "ws_001".to_string(),
            peer_id: "peer_001".to_string(),
            fact_type: "static".to_string(),
            category: "knowledge".to_string(),
            content: "Alice knows Rust".to_string(),
            confidence: 0.95,
            source: "manual".to_string(),
            tier: "L1".to_string(),
            is_active: true,
            created_at: 1_000_000,
            expires_at: 8_776_000_000_000_i64,
            updated_at: 1_000_000,
        };
        assert_eq!(fact.id, "fact_001");
        assert_eq!(fact.fact_type, "static");
        assert_eq!(fact.category, "knowledge");
        assert_eq!(fact.content, "Alice knows Rust");
        assert_eq!(fact.confidence, 0.95);
        assert_eq!(fact.source, "manual");
        assert_eq!(fact.tier, "L1");
        assert!(fact.is_active);
    }

    #[test]
    fn test_fact_all_types_and_categories() {
        for fact_type in &["static", "dynamic"] {
            for category in &["preference", "behavior", "knowledge", "relationship", "custom"] {
                let fact = Fact {
                    id: format!("fact_{}_{}", fact_type, category),
                    workspace_id: "ws".to_string(),
                    peer_id: "peer".to_string(),
                    fact_type: fact_type.to_string(),
                    category: category.to_string(),
                    content: "test content".to_string(),
                    confidence: 0.5,
                    source: "manual".to_string(),
                    tier: "L0".to_string(),
                    is_active: true,
                    created_at: 0,
                    expires_at: 0,
                    updated_at: 0,
                };
                assert_eq!(fact.fact_type, *fact_type);
                assert_eq!(fact.category, *category);
            }
        }
    }

    #[test]
    fn test_fact_all_tiers() {
        for tier in &["L0", "L1", "L2"] {
            let fact = Fact {
                id: format!("fact_tier_{}", tier),
                workspace_id: "ws".to_string(),
                peer_id: "peer".to_string(),
                fact_type: "static".to_string(),
                category: "knowledge".to_string(),
                content: "test".to_string(),
                confidence: 1.0,
                source: "test".to_string(),
                tier: tier.to_string(),
                is_active: true,
                created_at: 0,
                expires_at: 0,
                updated_at: 0,
            };
            assert_eq!(fact.tier, *tier);
        }
    }

    #[test]
    fn test_fact_serde_roundtrip() {
        let fact = Fact {
            id: "fact_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            peer_id: "peer_serde".to_string(),
            fact_type: "dynamic".to_string(),
            category: "behavior".to_string(),
            content: "often codes at night".to_string(),
            confidence: 0.8,
            source: "extracted".to_string(),
            tier: "L2".to_string(),
            is_active: true,
            created_at: 1_000_000,
            expires_at: 32_536_000_000_000_i64,
            updated_at: 1_000_000,
        };
        let json = serde_json::to_string(&fact).expect("serialize Fact");
        let deserialized: Fact = serde_json::from_str(&json).expect("deserialize Fact");
        assert_eq!(deserialized.id, fact.id);
        assert_eq!(deserialized.fact_type, fact.fact_type);
        assert_eq!(deserialized.category, fact.category);
        assert_eq!(deserialized.content, fact.content);
        assert_eq!(deserialized.confidence, fact.confidence);
        assert_eq!(deserialized.source, fact.source);
        assert_eq!(deserialized.tier, fact.tier);
        assert_eq!(deserialized.is_active, fact.is_active);
    }

    #[test]
    fn test_fact_inactive() {
        let fact = Fact {
            id: "fact_inactive".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "peer".to_string(),
            fact_type: "static".to_string(),
            category: "knowledge".to_string(),
            content: "old fact".to_string(),
            confidence: 0.3,
            source: "manual".to_string(),
            tier: "L0".to_string(),
            is_active: false,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
        };
        assert!(!fact.is_active);
    }

    #[test]
    fn test_fact_zero_confidence() {
        let fact = Fact {
            id: "fact_zero_conf".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "peer".to_string(),
            fact_type: "static".to_string(),
            category: "custom".to_string(),
            content: "uncertain".to_string(),
            confidence: 0.0,
            source: "inferred".to_string(),
            tier: "L0".to_string(),
            is_active: true,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
        };
        assert_eq!(fact.confidence, 0.0);
    }

    #[test]
    fn test_fact_empty_content() {
        let fact = Fact {
            id: "fact_empty".to_string(),
            workspace_id: "ws".to_string(),
            peer_id: "peer".to_string(),
            fact_type: "static".to_string(),
            category: "knowledge".to_string(),
            content: String::new(),
            confidence: 0.5,
            source: "manual".to_string(),
            tier: "L1".to_string(),
            is_active: true,
            created_at: 0,
            expires_at: 0,
            updated_at: 0,
        };
        assert_eq!(fact.content, "");
    }

    // -----------------------------------------------------------------------
    // FactResult struct
    // -----------------------------------------------------------------------

    #[test]
    fn test_fact_result_initialization() {
        let r = FactResult {
            id: "fr_001".to_string(),
            workspace_id: "ws_001".to_string(),
            query_hash: "ws_001:peer_001:static:L0:knowledge".to_string(),
            json_data: r#"[]"#.to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(r.id, "fr_001");
        assert_eq!(r.workspace_id, "ws_001");
        assert_eq!(r.query_hash, "ws_001:peer_001:static:L0:knowledge");
        assert_eq!(r.json_data, "[]");
    }

    #[test]
    fn test_fact_result_serde_roundtrip() {
        let r = FactResult {
            id: "fr_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            query_hash: "search:test:L0".to_string(),
            json_data: r#"[{"id":"f1","content":"test"}]"#.to_string(),
            created_at: 0,
        };
        let json = serde_json::to_string(&r).expect("serialize FactResult");
        let deserialized: FactResult = serde_json::from_str(&json).expect("deserialize FactResult");
        assert_eq!(deserialized.id, r.id);
        assert_eq!(deserialized.workspace_id, r.workspace_id);
        assert_eq!(deserialized.query_hash, r.query_hash);
        assert_eq!(deserialized.json_data, r.json_data);
    }

    #[test]
    fn test_fact_result_with_facts() {
        let facts = vec![
            Fact {
                id: "f1".to_string(),
                workspace_id: "ws".to_string(),
                peer_id: "p1".to_string(),
                fact_type: "static".to_string(),
                category: "knowledge".to_string(),
                content: "knows Rust".to_string(),
                confidence: 0.9,
                source: "manual".to_string(),
                tier: "L1".to_string(),
                is_active: true,
                created_at: 100,
                expires_at: 200,
                updated_at: 100,
            },
        ];
        let json_data = serde_json::to_string(&facts).expect("serialize facts");
        let r = FactResult {
            id: "fr_facts".to_string(),
            workspace_id: "ws".to_string(),
            query_hash: "ws:::".to_string(),
            json_data: json_data.clone(),
            created_at: 0,
        };
        assert!(r.json_data.contains("knows Rust"));
        assert!(r.json_data.contains("f1"));
        // Verify roundtrip of the contained data
        let deserialized: Vec<Fact> = serde_json::from_str(&r.json_data).expect("deserialize");
        assert_eq!(deserialized.len(), 1);
        assert_eq!(deserialized[0].content, "knows Rust");
    }
}
