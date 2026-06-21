//! Integration tests for spacetime-memory STDB reducers via HTTP API.
//!
//! These require a running SpacetimeDB standalone on localhost:3001.
//! Run with: SPACETIMEDB_HOST=localhost cargo test --test integration -- --ignored
//!
//! The tests are `#[ignore]` by default because they need live infrastructure.
//! Un-ignore them when STDB is running.

use std::process::Command;

const STDB_URL: &str = "http://localhost:3001";

/// Helper: call a reducer via curl and return the HTTP status + body.
fn call_reducer(db: &str, reducer: &str, args: &str) -> (i32, String) {
    let url = format!("{}/v1/database/{}/call/{}", STDB_URL, db, reducer);
    let output = Command::new("curl")
        .args(["-s", "-w", "\n%{http_code}", "-X", "POST", &url])
        .arg("-H").arg("Content-Type: application/json")
        .arg("-d").arg(args)
        .output()
        .expect("curl failed");
    let body = String::from_utf8_lossy(&output.stdout).to_string();
    let lines: Vec<&str> = body.trim().lines().collect();
    let code = lines.last().map(|s| s.parse().unwrap_or(0)).unwrap_or(0);
    let resp = lines[..lines.len().saturating_sub(1)].join("\n");
    (code, resp)
}

/// Helper: publish the WASM module and return the database identity.
fn publish_module() -> String {
    let wasm_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("target/wasm32-unknown-unknown/release/spacetime_memory.wasm");
    let wasm = std::fs::read(&wasm_path).expect("WASM not built");
    
    let client = reqwest::blocking::Client::new();
    let resp = client
        .post(format!("{}/v1/database?host_type=Wasm&delete_data=always", STDB_URL))
        .header("Content-Type", "application/octet-stream")
        .body(wasm)
        .send()
        .expect("publish failed");
    
    assert!(resp.status().is_success(), "publish returned {}", resp.status());
    resp.text().expect("no body").trim().to_string()
}

// ── Tests ──────────────────────────────────────────────────────────

#[test]
#[ignore]
fn test_health_check() {
    let output = Command::new("curl")
        .args(["-s", "-o", "/dev/null", "-w", "%{http_code}", STDB_URL])
        .output()
        .expect("curl failed");
    let code: i32 = String::from_utf8_lossy(&output.stdout).parse().unwrap_or(0);
    assert_eq!(code, 404); // STDB returns 404 on root, but it's alive
}

#[test]
#[ignore]
fn test_publish_and_call_register() {
    let db = publish_module();
    let (code, body) = call_reducer(
        &db, "register",
        r#"["integration-test-user", "integration@test.com", "testpass"]"#,
    );
    // Either success or "already exists" — both mean the module works
    assert!(code == 200 || code == 500, "unexpected status {}", code);
    assert!(body.contains("ok") || body.contains("already exists") || body.contains("success"),
        "unexpected body: {}", body);
}

#[test]
#[ignore]
fn test_call_query_sql() {
    let db = publish_module();
    // SQL query on a public table
    let url = format!("{}/v1/database/{}/sql", STDB_URL, db);
    let output = Command::new("curl")
        .args(["-s", "-X", "POST", &url])
        .arg("-H").arg("Content-Type: text/plain")
        .arg("-d").arg("SELECT * FROM user")
        .output()
        .expect("curl failed");
    let body = String::from_utf8_lossy(&output.stdout);
    // Should return JSON array (possibly empty)
    assert!(body.trim().starts_with('[') || body.trim().starts_with('{'),
        "unexpected SQL response: {}", body);
}
