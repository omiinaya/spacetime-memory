use spacetimedb::*;
use crate::auth::require_auth;
use crate::auth::require_admin;

use crate::{now_micros, uuid_v4_uniq, uuid_v7};
use crate::tracing::TracingSpanKind;
use crate::trace_span;

// ---------------------------------------------------------------------------
// ChangeEvent — real-time change data capture (CDC) table
// ---------------------------------------------------------------------------
// Every write reducer on content tables (memory, kg_node, kg_edge, note,
// profile, document) appends a ChangeEvent row so a delta-sync sidecar can
// poll and fan out to local subscribers in near-real-time.
// ---------------------------------------------------------------------------

/// A recorded data mutation for delta-sync fanout.
///
/// Consumers poll `get_changes_since()` and dispatch callbacks.
/// Old events are purged by `cleanup_change_events()`.
#[table(accessor = change_event)]
#[derive(Debug, Clone, serde::Serialize)]
pub struct ChangeEvent {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// The table that changed: "memory", "kg_node", "kg_edge", "note",
    /// "profile", "document", "workspace"
    pub table_name: String,
    /// The operation: "insert", "update", "delete"
    pub operation: String,
    /// Primary key of the changed record
    pub record_id: String,
    /// JSON-encoded snapshot of the record *after* the operation
    pub data_json: String,
    /// Monotonic microsecond timestamp (from ctx.timestamp)
    pub created_at: i64,
}

