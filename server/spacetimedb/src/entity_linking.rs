use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};

/// An entity link stores a canonical entity name with aliases,
/// providing Mem0-style entity resolution for the knowledge graph.
#[table(accessor = entity_link)]
#[derive(Debug, Clone)]
pub struct EntityLink {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Canonical entity name
    pub entity_name: String,
    /// JSON array of alias strings
    pub aliases_json: String,
    /// Entity type classification
    pub entity_type: String,
    pub description: String,
    pub created_at: i64,
}

#[reducer]
pub fn create_entity_link(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_name: String,
    aliases_json: String,
    entity_type: String,
    description: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let el = EntityLink {
        id: id.clone(),
        workspace_id,
        entity_name,
        aliases_json,
        entity_type,
        description,
        created_at: now,
    };

    ctx.db.entity_link().insert(el);
    Ok(())
}

#[reducer]
pub fn add_alias(ctx: &ReducerContext, id: String, alias: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let mut el = ctx
        .db
        .entity_link()
        .id()
        .find(&id)
        .ok_or_else(|| format!("EntityLink '{}' not found", id))?;

    // Append alias to aliases_json array — use serde_json for safety
    let mut aliases: Vec<String> = match serde_json::from_str(&el.aliases_json) {
        Ok(v) => v,
        Err(e) => {
            log::info!("Failed to parse aliases_json: {}", e);
            Vec::new()
        }
    };
    aliases.push(alias);
    el.aliases_json = serde_json::to_string(&aliases).unwrap_or_else(|_| "[]".to_string());

    ctx.db.entity_link().id().update(el);
    Ok(())
}

/// Resolve an entity name within a workspace by checking if it exists.
#[reducer]
pub fn resolve_entity(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Check if entity already exists in this workspace
    let existing = ctx
        .db
        .entity_link()
        .iter().take(crate::MAX_RESULTS)
        .find(|el| el.workspace_id == workspace_id && el.entity_name == name);

    if existing.is_none() {
        return Err(format!(
            "Entity '{}' not found in workspace '{}'",
            name, workspace_id
        ));
    }

    Ok(())
}
