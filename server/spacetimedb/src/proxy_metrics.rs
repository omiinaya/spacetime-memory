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
        raw_metrics_text,
        created_at: now,
    };

    ctx.db.proxy_metrics_snapshot().insert(snapshot);

    log::info!(
        "proxy_metrics: requests={requests_total} tokens={tokens_total} errors={errors_total}"
    );
    Ok(())
}
