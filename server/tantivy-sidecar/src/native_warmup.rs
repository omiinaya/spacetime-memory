//! Native Rust warmup — index existing STDB memories and KG nodes into Tantivy
//! on startup, without spawning a Python subprocess.
//!
//! Uses the SpacetimeDB HTTP API directly to:
//! 1. Get an anonymous identity
//! 2. Register a warmup user
//! 3. List all workspaces
//! 4. Query memories, KG nodes, and notes per workspace
//! 5. Batch-index them directly into the Tantivy writer (no HTTP round-trip)

use crate::{open_or_create_index, SharedState, WorkspaceIndex};
use std::sync::Arc;
use tantivy::{doc, Term};

/// Statistics returned by a completed warmup.
#[derive(Debug, Clone, Default)]
pub struct WarmupStats {
    pub memories_indexed: usize,
    pub nodes_indexed: usize,
    pub errors: usize,
}

/// Run the full warmup: connect to STDB, fetch all data, index into Tantivy.
pub async fn run_native_warmup(state: SharedState) -> Result<WarmupStats, String> {
    let stdb_url = &state.stdb_url;
    let stdb_db = &state.stdb_db;

    println!("Tantivy native warmup: connecting to STDB at {stdb_url}");

    let http = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()
        .map_err(|e| format!("Failed to build HTTP client: {e}"))?;

    let base_url = format!(
        "{}/v1/database/{}",
        stdb_url.trim_end_matches('/'),
        stdb_db
    );

    // ── 1. Get anonymous identity token ──────────────────────────────────
    let token = get_anonymous_token(&http, &base_url).await?;

    // ── 2. Register the warmup identity ──────────────────────────────────
    let auth_token = register_warmup_identity(&http, &base_url, &token).await?;

    println!("Tantivy native warmup: authenticated, listing workspaces...");

    // ── 3. List all workspaces ───────────────────────────────────────────
    let workspace_rows =
        query_table_via_stdb(&http, &base_url, &auth_token, "workspace", "", &["id", "name"])
            .await?;

    let ws_count = workspace_rows.len();
    println!("Tantivy native warmup: found {ws_count} workspace(s)");

    let mut stats = WarmupStats::default();

    if ws_count == 0 {
        println!("Tantivy native warmup: no workspaces found, nothing to index");
        return Ok(stats);
    }

    // ── 4. For each workspace, index memories and KG nodes ────────────────
    for ws_json in &workspace_rows {
        let ws_id = ws_json
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let ws_name = ws_json
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or(ws_id);

        if ws_id.is_empty() {
            continue;
        }

        let ws_short = if ws_name.len() > 16 { &ws_name[..16] } else { ws_name };
        println!("  Workspace: {ws_short} ({})", &ws_id[..ws_id.len().min(16)]);

        // Open a temporary writer for warmup — not cached in DashMap.
        // Caching would keep ~7 threads/workspace alive forever; with 3K+
        // workspaces that's a thread bomb. The writer drops after indexing.
        let ws_index = open_or_create_index(&state.index_dir, ws_id)
            .map_err(|e| format!("Failed to open index for workspace '{ws_id}': {e}"))?;

        // ── Memories ─────────────────────────────────────────────────────
        let mem_start = std::time::Instant::now();
        match index_memories(&http, &base_url, &auth_token, ws_id, &ws_index).await {
            Ok(count) => {
                if count > 0 {
                    stats.memories_indexed += count;
                    println!(
                        "    Memories: {count} ({}ms)",
                        mem_start.elapsed().as_millis()
                    );
                }
            }
            Err(e) => {
                println!("    ✗ Failed to index memories: {e}");
                stats.errors += 1;
            }
        }

        // ── KG Nodes ────────────────────────────────────────────────────
        let node_start = std::time::Instant::now();
        match index_nodes(&http, &base_url, &auth_token, ws_id, &ws_index).await {
            Ok(count) => {
                if count > 0 {
                    stats.nodes_indexed += count;
                    println!(
                        "    KG Nodes: {count} ({}ms)",
                        node_start.elapsed().as_millis()
                    );
                }
            }
            Err(e) => {
                println!("    ✗ Failed to index KG nodes: {e}");
                stats.errors += 1;
            }
        }

        // ── Notes (searchable content) ───────────────────────────────────
        let note_start = std::time::Instant::now();
        match index_notes(&http, &base_url, &auth_token, ws_id, &ws_index).await {
            Ok(count) => {
                if count > 0 {
                    stats.memories_indexed += count;
                    println!(
                        "    Notes: {count} ({}ms)",
                        note_start.elapsed().as_millis()
                    );
                }
            }
            Err(e) => {
                println!("    ✗ Failed to index notes: {e}");
                stats.errors += 1;
            }
        }
    }

    println!(
        "Tantivy native warmup complete: {} memories, {} nodes, {} errors",
        stats.memories_indexed, stats.nodes_indexed, stats.errors
    );

    Ok(stats)
}

