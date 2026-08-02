mod hnsw;
mod native_warmup;

use axum::{extract::{Path, State}, http::StatusCode, response::IntoResponse, routing::{get, post}, Json, Router};
use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;
use tantivy::collector::TopDocs;
use tantivy::query::{BooleanQuery, Occur, Query, QueryParser, TermQuery};
use tantivy::schema::*;
use tantivy::{doc, Index, IndexReader, IndexWriter, ReloadPolicy, TantivyDocument};

const WRITER_MEMORY_BUDGET: usize = 8_000_000;  // 8 MB per workspace writer (down from 40MB)
const EVICTION_TTL_SECS: u64 = 1800;             // 30 min idle before evicting a workspace
const EVICTION_SWEEP_INTERVAL_SECS: u64 = 300;   // sweep every 5 minutes
const HNSW_PERSIST_INTERVAL_SECS: u64 = 300;     // persist HNSW graphs every 5 minutes

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct IndexRequest {
    workspace_id: String,
    entity_id: String,
    content: String,
    entity_type: Option<String>,
    /// Optional JSON array of f32 embedding values for vector indexing
    embedding_json: Option<String>,
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

#[derive(Deserialize)]
struct VectorSearchRequest {
    workspace_id: String,
    /// JSON array of f32 embedding values
    embedding: Vec<f32>,
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
    embedding_field: Field,
    hnsw_graph: Arc<std::sync::Mutex<hnsw::HnswGraph>>,
    /// Last time this workspace was accessed (for TTL eviction)
    last_accessed: std::sync::Mutex<Instant>,
}

struct AppState {
    workspaces: DashMap<String, Arc<WorkspaceIndex>>,
    index_dir: PathBuf,
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
    builder.add_text_field(
        "embedding_json",
        STRING | STORED,
    );
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
    let embedding_field = schema.get_field("embedding_json").unwrap();

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
        .writer(WRITER_MEMORY_BUDGET)
        .map_err(|e| format!("Failed to create writer: {e}"))?;
    let reader = index
        .reader_builder()
        .reload_policy(ReloadPolicy::OnCommitWithDelay)
        .try_into()
        .map_err(|e| format!("Failed to create reader: {e}"))?;

    // Load existing HNSW graph or create new
    let hnsw_path = index_dir.join(workspace_id).join("hnsw_graph.json");
    let hnsw_graph = if hnsw_path.exists() {
        match std::fs::read_to_string(&hnsw_path) {
            Ok(json) => serde_json::from_str(&json).unwrap_or_else(|_| hnsw::HnswGraph::new()),
            Err(_) => hnsw::HnswGraph::new(),
        }
    } else {
        hnsw::HnswGraph::new()
    };

    Ok(Arc::new(WorkspaceIndex {
        reader,
        writer: Arc::new(std::sync::Mutex::new(writer)),
        index,
        content_field,
        workspace_field,
        entity_id_field,
        entity_type_field,
        embedding_field,
        hnsw_graph: Arc::new(std::sync::Mutex::new(hnsw_graph)),
        last_accessed: std::sync::Mutex::new(Instant::now()),
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

async fn metrics(state: State<SharedState>) -> impl IntoResponse {
    let ws_count = state.workspaces.len();
    let body = format!(
        "# HELP tantivy_workspace_count Number of active workspace indexes\n\
         # TYPE tantivy_workspace_count gauge\n\
         tantivy_workspace_count {}\n\
         # HELP tantivy_up Sidecar is running\n\
         # TYPE tantivy_up gauge\n\
         tantivy_up 1\n",
        ws_count
    );
    (
        StatusCode::OK,
        [("content-type", "text/plain; version=0.0.4; charset=utf-8")],
        body,
    )
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
    touch_workspace(&ws);

    // Delete existing doc for this entity_id (upsert)
    let entity_id_term = Term::from_field_text(ws.entity_id_field, &req.entity_id);
    ws.writer
        .lock()
        .unwrap()
        .delete_term(entity_id_term);

    let entity_type = req.entity_type.unwrap_or_else(|| "memory".to_string());
    let embedding_json = req.embedding_json.unwrap_or_else(|| "[]".to_string());
    ws.writer.lock().unwrap()
        .add_document(doc!(
            ws.workspace_field => req.workspace_id.clone(),
            ws.entity_id_field => req.entity_id.clone(),
            ws.content_field => req.content.clone(),
            ws.entity_type_field => entity_type,
            ws.embedding_field => embedding_json.clone(),
        ))
        .map_err(|e| format!("Failed to add document: {e}"))?;

    ws.writer
        .lock()
        .unwrap()
        .commit()
        .map_err(|e| format!("Failed to commit: {e}"))?;

    // Index embedding in HNSW graph
    if embedding_json != "[]" {
        if let Ok(emb) = serde_json::from_str::<Vec<f64>>(&embedding_json) {
            let f32_emb: Vec<f32> = emb.into_iter().map(|v| v as f32).collect();
            if !f32_emb.is_empty() {
                ws.hnsw_graph.lock().unwrap().insert(&req.entity_id, f32_emb);
            }
        }
    }

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
        touch_workspace(&ws);
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

        // Update HNSW graph for all items in this batch
        for item in items {
            if let Some(emb_json) = &item.embedding_json {
                if emb_json != "[]" {
                    if let Ok(emb) = serde_json::from_str::<Vec<f64>>(emb_json) {
                        let f32_emb: Vec<f32> = emb.into_iter().map(|v| v as f32).collect();
                        if !f32_emb.is_empty() {
                            ws.hnsw_graph.lock().unwrap().insert(&item.entity_id, f32_emb);
                        }
                    }
                }
            }
        }
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
    touch_workspace(&ws);

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

async fn vector_search(
    state: State<SharedState>,
    Json(req): Json<VectorSearchRequest>,
) -> Result<Json<Vec<SearchResult>>, String> {
    let ws = match state.workspaces.get(&req.workspace_id) {
        Some(ws) => ws.value().clone(),
        None => return Ok(Json(vec![])),
    };
    touch_workspace(&ws);

    let limit = req.limit.unwrap_or(50);
    let results = {
        let hnsw = ws.hnsw_graph.lock().unwrap();
        hnsw.search(&req.embedding, limit)
    };

    // Retrieve content from tantivy for each result
    let searcher = ws.reader.searcher();
    let mut search_results = Vec::with_capacity(results.len());
    for (entity_id, score) in results {
        let term = tantivy::Term::from_field_text(ws.entity_id_field, &entity_id);
        let top_docs = searcher.search(
            &tantivy::query::TermQuery::new(term, IndexRecordOption::Basic),
            &tantivy::collector::TopDocs::with_limit(1),
        ).unwrap_or_default();

        if let Some((_, doc_addr)) = top_docs.first() {
            if let Ok(doc) = searcher.doc::<TantivyDocument>(*doc_addr) {
                let content = doc.get_first(ws.content_field)
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let entity_type = doc.get_first(ws.entity_type_field)
                    .and_then(|v| v.as_str())
                    .unwrap_or("memory")
                    .to_string();
                search_results.push(SearchResult {
                    entity_id,
                    score: (1.0 / (1.0 + score)) as f32,
                    content,
                    entity_type,
                });
            }
        }
    }

    Ok(Json(search_results))
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
    touch_workspace(&ws);

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

    // Remove from HNSW graph
    ws.hnsw_graph.lock().unwrap().delete(&req.entity_id);

    Ok(Json(serde_json::json!({
        "status": "ok",
        "entity_id": req.entity_id,
    })))
}

/// Save HNSW graph to disk for a workspace index.
fn save_hnsw_graph(ws: &WorkspaceIndex, index_dir: &std::path::Path, workspace_id: &str) {
    let hnsw_path = index_dir.join(workspace_id).join("hnsw_graph.json");
    if let Ok(hnsw) = ws.hnsw_graph.lock() {
        if let Ok(json) = serde_json::to_string(&*hnsw) {
            let _ = std::fs::write(&hnsw_path, json);
        }
    }
}

/// Save all HNSW graphs for workspace indices.
fn save_all_hnsw_graphs(state: &AppState) {
    for entry in state.workspaces.iter() {
        let ws_id = entry.key();
        let ws = entry.value();
        save_hnsw_graph(ws, &state.index_dir, ws_id);
    }
}

/// Touch a workspace, resetting its TTL for eviction.
fn touch_workspace(ws: &WorkspaceIndex) {
    if let Ok(mut last) = ws.last_accessed.lock() {
        *last = Instant::now();
    }
}

/// Evict a single workspace: persist HNSW, then remove from DashMap.
/// The Arc<WorkspaceIndex> drops, closing the writer and freeing its memory.
fn evict_workspace(state: &AppState, workspace_id: &str) -> bool {
    if let Some((_, ws)) = state.workspaces.remove(workspace_id) {
        save_hnsw_graph(&ws, &state.index_dir, workspace_id);
        println!("Tantivy sidecar: evicted workspace {workspace_id}");
        true
    } else {
        false
    }
}

/// Background eviction sweep: iterate all workspaces and evict those
/// idle longer than EVICTION_TTL_SECS.
async fn eviction_sweep(state: SharedState) {
    loop {
        tokio::time::sleep(tokio::time::Duration::from_secs(EVICTION_SWEEP_INTERVAL_SECS)).await;
        let now = Instant::now();
        let mut evicted: Vec<String> = Vec::new();
        // Collect eviction candidates first (can't modify DashMap while iterating)
        for entry in state.workspaces.iter() {
            if let Ok(last) = entry.value().last_accessed.lock() {
                if now.duration_since(*last).as_secs() > EVICTION_TTL_SECS {
                    evicted.push(entry.key().clone());
                }
            }
        }
        for ws_id in &evicted {
            evict_workspace(&state, ws_id);
        }
        if !evicted.is_empty() {
            println!(
                "Tantivy sidecar: eviction sweep removed {} idle workspace(s) ({} remain)",
                evicted.len(),
                state.workspaces.len()
            );
        }
    }
}

/// HTTP handler: manually evict (force-close) a workspace to reclaim memory.
async fn evict_workspace_handler(
    state: State<SharedState>,
    Path(workspace_id): Path<String>,
) -> Json<serde_json::Value> {
    let removed = evict_workspace(&state, &workspace_id);
    Json(serde_json::json!({
        "status": if removed { "ok" } else { "not_found" },
        "workspace_id": workspace_id,
    }))
}

async fn warmup(
    state: State<SharedState>,
) -> Result<Json<WarmupResponse>, String> {
    // Use native Rust warmup instead of Python subprocess
    println!("Tantivy sidecar: running native warmup via HTTP endpoint...");
    
    // Persist all HNSW graphs before warmup
    save_all_hnsw_graphs(&state.0);
    
    match native_warmup::run_native_warmup(state.0).await {
        Ok(stats) => {
            let message = format!(
                "Warmup completed: {} memories + {} nodes",
                stats.memories_indexed, stats.nodes_indexed
            );
            Ok(Json(WarmupResponse {
                status: "ok".into(),
                memories_indexed: stats.memories_indexed,
                nodes_indexed: stats.nodes_indexed,
                errors: stats.errors,
                message,
            }))
        }
        Err(e) => {
            eprintln!("Tantivy native warmup failed: {e}");
            Ok(Json(WarmupResponse {
                status: "error".into(),
                memories_indexed: 0,
                nodes_indexed: 0,
                errors: 1,
                message: format!("Warmup failed: {e}"),
            }))
        }
    }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------// ---------------------------------------------------------------------------

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

    println!("Tantivy sidecar: index directory = {:?}", index_dir);

    // Workspaces are opened lazily on first use (HTTP handlers, warmup).
    // Pre-opening all 3K+ workspaces would create ~7 threads per writer = instant thread bomb.
    let workspaces = DashMap::new();

    let stdb_url = std::env::var("SPACETIMEDB_URL")
        .unwrap_or_else(|_| "http://localhost:3001".to_string());
    let stdb_db = std::env::var("SPACETIMEDB_DB")
        .unwrap_or_else(|_| "spacetime-memory".to_string());

    let state = Arc::new(AppState {
        workspaces,
        index_dir,
        stdb_url,
        stdb_db,
    });

    // Run warmup on startup if requested — native Rust implementation
    if warmup_on_start {
        println!("Tantivy sidecar: running native warmup on startup...");
        let state_clone = state.clone();
        tokio::spawn(async move {
            // Give the server a moment to start accepting connections
            tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
            match native_warmup::run_native_warmup(state_clone).await {
                Ok(stats) => {
                    println!(
                        "Tantivy native warmup complete: {} memories, {} nodes, {} errors",
                        stats.memories_indexed, stats.nodes_indexed, stats.errors
                    );
                }
                Err(e) => {
                    eprintln!("Tantivy native warmup failed: {e}");
                }
            }
        });
    }

    // Periodic HNSW persistence
    {
        let state_clone = state.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(
                tokio::time::Duration::from_secs(HNSW_PERSIST_INTERVAL_SECS)
            );
            loop {
                interval.tick().await;
                save_all_hnsw_graphs(&state_clone);
                println!("Tantivy sidecar: HNSW graphs persisted (periodic save)");
            }
        });
    }

    // Background eviction sweep — evict idle workspaces to free memory
    {
        let state_clone = state.clone();
        tokio::spawn(async move {
            eviction_sweep(state_clone).await;
        });
    }

    let app = Router::new()
        .route("/health", get(health))
        .route("/metrics", get(metrics))
        .route("/index", post(index_doc))
        .route("/index/batch", post(index_batch))
        .route("/search", post(search))
        .route("/vector_search", post(vector_search))
        .route("/delete", post(delete_doc))
        .route("/evict/:workspace_id", post(evict_workspace_handler))
        .route("/warmup", post(warmup))
        .with_state(state);

    let addr = format!("0.0.0.0:{}", tantivy_port);
    println!("Tantivy sidecar: listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

#[cfg(test)]
mod tests {
    #[test]
    fn it_works() {
        assert_eq!(2 + 2, 4);
    }
}