/// Result table for `get_changes_since` queries.
#[table(accessor = change_event_result, public)]
#[derive(Debug, Clone, serde::Serialize)]
pub struct ChangeEventResult {
    #[primary_key]
    pub id: String,
    /// Cursor value passed in (so the client can track what it has seen)
    pub since_cursor: i64,
    /// JSON array of ChangeEvent objects
    pub events_json: String,
    /// The highest created_at in the result (next cursor)
    pub next_cursor: i64,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Append a change event to the change_event table.
///
/// Call this from every content write reducer *after* the mutation is
/// committed to the primary table.  The sidecar poller picks these up
/// and fans them out to local subscribers.
pub fn log_change(
    ctx: &ReducerContext,
    workspace_id: &str,
    table_name: &str,
    operation: &str,
    record_id: &str,
    data_json: &str,
) {
    let now = now_micros(ctx);
    let event_id = uuid_v4_uniq(ctx, |id| ctx.db.change_event().id().find(id).is_none(), 3);
    let event = ChangeEvent {
        id: event_id,
        workspace_id: workspace_id.to_string(),
        table_name: table_name.to_string(),
        operation: operation.to_string(),
        record_id: record_id.to_string(),
        data_json: data_json.to_string(),
        created_at: now,
    };
    ctx.db.change_event().insert(event);
}

/// Serialise any STDB record to JSON string for the data_json field.
///
/// # Example
///
/// ```
/// use serde::Serialize;
/// use spacetime_memory::change_event::record_to_json;
///
/// #[derive(Serialize)]
/// struct Metric {
///     name: String,
///     value: f64,
/// }
///
/// let m = Metric { name: "cpu".into(), value: 0.85 };
/// let json = record_to_json(&m);
/// assert_eq!(json, r#"{"name":"cpu","value":0.85}"#);
/// ```
pub fn record_to_json<T: serde::Serialize>(record: &T) -> String {
    serde_json::to_string(record).unwrap_or_else(|_| "{}".to_string())
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

/// Query change events created after a given cursor (monotonic timestamp).
///
/// The caller passes the highest `created_at` it has already processed.
/// Returns up to `MAX_RESULTS` events ordered by `created_at` ascending.
///
/// Results are stored in the `change_event_result` table, keyed by the
/// cursor value so multiple concurrent pollers don't conflict.
#[reducer]
pub fn get_changes_since(
    ctx: &ReducerContext,
    since_cursor: i64,
) -> Result<(), String> {
    trace_span!(ctx, "get_changes_since", TracingSpanKind::Read, "", {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        let mut events: Vec<ChangeEvent> = ctx
            .db
            .change_event()
            .iter().take(crate::MAX_RESULTS)
            .filter(|e| e.created_at > since_cursor)
            .take(crate::MAX_RESULTS)
            .collect();

        // Sort ascending by created_at
        events.sort_by(|a, b| a.created_at.cmp(&b.created_at));

        let next_cursor = events
            .last()
            .map(|e| e.created_at)
            .unwrap_or(since_cursor);

        let result_id = uuid_v7(ctx);
        let result = ChangeEventResult {
            id: result_id.clone(),
            since_cursor,
            events_json: serde_json::to_string(&events)
                .unwrap_or_else(|_| "[]".to_string()),
            next_cursor,
            created_at: now,
        };
        ctx.db.change_event_result().insert(result);

        // Clean up stale results for the same cursor
        let stale: Vec<_> = ctx
            .db
            .change_event_result()
            .iter().take(crate::MAX_RESULTS)
            .filter(|r| r.since_cursor == since_cursor && r.id != result_id)
            .collect();
        for r in stale {
            ctx.db.change_event_result().id().delete(&r.id);
        }

        Ok(())
    })
}

/// Query the latest cursor value (highest created_at in change_event).
/// Consumers call this on startup to get their initial cursor.
#[reducer]
pub fn get_latest_change_cursor(ctx: &ReducerContext) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let cursor = ctx
        .db
        .change_event()
        .iter().take(crate::MAX_RESULTS)
        .map(|e| e.created_at)
        .max()
        .unwrap_or(0);

    let result_id = uuid_v7(ctx);
    let result = ChangeEventResult {
        id: result_id.clone(),
        since_cursor: 0,
        events_json: serde_json::json!({"cursor": cursor}).to_string(),
        next_cursor: cursor,
        created_at: now,
    };
    ctx.db.change_event_result().insert(result);

    Ok(())
}

/// Purge change events older than `retention_micros` (default: 1 hour).
///
/// Call this via maintenance cron to prevent unbounded growth.
#[reducer]
pub fn cleanup_change_events(
    ctx: &ReducerContext,
    retention_micros: i64,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let cutoff = now - retention_micros;

    let expired: Vec<_> = ctx
        .db
        .change_event()
        .iter().take(crate::MAX_RESULTS)
        .filter(|e| e.created_at < cutoff)
        .collect();

    for e in &expired {
        ctx.db.change_event().id().delete(&e.id);
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    // ---- Test helper structs ----

    #[derive(Debug, Serialize, Deserialize, PartialEq)]
    struct SimpleMetric {
        name: String,
        value: f64,
    }

    #[derive(Debug, Serialize, Deserialize, PartialEq)]
    struct Empty {}

    #[derive(Debug, Serialize, Deserialize, PartialEq)]
    struct Nested {
        label: String,
        inner: Inner,
    }

    #[derive(Debug, Serialize, Deserialize, PartialEq)]
    struct Inner {
        x: u32,
        y: u32,
    }

    // ---- record_to_json tests ----

    #[test]
    fn test_record_to_json_simple_struct() {
        let m = SimpleMetric {
            name: "cpu".into(),
            value: 0.85,
        };
        let json = record_to_json(&m);
        assert_eq!(json, r#"{"name":"cpu","value":0.85}"#);
    }

    #[test]
    fn test_record_to_json_empty_struct() {
        let e = Empty {};
        let json = record_to_json(&e);
        assert_eq!(json, r#"{}"#);
    }

    #[test]
    fn test_record_to_json_nested_struct() {
        let n = Nested {
            label: "point".into(),
            inner: Inner { x: 10, y: 20 },
        };
        let json = record_to_json(&n);
        assert_eq!(json, r#"{"label":"point","inner":{"x":10,"y":20}}"#);
    }

    #[test]
    fn test_record_to_json_roundtrip() {
        let original = SimpleMetric {
            name: "memory".into(),
            value: 0.42,
        };
        let json = record_to_json(&original);
        let parsed: SimpleMetric = serde_json::from_str(&json).expect("valid JSON");
        assert_eq!(original, parsed);
    }

    #[test]
    fn test_record_to_json_valid_json() {
        let m = SimpleMetric {
            name: "disk".into(),
            value: 0.5,
        };
        let json = record_to_json(&m);
        // Should parse as valid JSON
        let v: serde_json::Value = serde_json::from_str(&json).expect("should be valid JSON");
        assert_eq!(v["name"], "disk");
        assert_eq!(v["value"], 0.5);
    }

    // ---- ChangeEvent serialisation tests ----

    #[test]
    fn test_change_event_serialization() {
        let event = ChangeEvent {
            id: "evt-001".into(),
            workspace_id: "ws-1".into(),
            table_name: "memory".into(),
            operation: "insert".into(),
            record_id: "rec-001".into(),
            data_json: r#"{"key":"value"}"#.into(),
            created_at: 1_000_000,
        };
        let json = record_to_json(&event);
        let v: serde_json::Value = serde_json::from_str(&json).expect("valid JSON");

        assert_eq!(v["id"], "evt-001");
        assert_eq!(v["workspace_id"], "ws-1");
        assert_eq!(v["table_name"], "memory");
        assert_eq!(v["operation"], "insert");
        assert_eq!(v["record_id"], "rec-001");
        assert_eq!(v["data_json"], r#"{"key":"value"}"#);
        assert_eq!(v["created_at"], 1_000_000);
    }

    // ---- ChangeEventResult serialisation tests ----

    #[test]
    fn test_change_event_result_serialization() {
        let result = ChangeEventResult {
            id: "res-001".into(),
            since_cursor: 500,
            events_json: r#"[{"id":"evt-001"}]"#.into(),
            next_cursor: 1000,
            created_at: 2_000_000,
        };
        let json = record_to_json(&result);
        let v: serde_json::Value = serde_json::from_str(&json).expect("valid JSON");

        assert_eq!(v["id"], "res-001");
        assert_eq!(v["since_cursor"], 500);
        assert_eq!(v["events_json"], r#"[{"id":"evt-001"}]"#);
        assert_eq!(v["next_cursor"], 1000);
        assert_eq!(v["created_at"], 2_000_000);
    }
}
