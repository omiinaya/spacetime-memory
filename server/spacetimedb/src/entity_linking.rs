use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// An entity link stores a canonical entity name with aliases,
/// providing Mem0-style entity resolution for the knowledge graph.
#[table(accessor = entity_link, public)]
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
    let now = now_micros();
    let id = uuid_v4();

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
    let mut el = ctx
        .db
        .entity_link()
        .id()
        .find(&id)
        .ok_or_else(|| format!("EntityLink '{}' not found", id))?;

    // Append alias to aliases_json array
    let new_alias = format!("\"{}\"", alias.replace('"', "\\\""));
    if el.aliases_json.trim() == "[]" || el.aliases_json.trim().is_empty() {
        el.aliases_json = format!("[{}]", new_alias);
    } else {
        let trimmed = el.aliases_json.trim_end().to_string();
        if trimmed.ends_with(']') {
            el.aliases_json = format!("{}, {}]", trimmed[..trimmed.len() - 1].trim(), new_alias);
        } else {
            el.aliases_json = format!("[{}]", new_alias);
        }
    }

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
    // Check if entity already exists in this workspace
    let existing = ctx
        .db
        .entity_link()
        .iter()
        .find(|el| el.workspace_id == workspace_id && el.entity_name == name);

    if existing.is_none() {
        return Err(format!(
            "Entity '{}' not found in workspace '{}'",
            name, workspace_id
        ));
    }

    Ok(())
}
