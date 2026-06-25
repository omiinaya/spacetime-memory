use spacetimedb::*;
use crate::{now_micros, uuid_v4_uniq};
use crate::auth;

/// A persistent connector configuration.
///
/// Stored in the database so the connector daemon can load and run
/// connectors across restarts without re-registration.
#[table(accessor = connector_config)]
#[derive(Debug, Clone)]
pub struct ConnectorConfig {
    #[primary_key]
    pub id: String,
    pub name: String,
    pub connector_type: String, // "rss", "github", "twitter", "slack", "discord"
    pub config_json: String,    // JSON with connector-specific params
    pub workspace_id: String,   // target workspace for generated events
    pub schedule_secs: u64,     // poll interval
    pub is_active: bool,
    pub created_at: i64,
    pub updated_at: i64,
}

/// Register a new connector config. Caller must be authenticated.
#[reducer]
pub fn register_connector(
    ctx: &ReducerContext,
    name: String,
    connector_type: String,
    config_json: String,
    workspace_id: String,
    schedule_secs: u64,
) -> Result<(), String> {
    let _account = auth::require_auth(ctx)?;

    let now = now_micros(ctx);
    ctx.db.connector_config().insert(ConnectorConfig {
        id: uuid_v4_uniq(ctx, |id| ctx.db.connector_config().id().find(id).is_none(), 3),
        name,
        connector_type,
        config_json,
        workspace_id,
        schedule_secs,
        is_active: true,
        created_at: now,
        updated_at: now,
    });
    Ok(())
}

/// Update an existing connector config.
#[reducer]
pub fn update_connector(
    ctx: &ReducerContext,
    id: String,
    name: String,
    connector_type: String,
    config_json: String,
    workspace_id: String,
    schedule_secs: u64,
    is_active: bool,
) -> Result<(), String> {
    let _account = auth::require_auth(ctx)?;

    let mut existing = ctx.db.connector_config().id().find(&id)
        .ok_or_else(|| format!("Connector '{}' not found", id))?;

    existing.name = name;
    existing.connector_type = connector_type;
    existing.config_json = config_json;
    existing.workspace_id = workspace_id;
    existing.schedule_secs = schedule_secs;
    existing.is_active = is_active;
    existing.updated_at = now_micros(ctx);
    ctx.db.connector_config().id().update(existing);
    Ok(())
}

/// Delete a connector config.
#[reducer]
pub fn delete_connector(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let _account = auth::require_auth(ctx)?;

    // Check the connector exists
    ctx.db.connector_config().id().find(&id)
        .ok_or_else(|| format!("Connector '{}' not found", id))?;
    ctx.db.connector_config().id().delete(&id);
    Ok(())
}
