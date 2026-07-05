use axum::{extract::State, routing::post, Json, Router};
use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Arc;
use tantivy::collector::TopDocs;
use tantivy::query::{BooleanQuery, Occur, Query, TermQuery};
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

// ---------------------------------------------------------------------------
// Application state — one index per workspace
// ---------------------------------------------------------------------------

struct WorkspaceIndex {
    reader: IndexReader,
    writer: Arc<std::sync::Mutex<IndexWriter>>,
    content_field: Field,
    workspace_field: Field,
    entity_id_field: Field,
    entity_type_field: Field,
}

struct AppState {
    workspaces: DashMap<String, Arc<WorkspaceIndex>>,
    index_dir: PathBuf,
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
        TEXT
            | STORED,
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
        .map_err(|e| format!("Failed to create index dir: {}", e))?;

    let index = if ws_dir.join("meta.json").exists() {
        Index::open_in_dir(&ws_dir)
            .map_err(|e| format!("Failed to open index: {}", e))?
    } else {
        Index::create_in_dir(&ws_dir, schema.clone())
            .map_err(|e| format!("Failed to create index: {}", e))?
    };

    let writer = index
        .writer(40_000_000)
        .map_err(|e| format!("Failed to create writer: {}", e))?;
    let reader = index
        .reader_builder()
        .reload_policy(ReloadPolicy::OnCommitWithDelay)
        .try_into()
        .map_err(|e| format!("Failed to create reader: {}", e))?;

    Ok(Arc::new(WorkspaceIndex {
        reader,
        writer: Arc::new(std::sync::Mutex::new(writer)),
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
        .map_err(|e| format!("Failed to add document: {}", e))?;

    ws.writer
        .lock()
        .unwrap()
        .commit()
        .map_err(|e| format!("Failed to commit: {}", e))?;

    Ok(Json(serde_json::json!({
        "status": "ok",
        "entity_id": req.entity_id,
        "workspace_id": req.workspace_id,
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

    // Build query: parse user text + filter on workspace_id.
    // Construct a BooleanQuery with OR across all query terms —
    // BM25 scoring naturally weights multi-term matches higher,
    // so there's no precision loss from OR, but we gain recall when
    // stemming or tokenization causes a term mismatch.
    let mut subqueries: Vec<(Occur, Box<dyn Query>)> = Vec::new();

    // Tokenize the user query the same way Tantivy indexes: split on
    // non-alphanumeric, lowercase, skip stopwords and short tokens.
    for token in req.query.split(|c: char| !c.is_alphanumeric()) {
        if token.len() < 2 {
            continue;
        }
        let term = Term::from_field_text(ws.content_field, &token.to_lowercase());
        subqueries.push((Occur::Should, Box::new(TermQuery::new(term, IndexRecordOption::WithFreqs))));
    }

    if subqueries.is_empty() {
        return Ok(Json(vec![]));
    }

    let text_query: Box<dyn Query> = Box::new(BooleanQuery::new(subqueries));

    let workspace_term =
        Term::from_field_text(ws.workspace_field, &req.workspace_id);
    let workspace_query: Box<dyn Query> =
        Box::new(TermQuery::new(workspace_term, IndexRecordOption::Basic));

    // Combine: workspace filter AND text query
    let combined: Box<dyn Query> = Box::new(BooleanQuery::new(vec![
        (Occur::Must, workspace_query),
        (Occur::Must, Box::new(text_query)),
    ]));

    let top_docs = searcher
        .search(&combined, &TopDocs::with_limit(limit))
        .map_err(|e| format!("Search failed: {}", e))?;

    let mut results = Vec::with_capacity(top_docs.len());
    for (score, doc_addr) in top_docs {
        let doc: TantivyDocument = searcher
            .doc(doc_addr)
            .map_err(|e| format!("Failed to retrieve doc: {}", e))?;

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
        .map_err(|e| format!("Failed to commit: {}", e))?;

    Ok(Json(serde_json::json!({
        "status": "ok",
        "entity_id": req.entity_id,
    })))
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    let index_dir = std::env::var("TANTIVY_INDEX_DIR")
        .unwrap_or_else(|_| "data/tantivy".to_string());
    let index_dir = PathBuf::from(index_dir);
    std::fs::create_dir_all(&index_dir).expect("Failed to create index directory");

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
    });

    let app = Router::new()
        .route("/health", axum::routing::get(health))
        .route("/index", post(index_doc))
        .route("/search", post(search))
        .route("/delete", post(delete_doc))
        .with_state(state);

    let port: u16 = std::env::var("TANTIVY_PORT")
        .unwrap_or_else(|_| "9091".to_string())
        .parse()
        .expect("TANTIVY_PORT must be a valid port number");

    let addr = format!("0.0.0.0:{}", port);
    println!("Tantivy sidecar: listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
