use axum::{extract::State, routing::{get, post}, Json, Router};
use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Arc;
use tantivy::collector::TopDocs;
use tantivy::query::{BooleanQuery, Occur, Query, QueryParser, TermQuery};
use tantivy::schema::*;
use tantivy::{doc, Index, IndexReader, IndexWriter, ReloadPolicy, TantivyDocument};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct IndexRequest {
    workspace_id: String,
    entity_id: String,
    content: String,
    entity_type: Option<String>,
}

#[derive(Deserialize)]
struct IndexBatchRequest {
    items: Vec<IndexRequest>,
}

#[derive(Deserialize)]
struct SearchRequest {
    workspace_id: String,
    query: String,
    limit: Option<usize>,
}

#[derive(Serialize)]
struct SearchResult {
    entity_id: String,
    score: f32,
    content: String,
    entity_type: String,
}

#[derive(Deserialize)]
struct DeleteRequest {
    workspace_id: String,
    entity_id: String,
}

#[derive(Serialize)]
struct HealthResponse {
    status: String,
    workspace_count: usize,
}

#[derive(Serialize)]
struct WarmupResponse {
    status: String,
    memories_indexed: usize,
    nodes_indexed: usize,
    errors: usize,
    message: String,
}

// ---------------------------------------------------------------------------
// Application state — one index per workspace
// ---------------------------------------------------------------------------

struct WorkspaceIndex {
    reader: IndexReader,
    writer: Arc<std::sync::Mutex<IndexWriter>>,
    index: Index,
    content_field: Field,
    workspace_field: Field,
    entity_id_field: Field,
    entity_type_field: Field,
}

struct AppState {
    workspaces: DashMap<String, Arc<WorkspaceIndex>>,
    index_dir: PathBuf,
    tantivy_url: String,
    stdb_url: String,
    stdb_db: String,
}

type SharedState = Arc<AppState>;

// ---------------------------------------------------------------------------
// Schema factory
// ---------------------------------------------------------------------------

fn build_schema() -> Schema {
    let mut builder = Schema::builder();
    builder.add_text_field("workspace_id", STRING | STORED);
    builder.add_text_field("entity_id", STRING | STORED);
    builder.add_text_field(
        "content",
        TEXT | STORED,
    );
    builder.add_text_field("entity_type", STRING | STORED);
    builder.build()
}

fn open_or_create_index(
    index_dir: &PathBuf,
    workspace_id: &str,
) -> Result<Arc<WorkspaceIndex>, String> {
    let schema = build_schema();
    let content_field = schema.get_field("content").unwrap();
    let workspace_field = schema.get_field("workspace_id").unwrap();
    let entity_id_field = schema.get_field("entity_id").unwrap();
    let entity_type_field = schema.get_field("entity_type").unwrap();

    let ws_dir = index_dir.join(workspace_id);
    std::fs::create_dir_all(&ws_dir)
        .map_err(|e| format!("Failed to create index dir: {e}"))?;

    let index = if ws_dir.join("meta.json").exists() {
        Index::open_in_dir(&ws_dir)
            .map_err(|e| format!("Failed to open index: {e}"))?
    } else {
        Index::create_in_dir(&ws_dir, schema.clone())
            .map_err(|e| format!("Failed to create index: {e}"))?
    };

    let writer = index
        .writer(40_000_000)
        .map_err(|e| format!("Failed to create writer: {e}"))?;
    let reader = index
        .reader_builder()
        .reload_policy(ReloadPolicy::OnCommitWithDelay)
        .try_into()
        .map_err(|e| format!("Failed to create reader: {e}"))?;

    Ok(Arc::new(WorkspaceIndex {
        reader,
        writer: Arc::new(std::sync::Mutex::new(writer)),
        index,
        content_field,
        workspace_field,
        entity_id_field,
        entity_type_field,
    }))
}

// ---------------------------------------------------------------------------
// HTTP handlers
// ---------------------------------------------------------------------------

async fn health(state: State<SharedState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".into(),
        workspace_count: state.workspaces.len(),
    })
}

