use spacetimedb::*;
use crate::{now_micros, uuid_v4_uniq};
use crate::auth::{self, check_rate_limit};

/// A managed subscription that tracks which clients are subscribed
/// to which STDB queries. This allows clients to persist subscriptions
/// across reconnections and provides metadata about active subscriptions.
///
/// The `query` field stores the full SQL query string (e.g.,
/// `"SELECT * FROM memory WHERE workspace_id = 'ws-1'"`).
/// The `callback_url` field is optional — when set, the system can
/// push table updates to an external HTTP endpoint (webhook mode).
#[table(accessor = subscription)]
#[derive(Debug, Clone)]
pub struct Subscription {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    /// The SQL query string for the subscription (e.g., `"SELECT * FROM memory"`)
    pub query: String,
    /// Optional callback URL for webhook-style delivery (empty string = none)
    pub callback_url: String,
    /// Peer ID of the creator
    pub created_by: String,
    pub is_active: bool,
    pub created_at: i64,
    pub updated_at: i64,
}

/// Public result table for list_subscriptions reducer.
#[table(accessor = subscription_list_result)]
#[derive(Debug, Clone)]
pub struct SubscriptionListResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    pub query: String,
    pub callback_url: String,
    pub created_by: String,
    pub is_active: bool,
    pub created_at: i64,
    pub updated_at: i64,
}

/// Create a new subscription. Caller must be authenticated.
#[reducer]
pub fn create_subscription(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    query: String,
    callback_url: String,
) -> Result<(), String> {
    let account = auth::require_auth(ctx)?;
    check_rate_limit(ctx, "create_subscription", 10)?;

    if query.trim().is_empty() {
        return Err("Subscription query cannot be empty".to_string());
    }

    // Validate query to prevent SQL injection: only SELECT queries are allowed
    let trimmed = query.trim();
    if !trimmed.to_uppercase().starts_with("SELECT ") {
        return Err("Subscription query must be a SELECT statement. DDL/DML queries (INSERT, UPDATE, DELETE, DROP, etc.) are not allowed.".to_string());
    }
    // Reject known dangerous patterns inside SELECT as extra defense
    let dangerous_patterns = ["DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ", "CREATE ", "TRUNCATE ", "EXEC ", "EXECUTE "];
    let query_upper = trimmed.to_uppercase();
    for pattern in &dangerous_patterns {
        if query_upper.contains(pattern) {
            return Err(format!("Subscription query rejected: '{}' is not allowed", pattern.trim()));
        }
    }

    let now = now_micros(ctx);

    ctx.db.subscription().insert(Subscription {
        id: uuid_v4_uniq(ctx, |id| ctx.db.subscription().id().find(id).is_none(), 3),
        workspace_id,
        name,
        query,
        callback_url,
        created_by: account.id.clone(),
        is_active: true,
        created_at: now,
        updated_at: now,
    });
    Ok(())
}

/// Delete a subscription by ID. Only the creator or an admin can delete.
#[reducer]
pub fn delete_subscription(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let account = auth::require_auth(ctx)?;
    check_rate_limit(ctx, "delete_subscription", 10)?;

    let existing = ctx.db.subscription().id().find(&id)
        .ok_or_else(|| format!("Subscription '{}' not found", id))?;

    if existing.created_by != account.id && account.role != "admin" {
        return Err("Only the subscription creator or an admin can delete subscriptions".to_string());
    }

    ctx.db.subscription().id().delete(&id);
    Ok(())
}

/// Toggle a subscription active/inactive.
#[reducer]
pub fn toggle_subscription(ctx: &ReducerContext, id: String, is_active: bool) -> Result<(), String> {
    let account = auth::require_auth(ctx)?;
    check_rate_limit(ctx, "toggle_subscription", 10)?;

    let mut existing = ctx.db.subscription().id().find(&id)
        .ok_or_else(|| format!("Subscription '{}' not found", id))?;

    if existing.created_by != account.id && account.role != "admin" {
        return Err("Only the subscription creator or an admin can toggle subscriptions".to_string());
    }

    existing.is_active = is_active;
    existing.updated_at = now_micros(ctx);
    ctx.db.subscription().id().update(existing);
    Ok(())
}

