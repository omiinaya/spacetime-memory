pub mod workspace;
pub mod peer;
pub mod session;
pub mod message;
pub mod memory;
pub mod memory_feedback;
pub mod knowledge_graph;
pub mod document;
pub mod profile;
pub mod profile_query;
pub mod tag;
pub mod entity_linking;
pub mod insight;
pub mod retrieval;
pub mod auth;
pub mod connector;
pub mod consolidation;
pub mod context_compression;
pub mod context_delta;
pub mod context_directory;
pub mod hybrid_query;
pub mod note;
pub mod graph_traversal;
pub mod tour;
pub mod replication;
pub mod query;
pub mod user;

/// Maximum number of rows any read reducer will return.
/// This caps all `.iter()` scans to prevent OOM/timeout on large tables.
pub const MAX_RESULTS: usize = 1000;

/// Generate a UUID v4 using the SpacetimeDB reducer timestamp and RNG.
/// Safe for WASM — does not use `std::time::SystemTime`.
/// Each call advances the RNG, so consecutive calls in the same reducer
/// produce different UUIDs.
pub fn uuid_v4(ctx: &spacetimedb::ReducerContext) -> String {
    use spacetimedb::rand::RngCore;
    let ts = ctx.timestamp.to_micros_since_unix_epoch();
    let r1 = ctx.rng().next_u64();
    let r2 = ctx.rng().next_u64();
    let high = (ts as u64 ^ r1) as u64;
    let low = r2;
    let ts_part = format!("{:016x}", high);
    let rand_part = format!("{:016x}", low);
    format!(
        "{}-{}-{}-{}-{}",
        &ts_part[..8],
        &ts_part[8..12],
        &rand_part[..4],
        &rand_part[4..8],
        &rand_part[8..]
    )
}

/// Get current timestamp in microseconds from the reducer context.
/// Safe for WASM — uses `ctx.timestamp` instead of `std::time::SystemTime`.
pub fn now_micros(ctx: &spacetimedb::ReducerContext) -> i64 {
    (ctx.timestamp.to_micros_since_unix_epoch() / 1000) as i64
}

pub fn default_expires_at(ctx: &spacetimedb::ReducerContext, lifetime_days: i64) -> i64 {
    if lifetime_days <= 0 {
        0
    } else {
        now_micros(ctx) + lifetime_days * 86_400_000_000
    }
}
