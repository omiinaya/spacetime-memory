//! Operation tracing — structured span recording for the SpacetimeDB module.
//!
//! Provides a lightweight tracing layer that logs reducer operations to both
//! ``log::info!()`` (STDB host logging) and a queryable ``TracingSpan`` table.
//!
//! Usage in a reducer:
//!
//! ```ignore
//! use crate::tracing::{record_span, TracingSpanKind};
//!
//! #[reducer]
//! pub fn my_reducer(ctx: &ReducerContext, …) -> Result<(), String> {
//!     let start = now_micros(ctx);
//!     // ... reducer logic ...
//!     let duration = now_micros(ctx) - start;
//!     record_span(ctx, "my_reducer", TracingSpanKind::Write, &workspace_id,
//!                 duration, true, None);
//!     Ok(())
//! }
//! ```
//!
//! Or use the `trace_span!` macro for automatic timing:
//!
//! ```ignore
//! use crate::tracing::trace_span;
//!
//! #[reducer]
//! pub fn my_reducer(ctx: &ReducerContext, …) -> Result<(), String> {
//!     trace_span!(ctx, "my_reducer", TracingSpanKind::Read, &workspace_id, {
//!         // ... reducer logic ...
//!     })
//! }
//! ```

use spacetimedb::*;

use crate::now_micros;
use crate::uuid_v7;

// ---------------------------------------------------------------------------
// Kinds of traced operations
// ---------------------------------------------------------------------------

/// Categorises the traced operation for filtering and dashboard use.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TracingSpanKind {
    /// Read-only reducer (search, query, get)
    Read,
    /// Write reducer (store, update, delete, insert)
    Write,
    /// Admin/internal reducer (cleanup, maintenance, sync)
    Admin,
}

impl TracingSpanKind {
    fn as_str(&self) -> &'static str {
        match self {
            Self::Read => "read",
            Self::Write => "write",
            Self::Admin => "admin",
        }
    }
}

// ---------------------------------------------------------------------------
// Table: TracingSpan
// ---------------------------------------------------------------------------

/// A single traced operation recorded by the observability layer.
///
/// Every call to ``record_span`` inserts one row. Clients (or the Python SDK
/// tracer) can query recent spans for latency monitoring, debugging, and
/// dashboards.
///
/// The table is **public** so the frontend dashboard can display traces
/// without authentication.
#[table(accessor = tracing_span, public)]
#[derive(Debug, Clone)]
pub struct TracingSpan {
    #[primary_key]
    pub id: String,
    /// Name of the traced operation (e.g. `"store_memory"`, `"hybrid_search"`)
    pub operation: String,
    /// Category: "read" | "write" | "admin"
    pub kind: String,
    /// Workspace the operation targeted (empty string if global)
    pub workspace_id: String,
    /// Duration of the operation in microseconds
    pub duration_micros: i64,
    /// Whether the operation completed successfully
    pub success: bool,
    /// Error message if ``success`` is false; empty string otherwise
    pub error_message: String,
    /// Reducer context sender identity (hex)
    pub caller: String,
    /// Millisecond epoch timestamp when the span was recorded
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Record a structured span entry for an operation.
///
/// Writes a ``TracingSpan`` row and emits a structured ``log::info!()``
/// message.  The caller must provide the operation's duration (in
/// microseconds) — measure it with ``now_micros()`` before and after the
/// body.
pub fn record_span(
    ctx: &ReducerContext,
    operation: &str,
    kind: TracingSpanKind,
    workspace_id: &str,
    duration_micros: i64,
    success: bool,
    error_message: Option<&str>,
) {
    let now = now_micros(ctx);
    let span = TracingSpan {
        id: uuid_v7(ctx),
        operation: operation.to_string(),
        kind: kind.as_str().to_string(),
        workspace_id: workspace_id.to_string(),
        duration_micros,
        success,
        error_message: error_message.unwrap_or("").to_string(),
        caller: ctx.sender().to_hex().to_string(),
        created_at: now,
    };

    // Persist to table for later querying
    ctx.db.tracing_span().insert(span);

    // Emit structured log line
    if success {
        log::info!(
            "[trace] op={op} kind={k} ws={ws} duration={d}µs caller={c}",
            op = operation,
            k = kind.as_str(),
            ws = workspace_id,
            d = duration_micros,
            c = ctx.sender().to_hex(),
        );
    } else {
        log::error!(
            "[trace] op={op} kind={k} ws={ws} duration={d}µs caller={c} error={e}",
            op = operation,
            k = kind.as_str(),
            ws = workspace_id,
            d = duration_micros,
            c = ctx.sender().to_hex(),
            e = error_message.unwrap_or("unknown"),
        );
    }
}

// ---------------------------------------------------------------------------
// Macro: trace_span!
// ---------------------------------------------------------------------------

/// Execute a block of code, timing it and recording a tracing span.
///
/// The span is recorded on success **and** on error.  On error the
/// block's ``Result::Err`` message is captured and the span marked as
/// unsuccessful.
///
/// # Usage
///
/// ```ignore
/// use crate::tracing::trace_span;
///
/// #[reducer]
/// pub fn my_reducer(ctx: &ReducerContext, ws: String, …) -> Result<(), String> {
///     trace_span!(ctx, "my_reducer", TracingSpanKind::Write, &ws, {
///         // ... do work that returns Result<(), String> ...
///         Ok(())
///     })
/// }
/// ```
#[macro_export]
macro_rules! trace_span {
    ($ctx:expr, $op:expr, $kind:expr, $ws:expr, $body:block) => {{
        let __start = $crate::now_micros($ctx);
        let __result: Result<(), String> = { $body };
        let __duration = $crate::now_micros($ctx) - __start;
        match &__result {
            Ok(_) => {
                $crate::tracing::record_span(
                    $ctx, $op, $kind, $ws, __duration, true, None,
                );
            }
            Err(e) => {
                $crate::tracing::record_span(
                    $ctx, $op, $kind, $ws, __duration, false, Some(e),
                );
            }
        }
        __result
    }};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_span_kind_as_str() {
        assert_eq!(TracingSpanKind::Read.as_str(), "read");
        assert_eq!(TracingSpanKind::Write.as_str(), "write");
        assert_eq!(TracingSpanKind::Admin.as_str(), "admin");
    }

    #[test]
    fn test_tracing_span_struct() {
        let span = TracingSpan {
            id: "test-id".into(),
            operation: "test_op".into(),
            kind: "read".into(),
            workspace_id: "ws-1".into(),
            duration_micros: 42,
            success: true,
            error_message: String::new(),
            caller: "0xdead".into(),
            created_at: 1_000_000,
        };
        assert_eq!(span.operation, "test_op");
        assert!(span.success);
        assert!(span.error_message.is_empty());
    }

    #[test]
    fn test_tracing_span_error() {
        let span = TracingSpan {
            id: "err-id".into(),
            operation: "fail_op".into(),
            kind: "write".into(),
            workspace_id: "ws-2".into(),
            duration_micros: 999,
            success: false,
            error_message: "something went wrong".into(),
            caller: "0xbeef".into(),
            created_at: 2_000_000,
        };
        assert!(!span.success);
        assert_eq!(span.error_message, "something went wrong");
    }
}
