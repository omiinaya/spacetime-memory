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
    pub connector_type: String, // "rss", "github", "twitter", "slack", "discord", "telegram"
    pub config_json: String,    // JSON with connector-specific params
    #[index(btree)]
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_connector_config_active() {
        let config = ConnectorConfig {
            id: "conn_001".to_string(),
            name: "RSS Feed".to_string(),
            connector_type: "rss".to_string(),
            config_json: r#"{"url":"https://example.com/feed.xml"}"#.to_string(),
            workspace_id: "ws_001".to_string(),
            schedule_secs: 300,
            is_active: true,
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(config.id, "conn_001");
        assert_eq!(config.name, "RSS Feed");
        assert_eq!(config.connector_type, "rss");
        assert_eq!(config.schedule_secs, 300);
        assert!(config.is_active);
        assert_eq!(config.created_at, 1_000_000);
        assert_eq!(config.updated_at, 1_000_000);
    }

    #[test]
    fn test_connector_config_inactive() {
        let config = ConnectorConfig {
            id: "conn_002".to_string(),
            name: "Disabled".to_string(),
            connector_type: "github".to_string(),
            config_json: "{}".to_string(),
            workspace_id: "ws_002".to_string(),
            schedule_secs: 0,
            is_active: false,
            created_at: 2_000_000,
            updated_at: 2_000_000,
        };
        assert_eq!(config.id, "conn_002");
        assert_eq!(config.connector_type, "github");
        assert_eq!(config.schedule_secs, 0);
        assert!(!config.is_active);
    }

    #[test]
    fn test_connector_config_defaults() {
        let config = ConnectorConfig {
            id: String::new(),
            name: String::new(),
            connector_type: String::new(),
            config_json: String::new(),
            workspace_id: String::new(),
            schedule_secs: 0,
            is_active: false,
            created_at: 0,
            updated_at: 0,
        };
        assert!(config.id.is_empty());
        assert!(config.config_json.is_empty());
        assert_eq!(config.schedule_secs, 0);
        assert!(!config.is_active);
        assert_eq!(config.created_at, 0);
    }

    // ── Additional tests ──────────────────────────────────────────────

    #[test]
    fn test_connector_config_different_types() {
        for ctype in &["rss", "github", "twitter", "slack", "discord", "telegram"] {
            let config = ConnectorConfig {
                id: format!("conn_{}", ctype),
                name: format!("{} Connector", ctype),
                connector_type: ctype.to_string(),
                config_json: r#"{"key":"value"}"#.to_string(),
                workspace_id: "ws_main".to_string(),
                schedule_secs: 60,
                is_active: true,
                created_at: 1_000_000,
                updated_at: 1_000_000,
            };
            assert_eq!(config.connector_type, *ctype);
            assert_eq!(&config.id, &format!("conn_{}", ctype));
        }
    }

    #[test]
    fn test_connector_config_large_schedule() {
        let config = ConnectorConfig {
            id: "conn_long".to_string(),
            name: "Infrequent Poll".to_string(),
            connector_type: "rss".to_string(),
            config_json: "{}".to_string(),
            workspace_id: "ws_001".to_string(),
            schedule_secs: 86400, // once per day
            is_active: true,
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(config.schedule_secs, 86400);
    }

    #[test]
    fn test_connector_config_minimal() {
        let config = ConnectorConfig {
            id: "conn_min".to_string(),
            name: String::new(),
            connector_type: "custom".to_string(),
            config_json: "{}".to_string(),
            workspace_id: "ws_min".to_string(),
            schedule_secs: 0,
            is_active: false,
            created_at: 0,
            updated_at: 0,
        };
        assert!(config.name.is_empty());
        assert!(!config.is_active);
        assert_eq!(config.schedule_secs, 0);
    }
}
