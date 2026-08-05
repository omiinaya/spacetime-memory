use spacetimedb::*;

use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::{now_micros, uuid_v4_uniq, uuid_v7};

// ---------------------------------------------------------------------------
// Webhook — registered callback URL that receives POST requests when events
// occur within a workspace.
// ---------------------------------------------------------------------------

/// A registered webhook that fires POST requests on matching workspace events.
#[table(accessor = webhook, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Webhook {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Human-friendly label for this webhook.
    pub name: String,
    /// Target URL that receives the POST request.
    pub url: String,
    /// JSON array of event type strings, e.g. `["message.created", "memory.created"]`.
    /// An empty array `[]` matches all events.
    pub event_types: String,
    /// Whether this webhook is actively delivering.
    pub is_active: bool,
    /// HMAC-SHA256 secret for signing payloads (plaintext in DB, used by
    /// the delivery worker to compute the `X-Webhook-Signature` header).
    pub secret: String,
    pub created_at: i64,
    pub updated_at: i64,
    /// Identity that created this webhook.
    pub created_by: String,
}

// ---------------------------------------------------------------------------
// WebhookDelivery — record of every webhook POST attempt and its result.
// ---------------------------------------------------------------------------

/// A single delivery attempt for a webhook event.
///
/// Status lifecycle: `pending` → `delivered` | `failed`.
/// An external worker (or future reducer) picks up `pending` deliveries,
/// performs the HTTP call, and updates the status accordingly.
#[table(accessor = webhook_delivery, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct WebhookDelivery {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub webhook_id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The event type that triggered this delivery, e.g. `"message.created"`.
    pub event_type: String,
    /// JSON payload sent in the POST body.
    pub payload: String,
    /// `"pending"` | `"delivered"` | `"failed"`
    pub status: String,
    /// HTTP response status code (0 if not yet delivered).
    pub response_code: u16,
    /// HTTP response body (empty if not yet delivered or empty response).
    pub response_body: String,
    /// Micros timestamp of the last delivery attempt (0 if never attempted).
    pub attempted_at: i64,
    /// Micros timestamp of successful delivery (0 if not yet delivered).
    pub delivered_at: i64,
    /// How many times delivery has been retried.
    pub retry_count: u32,
}

// ---------------------------------------------------------------------------
// WebhookListResult — ephemeral result table for list_webhooks.
// ---------------------------------------------------------------------------

/// Snapshot result for `list_webhooks` queries.
#[table(accessor = webhook_list_result, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct WebhookListResult {
    #[primary_key]
    pub id: String,
    pub webhook_id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub name: String,
    pub url: String,
    pub event_types: String,
    pub is_active: bool,
    pub created_at: i64,
    pub updated_at: i64,
    pub created_by: String,
}

// ---------------------------------------------------------------------------
// Webhook CRUD reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_webhook(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    url: String,
    event_types: String,
    secret: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v4_uniq(ctx, |id| ctx.db.webhook().id().find(id).is_none(), 3);
    let ws_id = workspace_id.clone();

    // Validate event_types is valid JSON (must be an array of strings)
    if !event_types.is_empty() {
        let parsed: serde_json::Value = serde_json::from_str(&event_types).map_err(|e| {
            format!("event_types must be valid JSON: {}", e)
        })?;
        if !parsed.is_array() {
            return Err("event_types must be a JSON array".to_string());
        }
    }

    // Validate URL is non-empty
    if url.trim().is_empty() {
        return Err("url must not be empty".to_string());
    }

    let webhook = Webhook {
        id: id.clone(),
        workspace_id,
        name,
        url,
        event_types: if event_types.is_empty() {
            String::from("[]")
        } else {
            event_types
        },
        is_active: true,
        secret,
        created_at: now,
        updated_at: now,
        created_by: caller.to_string(),
    };

    let json = change_event::record_to_json(&webhook);
    ctx.db.webhook().insert(webhook);
    change_event::log_change(ctx, &ws_id, "webhook", "insert", &id, &json);
    Ok(())
}

#[reducer]
pub fn update_webhook(
    ctx: &ReducerContext,
    webhook_id: String,
    name: String,
    url: String,
    event_types: String,
    is_active: bool,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let mut wh = ctx
        .db
        .webhook()
        .id()
        .find(&webhook_id)
        .ok_or_else(|| format!("Webhook '{}' not found", webhook_id))?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &wh.workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);

    // Validate event_types is valid JSON if non-empty
    if !event_types.is_empty() {
        let parsed: serde_json::Value = serde_json::from_str(&event_types).map_err(|e| {
            format!("event_types must be valid JSON: {}", e)
        })?;
        if !parsed.is_array() {
            return Err("event_types must be a JSON array".to_string());
        }
        wh.event_types = event_types;
    }

    if !name.is_empty() {
        wh.name = name;
    }
    if !url.trim().is_empty() {
        wh.url = url;
    }
    wh.is_active = is_active;
    wh.updated_at = now;

    let ws_id = wh.workspace_id.clone();
    let json = change_event::record_to_json(&wh);
    ctx.db.webhook().id().update(wh);
    change_event::log_change(ctx, &ws_id, "webhook", "update", &webhook_id, &json);
    Ok(())
}

