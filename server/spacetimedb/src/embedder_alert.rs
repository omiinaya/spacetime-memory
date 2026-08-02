//! Embedder alert events -- push notifications when the embedder sidecar
//! degrades (consecutive failures exceed threshold) or recovers.
//!
//! The SDK calls ``push_embedder_alert`` in real-time when it detects
//! the embedder crossing the failure threshold, and again when it
//! recovers. A standalone cron script (``embedder_alert_cron.py``)
//! provides a fallback watchdog that checks /health independently.
//!
//! The ``embedder_alert`` table is public so the frontend dashboard
//! can display real-time alert status without auth.

use spacetimedb::*;

use crate::auth::require_auth;
use crate::{now_micros, uuid_v7};

/// Severity constants for embedder alerts.
pub mod severity {
    /// Embedder recovered after a degradation episode.
    pub const RECOVERY: u8 = 0;
    /// Warning -- elevated failure rate detected.
    pub const WARNING: u8 = 1;
    /// Critical -- consecutive failures exceed threshold.
    pub const CRITICAL: u8 = 2;
}

/// Single embedder alert event (degradation or recovery).
#[table(accessor = embedder_alert, public)]
#[derive(Debug, Clone)]
pub struct EmbedderAlert {
    #[primary_key]
    pub id: String,
    /// Alert severity: 0=recovery, 1=warning, 2=critical
    pub severity: u8,
    /// Human-readable alert message
    pub message: String,
    /// Consecutive failures at the time of the alert
    pub consecutive_failures: u32,
    /// Total embedder calls made since client init
    pub total_calls: u32,
    /// Total embedder errors recorded
    pub total_errors: u32,
    /// Error rate percentage (total_errors / total_calls * 100)
    pub error_rate_pct: f64,
    /// Whether the embedder is currently in degraded state
    pub degraded: bool,
    /// Whether this is a recovery event
    pub recovery: bool,
    /// Whether the embedder endpoint was reachable
    pub reachable: bool,
    /// The embedder URL that was being checked
    pub embedder_url: String,
    /// Millisecond timestamp when alert was pushed
    pub created_at: i64,
}

/// Push an embedder alert event (degradation, warning, or recovery).
///
/// Called by the Python SDK in real-time when the embedder crosses the
/// consecutive-failure threshold, and by the standalone
/// ``embedder_alert_cron.py`` watchdog as a fallback.
///
/// Args:
///     severity: 0=recovery, 1=warning, 2=critical.
///     message: Human-readable alert message.
///     consecutive_failures: Consecutive failures at alert time.
///     total_calls: Total embedder calls made.
///     total_errors: Total embedder errors recorded.
///     error_rate_pct: Error rate percentage.
///     degraded: Whether the embedder is currently degraded.
///     recovery: Whether this is a recovery event.
///     reachable: Whether the embedder endpoint was reachable.
///     embedder_url: The embedder URL being checked.
#[reducer]
pub fn push_embedder_alert(
    ctx: &ReducerContext,
    severity: u8,
    message: String,
    consecutive_failures: u32,
    total_calls: u32,
    total_errors: u32,
    error_rate_pct: f64,
    degraded: bool,
    recovery: bool,
    reachable: bool,
    embedder_url: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let alert = EmbedderAlert {
        id,
        severity,
        message,
        consecutive_failures,
        total_calls,
        total_errors,
        error_rate_pct,
        degraded,
        recovery,
        reachable,
        embedder_url,
        created_at: now,
    };

    ctx.db.embedder_alert().insert(alert);

    log::info!(
        "embedder_alert: severity={severity} consecutive={consecutive_failures} degraded={degraded} recovery={recovery}"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_embedder_alert_severity_constants() {
        assert_eq!(severity::RECOVERY, 0);
        assert_eq!(severity::WARNING, 1);
        assert_eq!(severity::CRITICAL, 2);
    }

    #[test]
    fn test_embedder_alert_with_critical_severity() {
        let alert = EmbedderAlert {
            id: "alert_001".to_string(),
            severity: severity::CRITICAL,
            message: "Embedder has failed 5 consecutive times -- SDK is returning empty embeddings.".to_string(),
            consecutive_failures: 5,
            total_calls: 50,
            total_errors: 5,
            error_rate_pct: 10.0,
            degraded: true,
            recovery: false,
            reachable: false,
            embedder_url: "http://localhost:4000".to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(alert.id, "alert_001");
        assert_eq!(alert.severity, 2);
        assert!(alert.degraded);
        assert!(!alert.recovery);
        assert!(!alert.reachable);
        assert_eq!(alert.error_rate_pct, 10.0);
    }

    #[test]
    fn test_embedder_alert_with_recovery() {
        let alert = EmbedderAlert {
            id: "alert_002".to_string(),
            severity: severity::RECOVERY,
            message: "Embedder has recovered after 5 consecutive failures.".to_string(),
            consecutive_failures: 0,
            total_calls: 55,
            total_errors: 5,
            error_rate_pct: 9.09,
            degraded: false,
            recovery: true,
            reachable: true,
            embedder_url: "http://localhost:4000".to_string(),
            created_at: 2_000_000,
        };
        assert_eq!(alert.severity, 0);
        assert!(alert.recovery);
        assert!(!alert.degraded);
        assert!(alert.reachable);
        assert_eq!(alert.consecutive_failures, 0);
    }

    #[test]
    fn test_embedder_alert_empty_message() {
        let alert = EmbedderAlert {
            id: "alert_003".to_string(),
            severity: severity::WARNING,
            message: String::new(),
            consecutive_failures: 2,
            total_calls: 10,
            total_errors: 2,
            error_rate_pct: 20.0,
            degraded: false,
            recovery: false,
            reachable: true,
            embedder_url: String::new(),
            created_at: 0,
        };
        assert!(alert.message.is_empty());
        assert!(alert.embedder_url.is_empty());
        assert_eq!(alert.created_at, 0);
    }
}