async fn index_doc(
    state: State<SharedState>,
    Json(req): Json<IndexRequest>,
) -> Result<Json<serde_json::Value>, String> {
    let ws = state
        .workspaces
        .entry(req.workspace_id.clone())
        .or_try_insert_with(|| open_or_create_index(&state.index_dir, &req.workspace_id))
        .map_err(|e| e)?;

    let ws = ws.value().clone();

    // Delete existing doc for this entity_id (upsert)
    let entity_id_term = Term::from_field_text(ws.entity_id_field, &req.entity_id);
    ws.writer
        .lock()
        .unwrap()
        .delete_term(entity_id_term);

    let entity_type = req.entity_type.unwrap_or_else(|| "memory".to_string());
    ws.writer.lock().unwrap()
        .add_document(doc!(
            ws.workspace_field => req.workspace_id.clone(),
            ws.entity_id_field => req.entity_id.clone(),
            ws.content_field => req.content.clone(),
            ws.entity_type_field => entity_type,
        ))
        .map_err(|e| format!("Failed to add document: {e}"))?;

    ws.writer
        .lock()
        .unwrap()
        .commit()
        .map_err(|e| format!("Failed to commit: {e}"))?;

    Ok(Json(serde_json::json!({
        "status": "ok",
        "entity_id": req.entity_id,
        "workspace_id": req.workspace_id,
    })))
}

async fn index_batch(
    state: State<SharedState>,
    Json(req): Json<IndexBatchRequest>,
) -> Result<Json<serde_json::Value>, String> {
    if req.items.is_empty() {
        return Ok(Json(serde_json::json!({"status": "ok", "count": 0})));
    }

    // Group items by workspace_id so each workspace's writer gets one lock cycle
    let mut by_workspace: std::collections::HashMap<String, Vec<IndexRequest>> =
        std::collections::HashMap::new();
    for item in req.items {
        by_workspace
            .entry(item.workspace_id.clone())
            .or_default()
            .push(item);
    }

    let mut total = 0usize;
    for (ws_id, items) in &by_workspace {
        let ws = state
            .workspaces
            .entry(ws_id.clone())
            .or_try_insert_with(|| open_or_create_index(&state.index_dir, ws_id))
            .map_err(|e| e)?;

        let ws = ws.value().clone();
        let mut writer = ws.writer.lock().unwrap();

        for item in items {
            // Delete existing doc for this entity_id (upsert)
            let entity_id_term =
                Term::from_field_text(ws.entity_id_field, &item.entity_id);
            writer.delete_term(entity_id_term);

            let entity_type = item
                .entity_type
                .clone()
                .unwrap_or_else(|| "memory".to_string());
            writer
                .add_document(doc!(
                    ws.workspace_field => item.workspace_id.clone(),
                    ws.entity_id_field => item.entity_id.clone(),
                    ws.content_field => item.content.clone(),
                    ws.entity_type_field => entity_type,
                ))
                .map_err(|e| format!("Failed to add document: {e}"))?;

            total += 1;
        }

        // Single commit per workspace
        writer
            .commit()
            .map_err(|e| format!("Failed to commit: {e}"))?;
    }

    Ok(Json(serde_json::json!({
        "status": "ok",
        "count": total,
    })))
}

