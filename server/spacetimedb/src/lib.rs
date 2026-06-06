pub mod workspace;
pub mod peer;
pub mod session;
pub mod message;
pub mod memory;
pub mod memory_feedback;
pub mod knowledge_graph;
pub mod document;
pub mod profile;
pub mod tag;
pub mod entity_linking;
pub mod insight;
pub mod retrieval;
pub mod auth;
pub mod context_directory;
pub mod consolidation;
pub mod context_compression;

/// Generate a UUID v4 using timestamp (WASM-safe). Not cryptographically secure.
pub fn uuid_v4() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    let micros = now.as_micros();
    // Format as a pseudo-UUID: 8-4-4-4-12 hex chars
    let ts_part = format!("{:016x}", micros);
    let rand_part = format!("{:016x}", (micros.wrapping_mul(6364136223846793005) ^ micros) & 0xFFFFFFFFFFFFFFFF);
    format!(
        "{}-{}-{}-{}-{}",
        &ts_part[..8],
        &ts_part[8..12],
        &rand_part[..4],
        &rand_part[4..8],
        &rand_part[8..]
    )
}

pub fn now_micros() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_micros() as i64
}

pub fn default_expires_at(lifetime_days: i64) -> i64 {
    if lifetime_days <= 0 {
        0
    } else {
        now_micros() + lifetime_days * 86_400_000_000
    }
}

pub fn ctx_timestamp_micros(ctx: &spacetimedb::ReducerContext) -> i64 {
    ctx.timestamp.to_micros_since_unix_epoch() / 1000
}
