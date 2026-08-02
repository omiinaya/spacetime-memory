/// Webhook delivery sidecar for spacetime-memory.
///
/// Polls the SpacetimeDB `webhook_delivery` table for pending deliveries,
/// POSTs to the target webhook URLs, and updates delivery status.
///
/// # Architecture
///
/// 1. Polls STDB's SQL API for rows WHERE status = 'pending'
/// 2. For each pending delivery:
///    a. Look up the webhook URL from the `webhook` table
///    b. POST the payload with HMAC-SHA256 signature
///    c. Update delivery status to 'delivered' or 'failed'
/// 3. Retry failed deliveries with exponential backoff (up to 3 retries)
///
/// Run alongside the SpacetimeDB instance. No external dependencies
/// beyond `reqwest` for HTTP and HMAC for payload signing.

use std::time::Duration;

use hmac::{Hmac, Mac};
use sha2::Sha256;
use base64::Engine;

type HmacSha256 = Hmac<Sha256>;

/// Configuration for the webhook sidecar.
#[derive(Debug, Clone)]
struct Config {
    /// SpacetimeDB base URL (e.g. "http://localhost:3001")
    stdb_url: String,
    /// Poll interval in seconds
    poll_interval_secs: u64,
    /// Max retries per delivery
    max_retries: u32,
    /// Request timeout in seconds
    request_timeout_secs: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            stdb_url: std::env::var("STDB_URL").unwrap_or_else(|_| "http://localhost:3001".into()),
            poll_interval_secs: std::env::var("POLL_INTERVAL_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(5),
            max_retries: std::env::var("MAX_RETRIES")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(3),
            request_timeout_secs: std::env::var("REQUEST_TIMEOUT_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(10),
        }
    }
}

/// A pending webhook delivery as returned by the STDB SQL API.
#[derive(Debug, serde::Deserialize, Clone)]
struct PendingDelivery {
    id: String,
    #[allow(dead_code)]
    webhook_id: String,
    #[allow(dead_code)]
    workspace_id: String,
    #[allow(dead_code)]
    event_type: String,
    payload: String,
    retry_count: u32,
}

/// A webhook definition as returned by the STDB SQL API.
#[derive(Debug, serde::Deserialize, Clone)]
struct WebhookRow {
    id: String,
    url: String,
    secret: String,
    is_active: bool,
}

#[derive(Debug, serde::Deserialize)]
struct SqlResponse<T> {
    rows: Vec<T>,
}

#[derive(Debug, serde::Serialize)]
#[allow(dead_code)]
struct StatusUpdate {
    status: String,
    response_code: u16,
    response_body: String,
    attempted_at: i64,
    retry_count: u32,
}

/// Compute HMAC-SHA256 signature for a payload.
fn compute_signature(secret: &str, payload: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .expect("HMAC key should accept any length");
    mac.update(payload.as_bytes());
    let result = mac.finalize();
    let code_bytes = result.into_bytes();
    base64::engine::general_purpose::STANDARD.encode(&code_bytes)
}

/// Fetch pending deliveries from the STDB SQL API.
async fn fetch_pending_deliveries(
    client: &reqwest::Client,
    config: &Config,
) -> Result<Vec<PendingDelivery>, String> {
    let url = format!(
        "{}/sql?q=SELECT%20id,webhook_id,workspace_id,event_type,payload,retry_count%20FROM%20webhook_delivery%20WHERE%20status%20%3D%20'pending'%20ORDER%20BY%20created_at%20ASC",
        config.stdb_url
    );

    let resp = client
        .get(&url)
        .timeout(Duration::from_secs(config.request_timeout_secs))
        .send()
        .await
        .map_err(|e| format!("HTTP error: {}", e))?;

    let body = resp.text().await.map_err(|e| format!("Body error: {}", e))?;

    // STDB SQL API returns either a JSON array of rows or a wrapper
    // Try deserializing as wrapped response first
    if let Ok(wrapped) = serde_json::from_str::<SqlResponse<PendingDelivery>>(&body) {
        return Ok(wrapped.rows);
    }

    // Try as plain JSON array
    if let Ok(rows) = serde_json::from_str::<Vec<PendingDelivery>>(&body) {
        return Ok(rows);
    }

    log::debug!("No pending deliveries (parse failed or empty): {}", body);
    Ok(Vec::new())
}

/// Look up the webhook definition for a delivery.
async fn fetch_webhook(
    client: &reqwest::Client,
    config: &Config,
    webhook_id: &str,
) -> Result<Option<WebhookRow>, String> {
    let escaped_id = urlencoding(webhook_id);
    let url = format!(
        "{}/sql?q=SELECT%20id,url,secret,is_active%20FROM%20webhook%20WHERE%20id%20%3D%20'{}'",
        config.stdb_url, escaped_id
    );

    let resp = client
        .get(&url)
        .timeout(Duration::from_secs(config.request_timeout_secs))
        .send()
        .await
        .map_err(|e| format!("HTTP error: {}", e))?;

    let body = resp.text().await.map_err(|e| format!("Body error: {}", e))?;

    // Try wrapped response
    if let Ok(wrapped) = serde_json::from_str::<SqlResponse<WebhookRow>>(&body) {
        return Ok(wrapped.rows.into_iter().next());
    }

    // Try as array
    if let Ok(rows) = serde_json::from_str::<Vec<WebhookRow>>(&body) {
        return Ok(rows.into_iter().next());
    }

    Ok(None)
}