async fn search(
    state: State<SharedState>,
    Json(req): Json<SearchRequest>,
) -> Result<Json<Vec<SearchResult>>, String> {
    let ws = match state.workspaces.get(&req.workspace_id) {
        Some(ws) => ws.value().clone(),
        None => return Ok(Json(vec![])),
    };

    let limit = req.limit.unwrap_or(50);

    let searcher = ws.reader.searcher();

    // Build query: use Tantivy's QueryParser for proper tokenization,
    // stemming, and multi-word query support.
    let query_parser = QueryParser::new(
        ws.index.schema(),
        vec![ws.content_field],
        ws.index.tokenizers().clone(),
    );
    let text_query = match query_parser.parse_query(&req.query) {
        Ok(q) => q,
        Err(_) => return Ok(Json(vec![])),
    };

    let workspace_term =
        Term::from_field_text(ws.workspace_field, &req.workspace_id);
    let workspace_query: Box<dyn Query> =
        Box::new(TermQuery::new(workspace_term, IndexRecordOption::Basic));

    // Combine: workspace filter AND parsed text query
    let combined: Box<dyn Query> = Box::new(BooleanQuery::new(vec![
        (Occur::Must, workspace_query),
        (Occur::Must, text_query),
    ]));

    let top_docs = searcher
        .search(&combined, &TopDocs::with_limit(limit))
        .map_err(|e| format!("Search failed: {e}"))?;

    let mut results = Vec::with_capacity(top_docs.len());
    for (score, doc_addr) in top_docs {
        let doc: TantivyDocument = searcher
            .doc(doc_addr)
            .map_err(|e| format!("Failed to retrieve doc: {e}"))?;

        let entity_id = doc
            .get_first(ws.entity_id_field)
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let content = doc
            .get_first(ws.content_field)
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let entity_type = doc
            .get_first(ws.entity_type_field)
            .and_then(|v| v.as_str())
            .unwrap_or("memory")
            .to_string();

        results.push(SearchResult {
            entity_id,
            score,
            content,
            entity_type,
        });
    }

    Ok(Json(results))
}

async fn delete_doc(
    state: State<SharedState>,
    Json(req): Json<DeleteRequest>,
) -> Result<Json<serde_json::Value>, String> {
    let ws = match state.workspaces.get(&req.workspace_id) {
        Some(ws) => ws.value().clone(),
        None => {
            return Ok(Json(serde_json::json!({
                "status": "not_found",
                "entity_id": req.entity_id,
            })))
        }
    };

    let entity_id_term = Term::from_field_text(ws.entity_id_field, &req.entity_id);
    ws.writer
        .lock()
        .unwrap()
        .delete_term(entity_id_term);
    ws.writer
        .lock()
        .unwrap()
        .commit()
        .map_err(|e| format!("Failed to commit: {e}"))?;

    Ok(Json(serde_json::json!({
        "status": "ok",
        "entity_id": req.entity_id,
    })))
}