// ── Individual table indexers ────────────────────────────────────────────

/// Query all memories for a workspace and write them to the Tantivy index.
async fn index_memories(
    http: &reqwest::Client,
    base_url: &str,
    token: &str,
    ws_id: &str,
    ws_index: &Arc<WorkspaceIndex>,
) -> Result<usize, String> {
    let memories = query_table_via_stdb(
        http,
        base_url,
        token,
        "memory",
        ws_id,
        &["id", "content"],
    )
    .await?;

    if memories.is_empty() {
        return Ok(0);
    }

    let mut count = 0usize;
    {
        let mut writer = ws_index.writer.lock().unwrap();
        for mem in &memories {
            let mem_id = mem.get("id").and_then(|v| v.as_str()).unwrap_or("");
            let content = mem.get("content").and_then(|v| v.as_str()).unwrap_or("");
            if content.is_empty() || mem_id.is_empty() {
                continue;
            }

            // Upsert: delete existing doc for this entity_id
            let entity_id_term = Term::from_field_text(ws_index.entity_id_field, mem_id);
            writer.delete_term(entity_id_term);

            let _ = writer.add_document(doc!(
                ws_index.workspace_field => ws_id.to_string(),
                ws_index.entity_id_field => mem_id.to_string(),
                ws_index.content_field => content.to_string(),
                ws_index.entity_type_field => "memory".to_string(),
            ));
            count += 1;
        }
        writer
            .commit()
            .map_err(|e| format!("Failed to commit memories for '{ws_id}': {e}"))?;
    }

    Ok(count)
}

/// Query all KG nodes for a workspace and write them to the Tantivy index.
async fn index_nodes(
    http: &reqwest::Client,
    base_url: &str,
    token: &str,
    ws_id: &str,
    ws_index: &Arc<WorkspaceIndex>,
) -> Result<usize, String> {
    let nodes = query_table_via_stdb(
        http,
        base_url,
        token,
        "kg_node",
        ws_id,
        &["id", "label", "summary"],
    )
    .await?;

    if nodes.is_empty() {
        return Ok(0);
    }

    let mut count = 0usize;
    {
        let mut writer = ws_index.writer.lock().unwrap();
        for node in &nodes {
            let node_id = node.get("id").and_then(|v| v.as_str()).unwrap_or("");
            let label = node.get("label").and_then(|v| v.as_str()).unwrap_or("");
            let summary = node.get("summary").and_then(|v| v.as_str()).unwrap_or("");
            let searchable = if summary.is_empty() {
                label.to_string()
            } else {
                format!("{label}: {summary}")
            };
            if searchable.trim().is_empty()
                || searchable.trim() == ":"
                || node_id.is_empty()
            {
                continue;
            }

            // Upsert: delete existing doc for this entity_id
            let entity_id_term = Term::from_field_text(ws_index.entity_id_field, node_id);
            writer.delete_term(entity_id_term);

            let _ = writer.add_document(doc!(
                ws_index.workspace_field => ws_id.to_string(),
                ws_index.entity_id_field => node_id.to_string(),
                ws_index.content_field => searchable,
                ws_index.entity_type_field => "node".to_string(),
            ));
            count += 1;
        }
        writer
            .commit()
            .map_err(|e| format!("Failed to commit nodes for '{ws_id}': {e}"))?;
    }

    Ok(count)
}

/// Query all notes for a workspace and write them to the Tantivy index.
async fn index_notes(
    http: &reqwest::Client,
    base_url: &str,
    token: &str,
    ws_id: &str,
    ws_index: &Arc<WorkspaceIndex>,
) -> Result<usize, String> {
    let notes = query_table_via_stdb(
        http,
        base_url,
        token,
        "note",
        ws_id,
        &["id", "title", "content"],
    )
    .await?;

    if notes.is_empty() {
        return Ok(0);
    }

    let mut count = 0usize;
    {
        let mut writer = ws_index.writer.lock().unwrap();
        for note_ in &notes {
            let note_id = note_.get("id").and_then(|v| v.as_str()).unwrap_or("");
            let title = note_.get("title").and_then(|v| v.as_str()).unwrap_or("");
            let content = note_.get("content").and_then(|v| v.as_str()).unwrap_or("");
            let searchable = if content.is_empty() {
                title.to_string()
            } else {
                format!("{title}\n{content}")
            };
            if searchable.trim().is_empty() || note_id.is_empty() {
                continue;
            }

            // Upsert: delete existing doc for this entity_id
            let entity_id_term = Term::from_field_text(ws_index.entity_id_field, note_id);
            writer.delete_term(entity_id_term);

            let _ = writer.add_document(doc!(
                ws_index.workspace_field => ws_id.to_string(),
                ws_index.entity_id_field => format!("note_{note_id}"),
                ws_index.content_field => searchable,
                ws_index.entity_type_field => "note".to_string(),
            ));
            count += 1;
        }
        writer
            .commit()
            .map_err(|e| format!("Failed to commit notes for '{ws_id}': {e}"))?;
    }

    Ok(count)
}