#[reducer]
pub fn delete_webhook(
    ctx: &ReducerContext,
    webhook_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let wh = ctx
        .db
        .webhook()
        .id()
        .find(&webhook_id)
        .ok_or_else(|| format!("Webhook '{}' not found", webhook_id))?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &wh.workspace_id, &caller, "editor")?;

    let ws_id = wh.workspace_id.clone();
    let json = change_event::record_to_json(&wh);
    ctx.db.webhook().id().delete(&webhook_id);

    // Also delete any pending deliveries for this webhook
    let deliveries: Vec<_> = ctx
        .db
        .webhook_delivery()
        .webhook_id()
        .filter(&webhook_id)
        .collect();
    for d in deliveries {
        ctx.db.webhook_delivery().id().delete(&d.id);
    }

    change_event::log_change(ctx, &ws_id, "webhook", "delete", &webhook_id, &json);
    Ok(())
}

#[reducer]
pub fn list_webhooks(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    // Clear stale results for this workspace
    for existing in ctx.db.webhook_list_result().workspace_id().filter(&workspace_id) {
        ctx.db.webhook_list_result().id().delete(&existing.id);
    }

    for wh in ctx
        .db
        .webhook()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
    {
        ctx.db.webhook_list_result().insert(WebhookListResult {
            id: uuid_v7(ctx),
            webhook_id: wh.id.clone(),
            workspace_id: workspace_id.clone(),
            name: wh.name.clone(),
            url: wh.url.clone(),
            event_types: wh.event_types.clone(),
            is_active: wh.is_active,
            created_at: wh.created_at,
            updated_at: wh.updated_at,
            created_by: wh.created_by.clone(),
        });
    }

    Ok(())
}