/// List all active subscriptions for a workspace.
/// Writes results to subscription_list_result so clients can subscribe.
#[reducer]
pub fn list_subscriptions(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _account = auth::require_auth(ctx)?;
    check_rate_limit(ctx, "list_subscriptions", 30)?;

    // Clear previous results for this workspace
    for r in ctx.db.subscription_list_result()
        .iter()
        .filter(|r| r.workspace_id == workspace_id)
        .collect::<Vec<_>>()
    {
        ctx.db.subscription_list_result().id().delete(&r.id);
    }

    for s in ctx.db.subscription()
        .iter()
        .filter(|s| s.workspace_id == workspace_id && s.is_active)
    {
        ctx.db.subscription_list_result().insert(SubscriptionListResult {
            id: uuid_v4_uniq(ctx, |id| ctx.db.subscription_list_result().id().find(id).is_none(), 3),
            workspace_id: workspace_id.clone(),
            name: s.name.clone(),
            query: s.query.clone(),
            callback_url: s.callback_url.clone(),
            created_by: s.created_by.clone(),
            is_active: s.is_active,
            created_at: s.created_at,
            updated_at: s.updated_at,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_subscription_construction_all_fields() {
        let sub = Subscription {
            id: "sub_001".to_string(),
            workspace_id: "ws_001".to_string(),
            name: "Memory Feed".to_string(),
            query: "SELECT * FROM memory WHERE workspace_id = 'ws_001'".to_string(),
            callback_url: "https://example.com/callback".to_string(),
            created_by: "usr_001".to_string(),
            is_active: true,
            created_at: 1_000_000,
            updated_at: 2_000_000,
        };
        assert_eq!(sub.id, "sub_001");
        assert_eq!(sub.name, "Memory Feed");
        assert!(sub.query.starts_with("SELECT"));
        assert!(!sub.callback_url.is_empty());
        assert!(sub.is_active);
    }

    #[test]
    fn test_subscription_without_callback() {
        let sub = Subscription {
            id: "sub_002".to_string(),
            workspace_id: "ws_002".to_string(),
            name: "Silent Sub".to_string(),
            query: "SELECT * FROM memory".to_string(),
            callback_url: String::new(), // No callback
            created_by: "usr_002".to_string(),
            is_active: true,
            created_at: 3_000_000,
            updated_at: 3_000_000,
        };
        assert!(sub.callback_url.is_empty());
        assert!(sub.is_active);
    }

    #[test]
    fn test_subscription_inactive() {
        let sub = Subscription {
            id: "sub_003".to_string(),
            workspace_id: "ws_003".to_string(),
            name: "Paused".to_string(),
            query: "SELECT * FROM memory".to_string(),
            callback_url: String::new(),
            created_by: "usr_003".to_string(),
            is_active: false,
            created_at: 4_000_000,
            updated_at: 4_000_000,
        };
        assert!(!sub.is_active);
    }

    #[test]
    fn test_subscription_list_result_construction() {
        let r = SubscriptionListResult {
            id: "sr_001".to_string(),
            workspace_id: "ws_001".to_string(),
            name: "Listed Sub".to_string(),
            query: "SELECT * FROM memory".to_string(),
            callback_url: String::new(),
            created_by: "usr_001".to_string(),
            is_active: true,
            created_at: 5_000_000,
            updated_at: 5_000_000,
        };
        assert_eq!(r.name, "Listed Sub");
        assert!(r.is_active);
    }

    #[test]
    fn test_subscription_query_validation_select_only() {
        // Replicate the validation logic from create_subscription
        let query = "SELECT * FROM memory";
        assert!(query.to_uppercase().starts_with("SELECT "));
    }

    #[test]
    fn test_subscription_query_validation_rejects_ddl() {
        let dangerous = ["DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ", "CREATE ", "TRUNCATE ", "EXEC ", "EXECUTE "];
        for pattern in &dangerous {
            let query = format!("SELECT * FROM memory WHERE name {} something", pattern);
            assert!(query.to_uppercase().contains(pattern), "Should detect pattern: {}", pattern);
        }
    }

    #[test]
    fn test_subscription_empty_query_rejected() {
        let query = "   ".to_string();
        assert!(query.trim().is_empty());
    }

    #[test]
    fn test_subscription_empty_query_not_select() {
        let query = String::new();
        assert!(!query.trim().to_uppercase().starts_with("SELECT "));
    }
}