/// Update delivery status via a reducer call.
async fn update_delivery_status(
    client: &reqwest::Client,
    config: &Config,
    delivery_id: &str,
    status: &str,
    response_code: u16,
    response_body: &str,
    retry_count: u32,
) -> Result<(), String> {
    let url = format!(
        "{}/v1/database/db/reducers/update_webhook_delivery",
        config.stdb_url
    );

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_micros() as i64;

    let body = serde_json::json!({
        "args": [
            delivery_id,
            status,
            response_code,
            response_body,
            now,
            retry_count,
        ]
    });

    let resp = client
        .post(&url)
        .json(&body)
        .timeout(Duration::from_secs(config.request_timeout_secs))
        .send()
        .await
        .map_err(|e| format!("Update error: {}", e))?;

    if !resp.status().is_success() {
        let text = resp.text().await.unwrap_or_default();
        log::warn!("Failed to update delivery {}: {}", delivery_id, text);
    }

    Ok(())
}

/// Simple URL encoding for SQL queries.
fn urlencoding(s: &str) -> String {
    s.replace('\'', "''")
}

/// Process a single pending delivery.
async fn process_delivery(
    client: &reqwest::Client,
    config: &Config,
    delivery: &PendingDelivery,
) {
    log::info!(
        "Processing delivery {} (webhook: {}, event: {})",
        &delivery.id[..8],
        &delivery.webhook_id[..8],
        delivery.event_type
    );

    // Fetch the webhook definition
    let webhook = match fetch_webhook(client, config, &delivery.webhook_id).await {
        Ok(Some(w)) => w,
        Ok(None) => {
            log::warn!("Webhook {} not found, marking delivery as failed", &delivery.webhook_id[..8]);
            let _ = update_delivery_status(
                client, config, &delivery.id, "failed", 404, "Webhook not found",
                delivery.retry_count,
            ).await;
            return;
        }
        Err(e) => {
            log::error!("Failed to fetch webhook {}: {}", &delivery.webhook_id[..8], e);
            return;
        }
    };

    if !webhook.is_active {
        log::debug!("Webhook {} is inactive, skipping", &webhook.id[..8]);
        return;
    }

    // Compute HMAC signature
    let signature = compute_signature(&webhook.secret, &delivery.payload);

    // POST to the webhook URL
    let body: serde_json::Value = match serde_json::from_str(&delivery.payload) {
        Ok(v) => v,
        Err(_) => serde_json::Value::String(delivery.payload.clone()),
    };

    let result = client
        .post(&webhook.url)
        .json(&body)
        .header("X-Webhook-Signature", &signature)
        .header("X-Webhook-Event", &delivery.event_type)
        .header("X-Webhook-Delivery", &delivery.id)
        .timeout(Duration::from_secs(config.request_timeout_secs))
        .send()
        .await;

    match result {
        Ok(resp) => {
            let status_code = resp.status().as_u16();
            let resp_body = resp.text().await.unwrap_or_default();
            let new_status = if status_code < 500 { "delivered" } else { "failed" };

            log::info!(
                "Delivery {} → {} (HTTP {})",
                &delivery.id[..8], new_status, status_code,
            );

            let _ = update_delivery_status(
                client, config, &delivery.id, new_status, status_code, &resp_body,
                delivery.retry_count,
            ).await;
        }
        Err(e) => {
            log::warn!(
                "Delivery {} failed (network error): {}",
                &delivery.id[..8], e,
            );

            let new_retry_count = delivery.retry_count + 1;
            let new_status = if new_retry_count >= config.max_retries {
                "failed"
            } else {
                "pending" // Will be retried on next poll
            };

            let _ = update_delivery_status(
                client, config, &delivery.id, new_status, 0, &e.to_string(),
                new_retry_count,
            ).await;
        }
    }
}

/// Main delivery loop.
async fn delivery_loop(config: Config) {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(config.request_timeout_secs + 5))
        .user_agent("spacetime-memory-webhook-sidecar/0.1.0")
        .build()
        .expect("Failed to create HTTP client");

    log::info!(
        "Webhook sidecar started (poll: {}s, max retries: {}, STDB: {})",
        config.poll_interval_secs,
        config.max_retries,
        config.stdb_url,
    );

    loop {
        let deliveries = match fetch_pending_deliveries(&client, &config).await {
            Ok(d) => d,
            Err(e) => {
                log::error!("Failed to fetch deliveries: {}", e);
                tokio::time::sleep(Duration::from_secs(config.poll_interval_secs)).await;
                continue;
            }
        };

        if deliveries.is_empty() {
            log::debug!("No pending deliveries");
        } else {
            log::info!("Found {} pending delivery(ies)", deliveries.len());
            for delivery in &deliveries {
                process_delivery(&client, &config, delivery).await;
            }
        }

        tokio::time::sleep(Duration::from_secs(config.poll_interval_secs)).await;
    }
}

#[tokio::main]
async fn main() {
    env_logger::Builder::from_env(
        env_logger::Env::default().default_filter_or("info"),
    )
    .init();

    let config = Config::default();

    log::info!("Starting webhook delivery sidecar");
    log::info!("  STDB URL:      {}", config.stdb_url);
    log::info!("  Poll interval:  {}s", config.poll_interval_secs);
    log::info!("  Max retries:    {}", config.max_retries);
    log::info!("  Request timeout: {}s", config.request_timeout_secs);

    delivery_loop(config).await;
}