async fn warmup(
    state: State<SharedState>,
) -> Result<Json<WarmupResponse>, String> {
    // Run the Python reindex script
    let script_path = std::env::var("REINDEX_SCRIPT")
        .unwrap_or_else(|_| "/app/scripts/reindex-tantivy.py".to_string());
    let tantivy_url = &state.tantivy_url;
    let stdb_url = &state.stdb_url;
    let stdb_db = &state.stdb_db;

    println!("Tantivy sidecar: starting warmup via {}", script_path);

    let output = tokio::process::Command::new("python3")
        .arg(&script_path)
        .arg("--tantivy-url")
        .arg(tantivy_url)
        .env("SPACETIMEDB_HOST", stdb_url.trim_start_matches("http://").trim_start_matches("https://"))
        .env("SPACETIMEDB_PORT", "3001")
        .env("SPACETIMEDB_DB", stdb_db)
        .output()
        .await
        .map_err(|e| format!("Failed to spawn warmup script: {e}"))?;

    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        println!("Tantivy warmup completed:\n{}", stdout);
        
        // Parse the output to extract counts (best effort)
        let mut memories = 0;
        let mut nodes = 0;
        let mut errors = 0;
        for line in stdout.lines() {
            if line.contains("Indexed") && line.contains("memories") {
                if let Some(num_str) = line.split_whitespace().find(|s| s.chars().all(|c| c.is_ascii_digit())) {
                    memories = num_str.parse().unwrap_or(0);
                }
            } else if line.contains("✗") || line.contains("Failed") || line.contains("error") {
                errors += 1;
            }
        }
        
        Ok(Json(WarmupResponse {
            status: "ok".into(),
            memories_indexed: memories,
            nodes_indexed: nodes,
            errors,
            message: "Warmup completed successfully".into(),
        }))
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        eprintln!("Tantivy warmup failed:\n{}", stderr);
        Ok(Json(WarmupResponse {
            status: "error".into(),
            memories_indexed: 0,
            nodes_indexed: 0,
            errors: 1,
            message: format!("Warmup script failed: {}", stderr),
        }))
    }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    let warmup_on_start = args.contains(&"--warmup".to_string());

    let index_dir = std::env::var("TANTIVY_INDEX_DIR")
        .unwrap_or_else(|_| "data/tantivy".to_string());
    let index_dir = PathBuf::from(index_dir);
    std::fs::create_dir_all(&index_dir).expect("Failed to create index directory");

    let tantivy_port: u16 = std::env::var("TANTIVY_PORT")
        .unwrap_or_else(|_| "9091".to_string())
        .parse()
        .expect("TANTIVY_PORT must be a valid port number");
    let tantivy_url = format!("http://0.0.0.0:{}", tantivy_port);

    let stdb_url = std::env::var("SPACETIMEDB_URL")
        .unwrap_or_else(|_| "http://localhost:3001".to_string());
    let stdb_db = std::env::var("SPACETIMEDB_DB")
        .unwrap_or_else(|_| "spacetime-memory".to_string());

    println!("Tantivy sidecar: index directory = {:?}", index_dir);

    // Pre-open existing workspace indexes
    let workspaces = DashMap::new();
    if let Ok(entries) = std::fs::read_dir(&index_dir) {
        for entry in entries.flatten() {
            if entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                let ws_id = entry.file_name().to_string_lossy().to_string();
                match open_or_create_index(&index_dir, &ws_id) {
                    Ok(ws) => {
                        workspaces.insert(ws_id.clone(), ws);
                        println!("Tantivy sidecar: loaded workspace '{}'", ws_id);
                    }
                    Err(e) => {
                        eprintln!(
                            "Tantivy sidecar: failed to load workspace '{}': {}",
                            ws_id, e
                        );
                    }
                }
            }
        }
    }

    let state = Arc::new(AppState {
        workspaces,
        index_dir,
        tantivy_url: tantivy_url.clone(),
        stdb_url,
        stdb_db,
    });

    // Run warmup on startup if requested
    if warmup_on_start {
        println!("Tantivy sidecar: running warmup on startup...");
        let state_clone = state.clone();
        tokio::spawn(async move {
            // Give the server a moment to start accepting connections
            tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
            if let Err(e) = run_warmup(state_clone).await {
                eprintln!("Tantivy warmup failed: {}", e);
            }
        });
    }

    let app = Router::new()
        .route("/health", get(health))
        .route("/index", post(index_doc))
        .route("/index/batch", post(index_batch))
        .route("/search", post(search))
        .route("/delete", post(delete_doc))
        .route("/warmup", post(warmup))
        .with_state(state);

    let addr = format!("0.0.0.0:{}", tantivy_port);
    println!("Tantivy sidecar: listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

async fn run_warmup(state: SharedState) -> Result<(), String> {
    let script_path = std::env::var("REINDEX_SCRIPT")
        .unwrap_or_else(|_| "/app/scripts/reindex-tantivy.py".to_string());
    let tantivy_url = &state.tantivy_url;
    let stdb_url = &state.stdb_url;
    let stdb_db = &state.stdb_db;

    // Extract host from stdb_url (remove http:// or https://)
    let stdb_host = stdb_url
        .trim_start_matches("http://")
        .trim_start_matches("https://");

    println!("Tantivy sidecar: starting warmup via {}", script_path);

    let output = tokio::process::Command::new("python3")
        .arg(&script_path)
        .arg("--tantivy-url")
        .arg(tantivy_url)
        .env("SPACETIMEDB_HOST", stdb_host)
        .env("SPACETIMEDB_PORT", "3001")
        .env("SPACETIMEDB_DB", stdb_db)
        .output()
        .await
        .map_err(|e| format!("Failed to spawn warmup script: {e}"))?;

    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        println!("Tantivy warmup completed:\n{}", stdout);
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        eprintln!("Tantivy warmup failed:\n{}", stderr);
        Err(format!("Warmup script failed: {}", stderr))
    }
}