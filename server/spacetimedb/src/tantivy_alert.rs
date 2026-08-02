//! Tantivy sidecar alert events — push notifications when the Tantivy sidecar
//! is unreachable or degraded.
//!
//! The sidecar watchdog (``health_watchdog.py``) calls ``push_tantivy_alert``
//! when it detects connectivity issues or health check failures.
//!
//! The table is public so the frontend dashboard can display real-time alert
//! status without auth.

use spacetimedb::*;

use crate::auth::require_auth;
use crate::{now_micros, uuid_v7};

/// Severity constants for Tantivy sidecar alerts.
pub mod severity {
    /// Sidecar recovered after a degradation episode.
    pub const RECOVERY: u8 = 0;
    /// Warning — elevated failure rate detected.
    pub const WARNING: u8 = 1;
    /// Critical — sidecar unreachable or consecutive failures exceed threshold.
    pub const CRITICAL: u8 = 2;
}

/// Single Tantivy sidecar alert event (degradation or recovery).
#[table(accessor = tantivy_alert, public)]
#[derive(Debug, Clone)]
pub struct TantivyAlert {
    #[primary_key]
    pub id: String,
    /// Alert severity: 0=recovery, 1=warning, 2=critical
    pub severity: u8,
    /// Human-readable alert message
    pub message: String,
    /// Consecutive failures at the time of the alert
    pub consecutive_failures: u32,
    /// Total health checks performed
    pub total_checks: u32,
    /// Total failures recorded
    pub total_failures: u32,
    /// Error rate percentage (total_failures / total_checks * 100)
    pub error_rate_pct: f64,
    /// Whether the sidecar is currently in degraded state
    pub degraded: bool,
    /// Whether this is a recovery event
    pub recovery: bool,
    /// Whether the sidecar endpoint was reachable
    pub reachable: bool,
    /// The Tantivy sidecar URL that was being checked
    pub tantivy_url: String,
    /// Millisecond timestamp when alert was pushed
    pub created_at: i64,
}

/// Push a Tantivy sidecar alert event (degradation, warning, or recovery).
///
/// Called by the Python watchdog script in real-time when the sidecar
/// crosses the consecutive-failure threshold, or when it recovers.
///
/// Args:
///     severity: 0=recovery, 1=warning, 2=critical.
///     message: Human-readable alert message.
///     consecutive_failures: Consecutive failures at alert time.
///     total_checks: Total health checks performed.
///     total_failures: Total failures recorded.
///     error_rate_pct: Error rate percentage.
///     degraded: Whether the sidecar is currently degraded.
///     recovery: Whether this is a recovery event.
///     reachable: Whether the sidecar endpoint was reachable.
///     tantivy_url: The sidecar URL being checked.
#[reducer]
pub fn push_tantivy_alert(
    ctx: &ReducerContext,
    severity: u8,
    message: String,
    consecutive_failures: u32,
    total_checks: u32,
    total_failures: u32,
    error_rate_pct: f64,
    degraded: bool,
    recovery: bool,
    reachable: bool,
    tantivy_url: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let alert = TantivyAlert {
        id,
        severity,
        message,
        consecutive_failures,
        total_checks,
        total_failures,
        error_rate_pct,
        degraded,
        recovery,
        reachable,
        tantivy_url,
        created_at: now,
    };

    ctx.db.tantivy_alert().insert(alert);

    log::info!(
        "tantivy_alert: severity={severity} reachable={reachable} degraded={degraded} consecutive_failures={consecutive_failures}"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tantivy_alert_critical() {
        let alert = TantivyAlert {
            id: "tantivy_alert_001".to_string(),
            severity: severity::CRITICAL,
            message: "Tantivy sidecar unreachable after 5 consecutive failures.".to_string(),
            consecutive_failures: 5,
            total_checks: 50,
            total_failures: 5,
            error_rate_pct: 10.0,
            degraded: true,
            recovery: false,
            reachable: false,
            tantivy_url: "http://localhost:4001".to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(alert.severity, 2);
        assert!(alert.degraded);
        assert!(!alert.recovery);
        assert!(!alert.reachable);
    }

    #[test]
    fn test_tantivy_alert_recovery() {
        let alert = TantivyAlert {
            id: "tantivy_alert_002".to_string(),
            severity: severity::RECOVERY,
            message: "Tantivy sidecar has recovered.".to_string(),
            consecutive_failures: 0,
            total_checks: 55,
            total_failures: 5,
            error_rate_pct: 9.09,
            degraded: false,
            recovery: true,
            reachable: true,
            tantivy_url: "http://localhost:4001".to_string(),
            created_at: 2_000_000,
        };
        assert_eq!(alert.severity, 0);
        assert!(alert.recovery);
        assert!(!alert.degraded);
        assert!(alert.reachable);
    }

    #[test]
    fn test_tantivy_alert_empty_message() {
        let alert = TantivyAlert {
            id: "tantivy_alert_003".to_string(),
            severity: severity::WARNING,
            message: String::new(),
            consecutive_failures: 2,
            total_checks: 10,
            total_failures: 2,
            error_rate_pct: 20.0,
            degraded: false,
            recovery: false,
            reachable: true,
            tantivy_url: String::new(),
            created_at: 0,
        };
        assert!(alert.message.is_empty());
        assert!(alert.tantivy_url.is_empty());
        assert_eq!(alert.created_at, 0);
    }
}
