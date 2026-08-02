//! Embedder metrics — periodic snapshots of the embedder sidecar state.
//!
//! The embedder exposes a Prometheus /metrics endpoint. A cron job scrapes
//! it and pushes the values here via ``push_embedder_metrics``, which writes
//! a snapshot row with RSS, embedding count, model info, and raw metrics text.
//!
//! The ``embedder_metrics_snapshot`` table is public so the frontend
//! dashboard can display trends without auth.

use spacetimedb::*;

use crate::auth::require_auth;
use crate::{now_micros, uuid_v7};

/// Single snapshot of embedder /metrics data.
#[table(accessor = embedder_metrics_snapshot, public)]
#[derive(Debug, Clone)]
pub struct EmbedderMetricsSnapshot {
    #[primary_key]
    pub id: String,
    /// Resident set size in bytes (process RAM usage)
    pub rss_bytes: u64,
    /// Total embeddings computed (counter)
    pub embedding_count: u64,
    /// Process uptime in seconds
    pub uptime_seconds: u64,
    /// Embedding dimension (e.g. 1024)
    pub dimension: u32,
    /// Model name (e.g. "BAAI/bge-m3")
    pub model_name: String,
    /// Raw Prometheus text from the embedder /metrics endpoint
    pub raw_metrics_text: String,
    /// Millisecond timestamp when snapshot was pushed
    pub created_at: i64,
}

/// Push an embedder metrics snapshot from the sidecar.
///
/// Called by a cron job that periodically scrapes the embedder /metrics
/// endpoint. Stores the raw Prometheus text + extracted structured values.
///
/// Args:
///     rss_bytes: Resident set size in bytes from embedder_rss_bytes gauge.
///     embedding_count: Total embeddings from embedder_embedding_count counter.
///     uptime_seconds: Uptime from embedder_uptime_seconds gauge.
///     dimension: Embedding dimension from embedder_dimension gauge.
///     model_name: Model name from embedder_model_info label.
///     raw_metrics_text: Full Prometheus text output from /metrics.
#[reducer]
pub fn push_embedder_metrics(
    ctx: &ReducerContext,
    rss_bytes: u64,
    embedding_count: u64,
    uptime_seconds: u64,
    dimension: u32,
    model_name: String,
    raw_metrics_text: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let snapshot = EmbedderMetricsSnapshot {
        id,
        rss_bytes,
        embedding_count,
        uptime_seconds,
        dimension,
        model_name,
        raw_metrics_text,
        created_at: now,
    };

    ctx.db.embedder_metrics_snapshot().insert(snapshot);

    log::info!(
        "embedder_metrics: rss={rss_bytes}B embeddings={embedding_count} uptime={uptime_seconds}s"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_embedder_metrics_snapshot_with_data() {
        let snap = EmbedderMetricsSnapshot {
            id: "emb_snap_001".to_string(),
            rss_bytes: 2_299_192_000,
            embedding_count: 1_500,
            uptime_seconds: 86400,
            dimension: 1024,
            model_name: "BAAI/bge-m3".to_string(),
            raw_metrics_text: "# HELP embedder_rss_bytes Resident set size\n# TYPE embedder_rss_bytes gauge\nembedder_rss_bytes 2299192000".to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(snap.id, "emb_snap_001");
        assert_eq!(snap.rss_bytes, 2_299_192_000);
        assert_eq!(snap.embedding_count, 1500);
        assert_eq!(snap.dimension, 1024);
        assert_eq!(snap.model_name, "BAAI/bge-m3");
    }

    #[test]
    fn test_embedder_metrics_snapshot_empty() {
        let snap = EmbedderMetricsSnapshot {
            id: "emb_snap_002".to_string(),
            rss_bytes: 0,
            embedding_count: 0,
            uptime_seconds: 0,
            dimension: 0,
            model_name: String::new(),
            raw_metrics_text: String::new(),
            created_at: 0,
        };
        assert_eq!(snap.rss_bytes, 0);
        assert!(snap.model_name.is_empty());
    }

    #[test]
    fn test_embedder_metrics_snapshot_high_values() {
        let snap = EmbedderMetricsSnapshot {
            id: "emb_snap_003".to_string(),
            rss_bytes: u64::MAX,
            embedding_count: u64::MAX,
            uptime_seconds: u64::MAX,
            dimension: u32::MAX,
            model_name: "test".to_string(),
            raw_metrics_text: "raw".to_string(),
            created_at: 9_999_999_999_999,
        };
        assert_eq!(snap.rss_bytes, u64::MAX);
        assert_eq!(snap.dimension, u32::MAX);
    }
}
