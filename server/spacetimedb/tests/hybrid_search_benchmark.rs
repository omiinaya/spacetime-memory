//! WASM hybrid_search latency benchmark -- CI gate.
//!
//! Publishes the WASM module to a running SpacetimeDB instance, seeds test
//! memories with pre-computed embeddings, calls hybrid_search N times, and
//! measures p50 latency.  Fails CI if p50 > 2x baseline.
//!
//! The baseline is stored in `benchmark_results_wasm_hybrid_search.json` at
//! the repo root and is updated on every run so the gate tracks real
//! performance over time.
//!
//! Run (from server/spacetimedb/):
//!   export SPACETIMEDB_HOST=localhost
//!   cargo build --release --target wasm32-unknown-unknown
//!   spacetime start -l 127.0.0.1:3001 --in-memory --non-interactive &
//!   cargo test --test hybrid_search_benchmark -- --ignored --nocapture

use std::path::Path;
use std::process::Command;
use std::time::Instant;

const STDB_URL: &str = "http://localhost:3001";
const ITERATIONS: u32 = 20;
const SEED_COUNT: u32 = 50;
/// WASM expects 1024-dim embeddings (bge-m3)
const EMBED_DIM: usize = 1024;

// HTTP helpers (reqwest-based, handles auth tokens)

/// A thin client that captures and re-sends the SpacetimeDB identity token.
struct StdbClient {
    client: reqwest::blocking::Client,
    base: String,
    /// Captured `spacetime-identity-token` (JWT) for authenticated requests.
    identity_token: Option<String>,
}

impl StdbClient {
    fn new() -> Self {
        Self {
            client: reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(60))
                .build()
                .expect("reqwest client"),
            base: STDB_URL.to_string(),
            identity_token: None,
        }
    }

    /// Establish an identity with the database by doing a GET and capturing
    /// the `spacetime-identity-token` from response headers.
    fn establish_identity(&mut self, db: &str) {
        let url = format!("{}/v1/database/{}", self.base, db);
        let resp = self
            .client
            .get(&url)
            .send()
            .expect("identity handshake GET failed");
        self.capture_token(&resp);
        eprintln!("  identity: {} ({})", resp.status(), db);
    }

    /// Capture identity token from response headers if present.
    fn capture_token(&mut self, resp: &reqwest::blocking::Response) {
        if let Some(token) = resp.headers().get("spacetime-identity-token") {
            if let Ok(t) = token.to_str() {
                if !t.is_empty() {
                    self.identity_token = Some(t.to_string());
                }
            }
        }
    }

    /// Call a reducer with JSON args. Returns (http_status, body).
    fn call_reducer(&mut self, db: &str, reducer: &str, args: &str) -> (u16, String) {
        let url = format!("{}/v1/database/{}/call/{}", self.base, db, reducer);
        let mut req = self
            .client
            .post(&url)
            .header("Content-Type", "application/json")
            .body(args.to_string());
        if let Some(token) = &self.identity_token {
            req = req.header("Authorization", format!("Bearer {}", token));
        }
        let resp = req.send().expect(&format!("reducer {reducer} failed"));
        let status = resp.status().as_u16();
        self.capture_token(&resp);
        let body = resp.text().unwrap_or_default();
        (status, body)
    }

    /// Run a SQL query. Returns (http_status, body).
    fn sql_query(&mut self, db: &str, sql: &str) -> (u16, String) {
        let url = format!("{}/v1/database/{}/sql", self.base, db);
        let mut req = self
            .client
            .post(&url)
            .header("Content-Type", "text/plain")
            .body(sql.to_string());
        if let Some(token) = &self.identity_token {
            req = req.header("Authorization", format!("Bearer {}", token));
        }
        let resp = req.send().expect("sql query failed");
        let status = resp.status().as_u16();
        let body = resp.text().unwrap_or_default();
        (status, body)
    }
}

/// Publish the WASM module and return the database identity string.
fn publish_module() -> String {
    let wasm_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("target/wasm32-unknown-unknown/release/spacetime_memory.wasm");
    let wasm = std::fs::read(&wasm_path)
        .expect("WASM not built -- run: cargo build --release --target wasm32-unknown-unknown");

    let client = reqwest::blocking::Client::new();
    let resp = client
        .post(format!("{}/v1/database?host_type=Wasm&delete_data=always", STDB_URL))
        .header("Content-Type", "application/octet-stream")
        .body(wasm)
        .send()
        .expect("publish failed");

    let status = resp.status();
    let body = resp.text().expect("no body").trim().to_string();
    eprintln!("  publish: HTTP {status} -- {body:?}");
    assert!(status.is_success(), "publish returned {status}");

    // Parse the JSON response to extract database_identity.
    // V2.6+ returns: {"Success":{"domain":null,"database_identity":"...","op":"created"}}
    match serde_json::from_str::<serde_json::Value>(&body) {
        Ok(val) => {
            if let Some(identity) = val["Success"]["database_identity"].as_str() {
                return identity.to_string();
            }
            panic!("publish response missing Success.database_identity: {body}");
        }
        Err(e) => {
            panic!("publish response not valid JSON (HTTP {status}): {e} -- {body}");
        }
    }
}

