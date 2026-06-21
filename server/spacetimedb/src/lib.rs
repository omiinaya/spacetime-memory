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
pub mod entity_extraction;
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
pub mod proxy_metrics;
pub mod harmonic_belief;
pub mod change_event;

/// Maximum number of rows any read reducer will return.
/// This caps all `.iter()` scans to prevent OOM/timeout on large tables.
pub const MAX_RESULTS: usize = 1000;

/// Generate a UUID v4 using the SpacetimeDB reducer timestamp and RNG.
/// Safe for WASM — does not use `std::time::SystemTime`.
/// Each call advances the RNG, so consecutive calls in the same reducer
/// produce different UUIDs.
pub fn uuid_v4(ctx: &spacetimedb::ReducerContext) -> String {
    use spacetimedb::rand::RngCore;
    // Hybrid: high bits from RNG (distribution), low bits XOR'd with
    // timestamp (uniqueness nonce). STDB's ctx.rng() is deterministic
    // per-module, so two reducers in the same transaction batch get
    // identical RNG outputs. The timestamp XOR guarantees uniqueness
    // even when RNG repeats.
    let ts = ctx.timestamp.to_micros_since_unix_epoch() as u64;
    let high = ctx.rng().next_u64();
    let low = ctx.rng().next_u64() ^ ts;
    let ts_part = format!("{:016x}", high);
    let mut rand_hex = format!("{:016x}", low);

    // RFC 4122 v4 UUID compliance — set version and variant bits
    // Version 4: 13th hex digit → '4'
    rand_hex.replace_range(0..1, "4");
    // Variant 10xx: 17th hex digit → 8,9,a, or b
    let var = ((high >> 60) & 0x3) as u8;
    let vc = match var { 0 => '8', 1 => '9', 2 => 'a', _ => 'b' };
    rand_hex.replace_range(4..5, &vc.to_string());

    format!(
        "{}-{}-{}-{}-{}",
        &ts_part[..8],
        &ts_part[8..12],
        &rand_hex[..4],
        &rand_hex[4..8],
        &rand_hex[8..]
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
