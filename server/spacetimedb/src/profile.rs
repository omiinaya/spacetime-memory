use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v4};

/// A profile accumulates static facts and dynamic context about a peer.
#[table(accessor = profile)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Profile {
    #[primary_key]
    pub id: String,
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
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    // Attempt to find existing profile for this peer
    let existing = ctx.db.profile().iter().take(crate::MAX_RESULTS).find(|p| p.peer_id == peer_id);

    if let Some(mut p) = existing {
        p.static_facts_json = static_facts_json;
        p.dynamic_context_json = dynamic_context_json;
        p.preferences_json = preferences_json;
        p.tags_json = tags_json;
        p.updated_at = now;
        ctx.db.profile().id().update(p);
    } else {
        // Create new profile
        let id = uuid_v4(ctx);
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
}

#[reducer]
pub fn add_profile_fact(ctx: &ReducerContext, peer_id: String, fact: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let existing = ctx.db.profile().iter().take(crate::MAX_RESULTS).find(|p| p.peer_id == peer_id);

    if let Some(mut p) = existing {
        // Append fact to static_facts_json array — use serde_json for safety
        let mut facts: Vec<String> = serde_json::from_str(&p.static_facts_json).unwrap_or_default();
        facts.push(fact);
        p.static_facts_json = serde_json::to_string(&facts).unwrap_or_else(|_| "[]".to_string());
        p.updated_at = now;
        ctx.db.profile().id().update(p);
    } else {
        // Create a new profile with just this fact
        let id = uuid_v4(ctx);
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
}

#[reducer]
pub fn add_dynamic_context(
    ctx: &ReducerContext,
    peer_id: String,
    context: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let existing = ctx.db.profile().iter().take(crate::MAX_RESULTS).find(|p| p.peer_id == peer_id);

    if let Some(mut p) = existing {
        // Append context entry to dynamic_context_json — use serde_json for safety
        let mut entries: Vec<String> = serde_json::from_str(&p.dynamic_context_json).unwrap_or_default();
        entries.push(context);
        p.dynamic_context_json = serde_json::to_string(&entries).unwrap_or_else(|_| "[]".to_string());
        p.updated_at = now;
        ctx.db.profile().id().update(p);
    } else {
        // Create a new profile with just this context entry
        let id = uuid_v4(ctx);
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
#[table(accessor = fact_result, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct FactResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub query_hash: String,
    pub json_data: String,
    pub created_at: i64,
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
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

    // Determine expires_at: L0=30d, L1=90d, L2=365d from now (in micros)
    let expires_offset: i64 = match tier.as_str() {
        "L0" => 30 * 86400 * 1_000_000,
        "L1" => 90 * 86400 * 1_000_000,
        "L2" => 365 * 86400 * 1_000_000,
        _ => 90 * 86400 * 1_000_000,
    };

    let fact = Fact {
        id,
        workspace_id,
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
                let expires_offset: i64 = match fact.tier.as_str() {
                    "L0" => 30 * 86400 * 1_000_000,
                    "L1" => 90 * 86400 * 1_000_000,
                    "L2" => 365 * 86400 * 1_000_000,
                    _ => 90 * 86400 * 1_000_000,
                };
                fact.expires_at = now + expires_offset;
            }
            fact.updated_at = now;
            ctx.db.fact().id().update(fact);
            Ok(())
        }
        None => Err(format!("Fact '{}' not found", fact_id)),
    }
}

#[reducer]
pub fn delete_fact(ctx: &ReducerContext, fact_id: String) -> Result<(), String> {
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
        .iter()
        .filter(|f| {
            if f.workspace_id != workspace_id {
                return false;
            }
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
    let result_id = uuid_v4(ctx);

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
        .iter()
        .filter(|f| {
            if f.workspace_id != workspace_id {
                return false;
            }
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
    let result_id = uuid_v4(ctx);

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