// JSON helpers (no serde dependency needed for construction)

/// Build a JSON array-of-strings from a list of &str (with minimal escaping).
fn json_str_array(items: &[&str]) -> String {
    let mut s = String::from("[");
    for (i, item) in items.iter().enumerate() {
        if i > 0 { s.push(','); }
        s.push('"');
        for ch in item.chars() {
            match ch {
                '\\' => s.push_str("\\\\"),
                '"' => s.push_str("\\\""),
                '\n' => s.push_str("\\n"),
                '\r' => s.push_str("\\r"),
                '\t' => s.push_str("\\t"),
                c => s.push(c),
            }
        }
        s.push('"');
    }
    s.push(']');
    s
}

/// Generate a JSON embedding array of EMBED_DIM floats with deterministic
/// values that produce cosine_similarity > 0.1 (the hybrid_query threshold
/// used by the semantic strategy).
fn make_embedding(seed: f64) -> String {
    let mut s = String::from("[");
    for i in 0..EMBED_DIM {
        if i > 0 { s.push(','); }
        let val = 0.2 + (i as f64 * 0.001 + seed).fract() * 0.7;
        s.push_str(&format!("{:.6}", val));
    }
    s.push(']');
    s
}

/// Get current UTC ISO-8601 timestamp via `date -u`.
fn utc_now_iso() -> String {
    Command::new("date")
        .args(["-u", "+%Y-%m-%dT%H:%M:%SZ"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "unknown".to_string())
}

// Benchmark

#[test]
#[ignore]
fn hybrid_search_wasm_benchmark() {
    eprintln!("\n=== WASM hybrid_search Benchmark ===");
    eprintln!("  iterations: {ITERATIONS}");
    eprintln!("  seed count: {SEED_COUNT}");
    eprintln!();

    eprint!("Publishing WASM module ... ");
    let db = publish_module();
    eprintln!("OK -- database: {db}");

    let mut c = StdbClient::new();

    eprint!("Establishing identity ... ");
    c.establish_identity(&db);
    eprintln!("OK");

    eprint!("Registering admin user ... ");
    let (code, body) = c.call_reducer(&db, "register", r#"["bench_admin","Bench Admin","benchpass"]"#);
    assert!(code == 200 || code == 500,
        "register failed: HTTP {code} -- {body}  (200=success, 500=already-exists)");
    eprintln!("OK");

    eprint!("Logging in ... ");
    let (code, body) = c.call_reducer(&db, "login", r#"["bench_admin","benchpass"]"#);
    assert!(code == 200 || code == 500,
        "login failed: HTTP {code} -- {body}");
    eprintln!("OK");

    let ws_id = "bench-hybrid-ws-1";
    eprint!("Creating workspace {ws_id} ... ");
    let args = json_str_array(&[ws_id, "Benchmark workspace", "bench-hybrid-ws-1"]);
    let (code, body) = c.call_reducer(&db, "create_workspace", &args);
    assert!(code == 200 || code == 500,
        "create_workspace failed: HTTP {code} -- {body}");
    eprintln!("OK");

    eprint!("Seeding 50 search_index entries ... ");
    let mut items: Vec<String> = Vec::with_capacity(SEED_COUNT as usize);
    for i in 0..SEED_COUNT {
        let eid = format!("bench-entity-{i:04}");
        let content = format!(
            "Benchmark test memory number {i} for WASM hybrid search benchmark. \
             This memory contains keywords about retrieval quality verification."
        );
        let emb = make_embedding(i as f64);
        items.push(format!(
            r#"["{}","memory","{}","{}","{}"]"#,
            ws_id, eid, json_escape(&content), json_escape(&emb)
        ));
    }
    let batch_json = format!("[{}]", items.join(","));
    // The reducer takes a single String arg (JSON-encoded Vec of tuples).
    // HTTP body must be a JSON array of the reducer args: [batch_json_string]
    let call_body = json_str_array(&[&batch_json]);
    let (code, body) = c.call_reducer(&db, "index_entity_batch", &call_body);
    assert_eq!(code, 200,
        "index_entity_batch failed: HTTP {code} -- {body:?}");
    eprintln!("OK");

    let (_code, sql_out) = c.sql_query(&db,
        &format!("SELECT count(*) AS cnt FROM search_index WHERE workspace_id = '{}'", ws_id));
    eprintln!("  search_index rows: {sql_out}");

    let query = "WASM hybrid search benchmark query for performance testing and latency measurement";
    let query_emb = make_embedding(0.5);

    let hy_args = format!(
        r#"["{ws_id}","{}","{}","","",10,"{}"]"#,
        json_escape(query), json_escape(&query_emb), json_escape(r#"["semantic","keyword"]"#)
    );

    eprintln!("\nRunning hybrid_search {ITERATIONS} times:");
    let mut lats: Vec<f64> = Vec::with_capacity(ITERATIONS as usize);
    let mut fails: u32 = 0;

    for i in 0..ITERATIONS {
        let start = Instant::now();
        let (code, body) = c.call_reducer(&db, "hybrid_search", &hy_args);
        let ms = start.elapsed().as_secs_f64() * 1000.0;
        if code == 200 {
            lats.push(ms);
            eprintln!("  [{:2}/{ITERATIONS}] {ms:.1}ms", i + 1);
        } else {
            fails += 1;
            eprintln!("  [{:2}/{ITERATIONS}] FAIL (HTTP {code}): {body:.120}", i + 1);
        }
    }

    assert!(!lats.is_empty(),
        "All {ITERATIONS} hybrid_search calls failed -- cannot compute p50");
    lats.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = lats.len();
    let p50 = percentile(&lats, 50.0);
    let p90 = percentile(&lats, 90.0);
    let p99 = percentile(&lats, 99.0);
    let mean = lats.iter().sum::<f64>() / n as f64;
    let min_val = lats[0];
    let max_val = lats[n - 1];

    eprintln!("\n=== Results ===");
    eprintln!("  n={n}, failures={fails}");
    eprintln!("  p50  = {p50:.1}ms");
    eprintln!("  p90  = {p90:.1}ms");
    eprintln!("  p99  = {p99:.1}ms");
    eprintln!("  mean = {mean:.1}ms");
    eprintln!("  min  = {min_val:.1}ms");
    eprintln!("  max  = {max_val:.1}ms");

    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..").join("..").canonicalize().unwrap();
    let baseline_file = repo_root.join("benchmark_results_wasm_hybrid_search.json");

    let maybe_baseline: Option<f64> = std::fs::read_to_string(&baseline_file)
        .ok()
        .and_then(|raw| serde_json::from_str::<serde_json::Value>(&raw).ok())
        .and_then(|v| v["baseline_p50_ms"].as_f64());

    eprintln!();
    if let Some(baseline) = maybe_baseline {
        let threshold = baseline * 2.0;
        eprintln!("  Baseline: {baseline:.1}ms  2x threshold: {threshold:.1}ms");
        if p50 > threshold {
            panic!(
                "FAIL: hybrid_search p50 ({p50:.1}ms) exceeds 2x baseline ({threshold:.1}ms). \
                 Performance regression detected -- investigate recent hybrid_query changes."
            );
        }
        eprintln!("  GATE PASSED: p50 = {p50:.1}ms <= 2x baseline = {threshold:.1}ms");
    } else {
        eprintln!("  No previous baseline -- first run, establishing baseline at p50 = {p50:.1}ms");
    }

    let result = serde_json::json!({
        "timestamp": utc_now_iso(),
        "database_prefix": &db[..16.min(db.len())],
        "workspace_id": ws_id,
        "iterations": ITERATIONS,
        "seed_count": SEED_COUNT,
        "strategies": ["semantic", "keyword"],
        "baseline_p50_ms": p50,
        "current": {
            "p50_ms": p50,
            "p90_ms": p90,
            "p99_ms": p99,
            "mean_ms": mean,
            "min_ms": min_val,
            "max_ms": max_val,
            "n": n,
            "failures": fails,
        },
        "gate": {
            "condition": "p50 > 2x baseline",
            "passed": maybe_baseline.map_or(true, |b| p50 <= b * 2.0),
        },
    });
    let json_str = serde_json::to_string_pretty(&result).unwrap();
    std::fs::write(&baseline_file, &json_str)
        .unwrap_or_else(|e| eprintln!("WARN: could not write baseline file {baseline_file:?}: {e}"));
    eprintln!("\n  Baseline saved: {}", baseline_file.display());
    eprintln!("\n=== GATE COMPLETE ===");
}

fn percentile(sorted: &[f64], pct: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let n = sorted.len();
    let idx = (pct / 100.0) * (n - 1) as f64;
    let lo = idx.floor() as usize;
    let hi = (idx.ceil() as usize).min(n - 1);
    if lo == hi {
        sorted[lo]
    } else {
        let frac = idx - lo as f64;
        sorted[lo] * (1.0 - frac) + sorted[hi] * frac
    }
}

/// Escape a string for embedding verbatim in a JSON string value.
fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out
}