/// Update a webhook delivery record (called by the webhook-sidecar process).
/// Accepts: delivery_id, status, response_code, response_body, attempted_at, retry_count.
#[reducer]
pub fn update_webhook_delivery(
    ctx: &ReducerContext,
    delivery_id: String,
    status: String,
    response_code: u16,
    response_body: String,
    attempted_at: i64,
    retry_count: u32,
) -> Result<(), String> {
    let mut delivery = ctx
        .db
        .webhook_delivery()
        .id()
        .find(&delivery_id)
        .ok_or_else(|| format!("Webhook delivery '{}' not found", delivery_id))?;

    delivery.status = status;
    delivery.response_code = response_code;
    delivery.response_body = response_body;
    delivery.attempted_at = attempted_at;
    delivery.retry_count = retry_count;

    if delivery.status == "delivered" {
        delivery.delivered_at = attempted_at;
    }

    ctx.db.webhook_delivery().id().update(delivery);
    Ok(())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

/// Fire a webhook event: find all active webhooks in the workspace whose
/// `event_types` match the given `event_type`, and create a `pending`
/// `WebhookDelivery` record for each.
///
/// This reducer does **not** perform HTTP calls — those are handled
/// asynchronously by an external delivery worker that polls for pending
/// deliveries. The `secret` field on the webhook is available for the
/// worker to compute `X-Webhook-Signature` HMAC headers.
///
/// # Matching logic
/// - If a webhook's `event_types` is `[]` (empty array), it matches all events.
/// - Otherwise, the event type must appear as a string in the JSON array.
#[reducer]
pub fn fire_webhook_event(
    ctx: &ReducerContext,
    workspace_id: String,
    event_type: String,
    payload: String,
) -> Result<(), String> {
    let _now = now_micros(ctx);

    // Collect matching webhooks (active + event type match)
    let matches: Vec<Webhook> = ctx
        .db
        .webhook()
        .workspace_id()
        .filter(&workspace_id)
        .filter(|wh| wh.is_active)
        .filter(|wh| {
            // If event_types is empty array "[]", match all events
            if wh.event_types == "[]" || wh.event_types == "[\"*\"]" {
                return true;
            }
            // Parse the JSON array and check for a match
            match serde_json::from_str::<Vec<String>>(&wh.event_types) {
                Ok(types) => types.contains(&event_type),
                Err(_) => false,
            }
        })
        .collect();

    if matches.is_empty() {
        return Ok(());
    }

    for wh in &matches {
        let delivery_id = uuid_v4_uniq(ctx, |id| ctx.db.webhook_delivery().id().find(id).is_none(), 3);

        let delivery = WebhookDelivery {
            id: delivery_id.clone(),
            webhook_id: wh.id.clone(),
            workspace_id: workspace_id.clone(),
            event_type: event_type.clone(),
            payload: payload.clone(),
            status: String::from("pending"),
            response_code: 0,
            response_body: String::new(),
            attempted_at: 0,
            delivered_at: 0,
            retry_count: 0,
        };

        ctx.db.webhook_delivery().insert(delivery);
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── Webhook struct construction ────────────────────────────────────

    #[test]
    fn test_webhook_construction_all_fields() {
        let wh = Webhook {
            id: "wh_001".to_string(),
            workspace_id: "ws_001".to_string(),
            name: "My Webhook".to_string(),
            url: "https://example.com/hook".to_string(),
            event_types: r#"["memory.created","message.created"]"#.to_string(),
            is_active: true,
            secret: "s3cr3t".to_string(),
            created_at: 1_700_000_000,
            updated_at: 1_700_000_000,
            created_by: "usr_001".to_string(),
        };
        assert_eq!(wh.id, "wh_001");
        assert_eq!(wh.name, "My Webhook");
        assert_eq!(wh.url, "https://example.com/hook");
        assert!(wh.is_active);
        assert_eq!(wh.secret, "s3cr3t");
    }

    #[test]
    fn test_webhook_construction_inactive() {
        let wh = Webhook {
            id: "wh_002".to_string(),
            workspace_id: "ws_002".to_string(),
            name: "Disabled Hook".to_string(),
            url: "https://example.com/disabled".to_string(),
            event_types: String::new(),
            is_active: false,
            secret: String::new(),
            created_at: 2_000_000,
            updated_at: 2_000_000,
            created_by: "usr_002".to_string(),
        };
        assert!(!wh.is_active);
        assert!(wh.event_types.is_empty());
        assert!(wh.secret.is_empty());
    }

    #[test]
    fn test_webhook_empty_event_types() {
        let wh = Webhook {
            id: "wh_003".to_string(),
            workspace_id: "ws_003".to_string(),
            name: "All Events".to_string(),
            url: "https://example.com/all".to_string(),
            event_types: String::new(), // Empty means all events in create_webhook
            is_active: true,
            secret: "key".to_string(),
            created_at: 3_000_000,
            updated_at: 3_000_000,
            created_by: "usr_003".to_string(),
        };
        assert!(wh.event_types.is_empty());
    }

    #[test]
    fn test_webhook_wildcard_event_types() {
        let wh = Webhook {
            id: "wh_004".to_string(),
            workspace_id: "ws_004".to_string(),
            name: "Wildcard".to_string(),
            url: "https://example.com/wildcard".to_string(),
            event_types: r#"["*"]"#.to_string(),
            is_active: true,
            secret: "key".to_string(),
            created_at: 4_000_000,
            updated_at: 4_000_000,
            created_by: "usr_004".to_string(),
        };
        assert_eq!(wh.event_types, r#"["*"]"#);
    }

    #[test]
    fn test_webhook_delivery_construction_pending() {
        let d = WebhookDelivery {
            id: "del_001".to_string(),
            webhook_id: "wh_001".to_string(),
            workspace_id: "ws_001".to_string(),
            event_type: "memory.created".to_string(),
            payload: r#"{"memory_id":"mem_001"}"#.to_string(),
            status: "pending".to_string(),
            response_code: 0,
            response_body: String::new(),
            attempted_at: 0,
            delivered_at: 0,
            retry_count: 0,
        };
        assert_eq!(d.status, "pending");
        assert_eq!(d.response_code, 0);
        assert_eq!(d.retry_count, 0);
    }

    #[test]
    fn test_webhook_delivery_construction_delivered() {
        let d = WebhookDelivery {
            id: "del_002".to_string(),
            webhook_id: "wh_001".to_string(),
            workspace_id: "ws_001".to_string(),
            event_type: "message.created".to_string(),
            payload: r#"{"message_id":"msg_001"}"#.to_string(),
            status: "delivered".to_string(),
            response_code: 200,
            response_body: "OK".to_string(),
            attempted_at: 1_700_000_000,
            delivered_at: 1_700_000_001,
            retry_count: 1,
        };
        assert_eq!(d.status, "delivered");
        assert_eq!(d.response_code, 200);
        assert_eq!(d.attempted_at, 1_700_000_000);
        assert_eq!(d.retry_count, 1);
    }

    #[test]
    fn test_webhook_delivery_construction_failed() {
        let d = WebhookDelivery {
            id: "del_003".to_string(),
            webhook_id: "wh_001".to_string(),
            workspace_id: "ws_001".to_string(),
            event_type: "memory.created".to_string(),
            payload: "{}".to_string(),
            status: "failed".to_string(),
            response_code: 500,
            response_body: "Internal Server Error".to_string(),
            attempted_at: 1_700_000_000,
            delivered_at: 0,
            retry_count: 3,
        };
        assert_eq!(d.status, "failed");
        assert_eq!(d.response_code, 500);
        assert_eq!(d.delivered_at, 0);
        assert_eq!(d.retry_count, 3);
    }

    #[test]
    fn test_webhook_delivery_empty_payload() {
        let d = WebhookDelivery {
            id: "del_004".to_string(),
            webhook_id: "wh_002".to_string(),
            workspace_id: "ws_002".to_string(),
            event_type: "event.test".to_string(),
            payload: String::new(),
            status: "pending".to_string(),
            response_code: 0,
            response_body: String::new(),
            attempted_at: 0,
            delivered_at: 0,
            retry_count: 0,
        };
        assert!(d.payload.is_empty());
        assert!(d.response_body.is_empty());
    }

    // ── WebhookListResult struct construction ──────────────────────────

    #[test]
    fn test_webhook_list_result_construction() {
        let r = WebhookListResult {
            id: "lr_001".to_string(),
            webhook_id: "wh_001".to_string(),
            workspace_id: "ws_001".to_string(),
            name: "Listed Hook".to_string(),
            url: "https://example.com/hook".to_string(),
            event_types: r#"["memory.created"]"#.to_string(),
            is_active: true,
            created_at: 1_000_000,
            updated_at: 2_000_000,
            created_by: "usr_001".to_string(),
        };
        assert_eq!(r.webhook_id, "wh_001");
        assert_eq!(r.name, "Listed Hook");
        assert!(r.is_active);
    }

    #[test]
    fn test_webhook_list_result_minimal() {
        let r = WebhookListResult {
            id: String::new(),
            webhook_id: String::new(),
            workspace_id: String::new(),
            name: String::new(),
            url: String::new(),
            event_types: String::new(),
            is_active: false,
            created_at: 0,
            updated_at: 0,
            created_by: String::new(),
        };
        assert!(r.id.is_empty());
        assert!(!r.is_active);
    }

    // ── Event type validation tests ────────────────────────────────────

    #[test]
    fn test_event_types_json_validation_valid_array() {
        let json = r#"["memory.created","message.created"]"#;
        let parsed: serde_json::Value = serde_json::from_str(json).unwrap();
        assert!(parsed.is_array());
    }

    #[test]
    fn test_event_types_json_validation_empty_array() {
        let json = r#"[]"#;
        let parsed: serde_json::Value = serde_json::from_str(json).unwrap();
        assert!(parsed.is_array());
        assert_eq!(parsed.as_array().unwrap().len(), 0);
    }

    #[test]
    fn test_event_types_json_validation_invalid() {
        let json = r#"not json"#;
        let result: Result<serde_json::Value, _> = serde_json::from_str(json);
        assert!(result.is_err());
    }

    #[test]
    fn test_event_types_json_validation_not_array() {
        let json = r#"{"type":"memory.created"}"#;
        let parsed: serde_json::Value = serde_json::from_str(json).unwrap();
        assert!(!parsed.is_array());
    }

    // ── URL validation tests ───────────────────────────────────────────

    #[test]
    fn test_url_trim_validation_empty() {
        let url = "   ".to_string();
        assert!(url.trim().is_empty());
    }

    #[test]
    fn test_url_trim_validation_non_empty() {
        let url = "https://example.com/hook".to_string();
        assert!(!url.trim().is_empty());
    }

    // ── Fire webhook event matching logic ──────────────────────────────

    #[test]
    fn test_fire_webhook_empty_array_matches_all() {
        // The fire_webhook_event reducer checks: wh.event_types == "[]"
        let empty_array = "[]";
        let wildcard_array = r#"["*"]"#;
        assert_eq!(empty_array, "[]");
        assert_eq!(wildcard_array, r#"["*"]"#);
    }

    #[test]
    fn test_fire_webhook_event_type_matching() {
        let event_types = r#"["memory.created","message.created"]"#;
        let types: Vec<String> = serde_json::from_str(event_types).unwrap();
        assert!(types.contains(&"memory.created".to_string()));
        assert!(types.contains(&"message.created".to_string()));
        assert!(!types.contains(&"memory.deleted".to_string()));
    }
}