// ── STDB HTTP API helpers ─────────────────────────────────────────────────

/// Get an anonymous identity token from STDB.
async fn get_anonymous_token(
    http: &reqwest::Client,
    base_url: &str,
) -> Result<String, String> {
    let resp = http
        .get(base_url)
        .send()
        .await
        .map_err(|e| format!("Failed to connect to STDB at {base_url}: {e}"))?;

    let token = resp
        .headers()
        .get("spacetime-identity-token")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string())
        .ok_or_else(|| {
            format!(
                "No spacetime-identity-token in STDB response (HTTP {})",
                resp.status()
            )
        })?;

    Ok(token)
}

/// Register the warmup identity and return an authenticated token.
async fn register_warmup_identity(
    http: &reqwest::Client,
    base_url: &str,
    token: &str,
) -> Result<String, String> {
    // Register with a unique name per process
    let warmup_username = format!("tantivy-warmup-{}", std::process::id());
    let register_payload = serde_json::json!([
        warmup_username,
        "Tantivy Warmup",
        "warmup123",
    ]);

    let resp = http
        .post(format!("{base_url}/call/register"))
        .header("Authorization", format!("Bearer {token}"))
        .header("Content-Type", "application/json")
        .json(&register_payload)
        .send()
        .await
        .map_err(|e| format!("Register request failed: {e}"))?;

    // Get the authenticated token from the response, if available
    let auth_token = if resp.status().is_success() {
        resp.headers()
            .get("spacetime-identity-token")
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string())
            .unwrap_or_else(|| {
                println!("Tantivy native warmup: no new token in register response, using original");
                token.to_string()
            })
    } else {
        // If registration failed (e.g. user already exists), just use the original token
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        println!("Tantivy native warmup: register returned HTTP {status}: {body}");
        println!("Tantivy native warmup: continuing with anonymous token");
        token.to_string()
    };

    Ok(auth_token)
}

/// Query a private table through the STDB `query_table` reducer, then read
/// results via SQL from the `query_result` table.
async fn query_table_via_stdb(
    http: &reqwest::Client,
    base_url: &str,
    token: &str,
    table: &str,
    workspace_id: &str,
    columns: &[&str],
) -> Result<Vec<serde_json::Map<String, serde_json::Value>>, String> {
    let query_id = uuid::Uuid::new_v4().to_string();

    // Call the query_table reducer
    let payload = serde_json::json!([
        query_id,
        table,
        workspace_id,
        "{}",
        serde_json::json!(columns),
    ]);

    let resp = http
        .post(format!("{base_url}/call/query_table"))
        .header("Authorization", format!("Bearer {token}"))
        .header("Content-Type", "application/json")
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("query_table call failed: {e}"))?;

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("query_table returned HTTP {status}: {body}"));
    }

    // Wait briefly for the reducer result to be available, then read via SQL
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

    // Read results from query_result table via SQL
    let sql_query = format!(
        "SELECT row_json FROM query_result WHERE query_id = '{}'",
        escape_sql_string(&query_id)
    );

    let resp = http
        .post(format!("{base_url}/sql"))
        .header("Authorization", format!("Bearer {token}"))
        .header("Content-Type", "text/plain")
        .body(sql_query)
        .send()
        .await
        .map_err(|e| format!("SQL query failed: {e}"))?;

    let sql_text = resp
        .text()
        .await
        .map_err(|e| format!("Failed to read SQL response: {e}"))?;

    // Parse SQL response — SpacetimeDB returns an array of table results
    // Each table result has { schema, rows: [[col1, col2, ...]], ... }
    let sql_result: Vec<serde_json::Value> = serde_json::from_str(&sql_text)
        .map_err(|e| {
            format!(
                "Failed to parse SQL response: {e} (text: {})",
                &sql_text[..sql_text.len().min(200)]
            )
        })?;

    let mut rows: Vec<serde_json::Map<String, serde_json::Value>> = Vec::new();

    for table_result in &sql_result {
        if let Some(row_array) = table_result.get("rows").and_then(|v| v.as_array()) {
            for row in row_array {
                if let Some(row_arr) = row.as_array() {
                    if let Some(row_json_str) = row_arr.first().and_then(|v| v.as_str()) {
                        if let Ok(parsed) = serde_json::from_str::<
                            serde_json::Map<String, serde_json::Value>,
                        >(row_json_str)
                        {
                            rows.push(parsed);
                        }
                    }
                }
            }
        }
    }

    Ok(rows)
}

/// Minimal SQL string escaping — replaces single quotes with two single quotes.
fn escape_sql_string(s: &str) -> String {
    s.replace('\'', "''")
}

#[cfg(test)]
mod tests {
    #[test]
    fn it_works() {
        assert_eq!(2 + 2, 4);
    }
}
