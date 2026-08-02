//! Proxy metrics — periodic snapshots of the SpacetimeLLM proxy /metrics.
//!
//! The proxy exposes a Prometheus /metrics endpoint. A cron job scrapes
//! it and pushes the values here via ``push_proxy_metrics``, which writes
//! a snapshot row with the raw Prometheus text + structured counters.
//!
//! The ``proxy_metrics_snapshot`` table is public so the frontend
//! dashboard can display trends without auth.

use spacetimedb::*;

use crate::auth::require_auth;
use crate::{now_micros, uuid_v7};

/// Single snapshot of proxy /metrics data.
#[table(accessor = proxy_metrics_snapshot, public)]
#[derive(Debug, Clone)]
pub struct ProxyMetricsSnapshot {
    #[primary_key]
    pub id: String,
    /// Total requests (counter)
    pub requests_total: u64,
    /// Total tokens processed (counter)
    pub tokens_total: u64,
    /// Total request errors (counter)
    pub errors_total: u64,
    /// Sum of request durations in microseconds
    pub duration_sum_micros: u64,
    /// Count of requests used for duration average
    pub duration_count: u64,
    /// Per-model breakdown as JSON: {"provider|model": count}
    pub per_model_json: String,
    /// Latency percentiles JSON: overall and per-model p50/p95/p99/mean/samples.
    pub latency_percentiles_json: String,
    /// Raw Prometheus text for reference
    pub raw_metrics_text: String,
    /// Millisecond timestamp when snapshot was pushed
    pub created_at: i64,
}

/// Push a metrics snapshot from the SpacetimeLLM proxy.
///
/// Called by a cron job that periodically scrapes the proxy /metrics
/// endpoint. Stores the raw Prometheus text + extracted structured counters.
///
/// Args:
///     requests_total: Total request count from counter.
///     tokens_total: Total token count from counter.
///     errors_total: Total error count from counter.
///     duration_sum_micros: Sum of request durations in microseconds.
///     duration_count: Count of duration samples.
///     per_model_json: JSON map of "provider|model" → count.
///     latency_percentiles_json: JSON with overall and per-model p50/p95/p99/mean/samples.
///     raw_metrics_text: Full Prometheus text output.
#[reducer]
pub fn push_proxy_metrics(
    ctx: &ReducerContext,
    requests_total: u64,
    tokens_total: u64,
    errors_total: u64,
    duration_sum_micros: u64,
    duration_count: u64,
    per_model_json: String,
    latency_percentiles_json: String,
    raw_metrics_text: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let snapshot = ProxyMetricsSnapshot {
        id,
        requests_total,
        tokens_total,
        errors_total,
        duration_sum_micros,
        duration_count,
        per_model_json,
        latency_percentiles_json,
        raw_metrics_text,
        created_at: now,
    };

    ctx.db.proxy_metrics_snapshot().insert(snapshot);

    log::info!(
        "proxy_metrics: requests={requests_total} tokens={tokens_total} errors={errors_total}"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_proxy_metrics_snapshot_with_data() {
        let snap = ProxyMetricsSnapshot {
            id: "snap_001".to_string(),
            requests_total: 1500,
            tokens_total: 75_000,
            errors_total: 3,
            duration_sum_micros: 5_000_000,
            duration_count: 200,
            per_model_json: r#"{"openai|gpt-4": 120, "anthropic|claude-3": 80}"#.to_string(),
            latency_percentiles_json: r#"{"overall":{"p50":1.2,"p95":3.5,"p99":8.0,"mean":1.5,"samples":200}}"#.to_string(),
            raw_metrics_text: "# HELP proxy_requests_total Total requests\n# TYPE proxy_requests_total counter\nproxy_requests_total 1500".to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(snap.id, "snap_001");
        assert_eq!(snap.requests_total, 1500);
        assert_eq!(snap.tokens_total, 75000);
        assert_eq!(snap.errors_total, 3);
        assert_eq!(snap.duration_count, 200);
        assert_eq!(snap.duration_sum_micros, 5_000_000);
        assert!(snap.per_model_json.contains("gpt-4"));
        assert!(snap.latency_percentiles_json.contains("p50"));
    }

    #[test]
    fn test_proxy_metrics_snapshot_empty() {
        let snap = ProxyMetricsSnapshot {
            id: "snap_002".to_string(),
            requests_total: 0,
            tokens_total: 0,
            errors_total: 0,
            duration_sum_micros: 0,
            duration_count: 0,
            per_model_json: "{}".to_string(),
            raw_metrics_text: String::new(),
            latency_percentiles_json: String::new(),
            created_at: 0,
        };
        assert_eq!(snap.requests_total, 0);
        assert!(snap.raw_metrics_text.is_empty());
        assert_eq!(snap.created_at, 0);
    }

    #[test]
    fn test_proxy_metrics_snapshot_high_values() {
        let snap = ProxyMetricsSnapshot {
            id: "snap_003".to_string(),
            requests_total: u64::MAX,
            tokens_total: u64::MAX,
            errors_total: 0,
            duration_sum_micros: u64::MAX,
            duration_count: u64::MAX,
            per_model_json: "{}".to_string(),
            raw_metrics_text: "raw".to_string(),
            latency_percentiles_json: String::new(), 
            created_at: 9_999_999_999_999,
        };
        assert_eq!(snap.requests_total, u64::MAX);
        assert_eq!(snap.created_at, 9_999_999_999_999);
    }
}
