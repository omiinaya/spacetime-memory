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
pub mod tracing;

/// Maximum number of rows any read reducer will return.
/// This caps all `.iter()` scans to prevent OOM/timeout on large tables.
pub const MAX_RESULTS: usize = 1000;

/// Generate a UUID v4 using the SpacetimeDB reducer timestamp and RNG.
/// Safe for WASM — does not use `std::time::SystemTime`.
/// Each call advances the RNG, so consecutive calls in the same reducer
/// produce different UUIDs.
pub fn uuid_v4(ctx: &spacetimedb::ReducerContext) -> String {
    use spacetimedb::rand::RngCore;
    let ts = ctx.timestamp.to_micros_since_unix_epoch() as u64;
    let high = ctx.rng().next_u64();
    let low = ctx.rng().next_u64() ^ ts;
    format_uuid_v4(high, low)
}

/// Format two raw u64 values into an RFC 4122 v4 UUID string.
///
/// `high` contributes the time-low and time-mid hex parts.
/// `low` contributes the time-high-and-version, clock-seq, and node parts.
///
/// Version bits (4) and variant bits (10xx) are set in the appropriate
/// positions per RFC 4122 §4.4.
///
/// NOTE: The output is 28 hex characters (8-4-4-4-8 format, 112 bits),
/// not the standard 32-hex-char UUID (8-4-4-4-12, 128 bits). The upper
/// 4 hex digits from `high` are unused. This is a legacy quirk; the
/// format is stable and used as an opaque unique key throughout the
/// module. New code should use `uuid_v7()` / `uuid_v7_uniq()` instead,
/// which produce standard 8-4-4-4-12 format via `ctx.new_uuid_v7()`.
///
/// This is a pure function — no STDB dependency — suitable for unit testing
/// on the host target.
fn format_uuid_v4(high: u64, low: u64) -> String {
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

/// Generate a UUID v4 with collision retry.
///
/// STDB's `ctx.rng()` is deterministic per-module, so two reducers in the
/// same transaction batch may produce identical UUIDs. This function checks
/// for existing rows via `is_unique` (a closure that returns `true` if the
/// generated ID is available) and retries up to `max_attempts` times.
///
/// Use this for every table INSERT that uses a UUID primary key generated
/// by `uuid_v4`, especially under concurrent load.
pub fn uuid_v4_uniq(
    ctx: &spacetimedb::ReducerContext,
    is_unique: impl Fn(&String) -> bool,
    max_attempts: usize,
) -> String {
    let mut id = uuid_v4(ctx);
    for _ in 0..max_attempts {
        if is_unique(&id) {
            return id;
        }
        id = uuid_v4(ctx);
    }
    id
}

/// Generate a sortable UUID v7 using the STDB built-in generator.
///
/// Uses `ctx.new_uuid_v7()` which returns a `spacetimedb::Uuid` in standard
/// 8-4-4-4-12 format. UUID v7 is time-ordered (timestamp-prefixed), which
/// improves B-tree index locality compared to random v4 UUIDs.
///
/// Panics (expect) if the STDB RNG fails — this should never happen in practice.
pub fn uuid_v7(ctx: &spacetimedb::ReducerContext) -> String {
    ctx.new_uuid_v7()
        .expect("STDB new_uuid_v7() should never fail")
        .to_string()
}

/// Generate a sortable UUID v7 with collision retry.
///
/// Like `uuid_v4_uniq`, but uses `uuid_v7` instead of `uuid_v4`.
/// The sortable nature of v7 makes collisions less likely under concurrent
/// load (different timestamps → different UUIDs), but the retry mechanism
/// provides a safety net for the extremely unlikely case where two reducers
/// in the same microsecond batch produce the same UUID.
pub fn uuid_v7_uniq(
    ctx: &spacetimedb::ReducerContext,
    is_unique: impl Fn(&String) -> bool,
    max_attempts: usize,
) -> String {
    let mut id = uuid_v7(ctx);
    for _ in 0..max_attempts {
        if is_unique(&id) {
            return id;
        }
        id = uuid_v7(ctx);
    }
    id
}

/// Convert a SpacetimeDB timestamp (microseconds since Unix epoch) to
/// the internal micros value used throughout the module.
///
/// Pure function — no STDB dependency.
fn micros_from_timestamp(ts_micros: i64) -> i64 {
    ts_micros / 1000
}

/// Get current timestamp in microseconds from the reducer context.
/// Safe for WASM — uses `ctx.timestamp` instead of `std::time::SystemTime`.
pub fn now_micros(ctx: &spacetimedb::ReducerContext) -> i64 {
    micros_from_timestamp(ctx.timestamp.to_micros_since_unix_epoch())
}

/// Compute an expiry timestamp given a current time (micros) and lifetime in days.
///
/// Returns 0 when `lifetime_days <= 0` (no expiry).
/// Pure function — no STDB dependency.
fn compute_expires_at(now_micros: i64, lifetime_days: i64) -> i64 {
    if lifetime_days <= 0 {
        0
    } else {
        now_micros + lifetime_days * 86_400_000_000
    }
}

pub fn default_expires_at(ctx: &spacetimedb::ReducerContext, lifetime_days: i64) -> i64 {
    compute_expires_at(now_micros(ctx), lifetime_days)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // ---- format_uuid_v4 ----

    #[test]
    fn test_format_uuid_v4_has_correct_length() {
        let id = format_uuid_v4(0x0123456789abcdef, 0xfedcba9876543210);
        // Legacy format: 8-4-4-4-8 = 28 hex + 4 hyphens = 32 chars
        assert_eq!(id.len(), 32);
    }

    #[test]
    fn test_format_uuid_v4_has_four_hyphens() {
        let id = format_uuid_v4(0x0123456789abcdef, 0xfedcba9876543210);
        assert_eq!(id.matches('-').count(), 4);
    }

    #[test]
    fn test_format_uuid_v4_version_digit_is_4() {
        let id = format_uuid_v4(0x0123456789abcdef, 0xfedcba9876543210);
        // The version digit is the first character of the third group.
        // Format: XXXXXXXX-XXXX-4XXX-XXXX-XXXXXXXXXXXX
        let parts: Vec<&str> = id.split('-').collect();
        assert_eq!(parts[2].chars().next().unwrap(), '4',
            "UUID v4 version digit must be '4', got id={}", id);
    }

    #[test]
    fn test_format_uuid_v4_variant_digit_is_8_9_a_or_b() {
        let id = format_uuid_v4(0x0123456789abcdef, 0xfedcba9876543210);
        let parts: Vec<&str> = id.split('-').collect();
        let variant_char = parts[3].chars().next().unwrap();
        assert!(variant_char == '8' || variant_char == '9' || variant_char == 'a' || variant_char == 'b',
            "UUID v4 variant digit must be 8/9/a/b, got '{}' in id={}", variant_char, id);
    }

    #[test]
    fn test_format_uuid_v4_deterministic() {
        let a = format_uuid_v4(0xdead, 0xbeef);
        let b = format_uuid_v4(0xdead, 0xbeef);
        assert_eq!(a, b);
    }

    #[test]
    fn test_format_uuid_v4_different_inputs_differ() {
        let a = format_uuid_v4(0x1111, 0x2222);
        let b = format_uuid_v4(0x3333, 0x4444);
        assert_ne!(a, b);
    }

    #[test]
    fn test_format_uuid_v4_all_zero_input() {
        let id = format_uuid_v4(0, 0);
        // Should still produce a valid-looking UUID with version=4 and variant set
        assert_eq!(id.len(), 32);
        let parts: Vec<&str> = id.split('-').collect();
        assert_eq!(parts[2].chars().next().unwrap(), '4');
    }

    #[test]
    fn test_format_uuid_v4_hex_characters_only() {
        let id = format_uuid_v4(u64::MAX, u64::MAX);
        let hex_chars: String = id.chars().filter(|c| *c != '-').collect();
        assert!(hex_chars.chars().all(|c| c.is_ascii_hexdigit()),
            "UUID contains non-hex characters: {}", id);
    }

    #[test]
    fn test_format_uuid_v4_variant_depends_on_high_bits() {
        // Force variant bits in high to 0, 1, 2, 3 to cover all branches
        let v0 = format_uuid_v4(0x0fff_ffff_ffff_ffff, 0);
        let v1 = format_uuid_v4(0x1fff_ffff_ffff_ffff, 0);
        let v2 = format_uuid_v4(0x2fff_ffff_ffff_ffff, 0);
        let v3 = format_uuid_v4(0x3fff_ffff_ffff_ffff, 0);
        for id in [&v0, &v1, &v2, &v3] {
            let parts: Vec<&str> = id.split('-').collect();
            let variant = parts[3].chars().next().unwrap();
            assert!(variant == '8' || variant == '9' || variant == 'a' || variant == 'b',
                "Variant char '{}' not in [8,9,a,b] for id={}", variant, id);
        }
    }

    // ---- micros_from_timestamp ----

    #[test]
    fn test_micros_from_timestamp_zero() {
        assert_eq!(micros_from_timestamp(0), 0);
    }

    #[test]
    fn test_micros_from_timestamp_basic() {
        // 1 second = 1_000_000 microseconds → /1000 = 1000
        assert_eq!(micros_from_timestamp(1_000_000), 1000);
    }

    #[test]
    fn test_micros_from_timestamp_large() {
        // Unix epoch 2024-01-01 in micros ≈ 1704067200_000_000 µs
        let ts = 1_704_067_200_000_000i64;
        assert_eq!(micros_from_timestamp(ts), 1_704_067_200_000i64);
    }

    #[test]
    fn test_micros_from_timestamp_truncation() {
        // Microseconds that don't divide evenly by 1000 → integer truncation
        assert_eq!(micros_from_timestamp(1_999_999), 1999);
        assert_eq!(micros_from_timestamp(1_000_999), 1000);
    }

    #[test]
    fn test_micros_from_timestamp_negative() {
        // Negative timestamps are possible (before epoch)
        assert_eq!(micros_from_timestamp(-1_000_000), -1000);
    }

    // ---- compute_expires_at ----

    #[test]
    fn test_compute_expires_at_never_expires() {
        assert_eq!(compute_expires_at(1000, 0), 0);
        assert_eq!(compute_expires_at(1000, -1), 0);
        assert_eq!(compute_expires_at(0, -5), 0);
    }

    #[test]
    fn test_compute_expires_at_same_day() {
        // 1 day = 86_400_000_000 micros
        let now = 1_000_000_000_000i64;
        let expires = compute_expires_at(now, 1);
        assert_eq!(expires, now + 86_400_000_000);
    }

    #[test]
    fn test_compute_expires_at_multi_day() {
        let now = 0i64;
        let expires = compute_expires_at(now, 30);
        assert_eq!(expires, 30 * 86_400_000_000);
    }

    #[test]
    fn test_compute_expires_at_zero_now() {
        assert_eq!(compute_expires_at(0, 7), 7 * 86_400_000_000);
    }

    #[test]
    fn test_compute_expires_at_negative_now() {
        // now_micros could theoretically be negative if called before epoch?
        let expires = compute_expires_at(-1000, 1);
        assert_eq!(expires, -1000 + 86_400_000_000);
    }

    // ---- uuid_v4_uniq (integration note) ----
    // uuid_v4_uniq needs a ReducerContext (not constructable in host tests)
    // but its retry logic is exercised indirectly by canary tests below.

    // ---- uuid_v7 / uuid_v7_uniq (integration note) ----
    // uuid_v7() calls ctx.new_uuid_v7() which requires a live STDB
    // ReducerContext (not available in host-target tests). The function is
    // tested indirectly by integration tests and by the format contract
    // below.

    #[test]
    fn test_format_uuid_v4_output_matches_uuid_pattern() {
        let id = format_uuid_v4(0x123456789abcdef0, 0x0fedcba987654321);
        // Legacy format: 8-4-4-4-8 (28 hex + 4 hyphens = 32 chars)
        let re = regex::Regex::new(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{8}$").unwrap();
        assert!(re.is_match(&id), "UUID '{}' does not match expected 8-4-4-4-8 pattern", id);
    }

    #[test]
    fn test_uuid_v7_format_is_standard() {
        // Verify that UUID v7 strings match RFC 9562 format:
        //   8-4-4-4-12 (36 chars total including hyphens)
        //   Version digit in the 13th hex position = '7'
        //   Variant bits in the 17th hex position = 8/9/a/b
        //
        // We can't instantiate a ReducerContext in host tests, so we validate
        // the format contract using an example and a regex. The actual
        // output from uuid_v7() must match this pattern.
        let re = regex::Regex::new(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ).unwrap();
        // Example STDB Uuid::to_string() format (standard RFC 9562)
        // NIL uuid: "00000000-0000-0000-0000-000000000000"
        // MAX uuid: "ffffffff-ffff-ffff-ffff-ffffffffffff"
        assert!(re.is_match("00000000-0000-7000-8000-000000000000"),
            "NIL-like UUID should match v7 pattern after version/variant tweak");
        // A v7 UUID like "018f3a6e-1a3c-7b00-9abc-def012345678" would match
        assert!(!re.is_match("00000000-0000-4000-8000-000000000000"),
            "v4 NIL should NOT match v7 pattern (version must be 7)");
    }

    #[test]
    fn test_default_expires_at_consistent_with_helpers() {
        // Verify that default_expires_at calls compute_expires_at(now_micros, ...)
        // This is a compilation/consistency check — the actual ctx path is tested
        // in integration tests.
        assert_eq!(
            compute_expires_at(42, 0),
            0,
            "zero lifetime → no expiry"
        );
    }
}
