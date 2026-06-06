use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// A profile accumulates static facts and dynamic context about a peer.
#[table(accessor = profile, public)]
#[derive(Debug, Clone)]
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
    let now = now_micros(ctx);

    // Attempt to find existing profile for this peer
    let existing = ctx.db.profile().iter().find(|p| p.peer_id == peer_id);

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
    let now = now_micros(ctx);

    let existing = ctx.db.profile().iter().find(|p| p.peer_id == peer_id);

    if let Some(mut p) = existing {
        // Append fact to static_facts_json array
        let new_fact = format!("\"{}\"", fact.replace('"', "\\\""));
        if p.static_facts_json.trim() == "[]" || p.static_facts_json.trim().is_empty() {
            p.static_facts_json = format!("[{}]", new_fact);
        } else {
            // Insert before the closing bracket
            let trimmed = p.static_facts_json.trim_end().to_string();
            if trimmed.ends_with(']') {
                p.static_facts_json = format!("{}, {}]", trimmed[..trimmed.len() - 1].trim(), new_fact);
            } else {
                p.static_facts_json = format!("[{}]", new_fact);
            }
        }
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
    let now = now_micros(ctx);

    let existing = ctx.db.profile().iter().find(|p| p.peer_id == peer_id);

    if let Some(mut p) = existing {
        let new_entry = format!("\"{}\"", context.replace('"', "\\\""));
        if p.dynamic_context_json.trim() == "[]" || p.dynamic_context_json.trim().is_empty() {
            p.dynamic_context_json = format!("[{}]", new_entry);
        } else {
            let trimmed = p.dynamic_context_json.trim_end().to_string();
            if trimmed.ends_with(']') {
                p.dynamic_context_json = format!("{}, {}]", trimmed[..trimmed.len() - 1].trim(), new_entry);
            } else {
                p.dynamic_context_json = format!("[{}]", new_entry);
            }
        }
        p.updated_at = now;
        ctx.db.profile().id().update(p);
    } else {
        // Create a new profile with just this context entry
        let id = uuid_v4(ctx);
        let context_entry = format!("[\"{}\"]", context.replace('"', "\\\""));
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
