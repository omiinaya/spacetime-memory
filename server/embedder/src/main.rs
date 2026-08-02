use axum::{routing::post, Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Arc;

mod backend;

use backend::EmbeddingBackend;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct EmbedRequest {
    text: Option<String>,
    texts: Option<Vec<String>>,
    dimensions: Option<usize>,
}

#[derive(Serialize)]
struct EmbedResponse {
    embedding: Vec<f32>,
    embeddings: Option<Vec<Vec<f32>>>,
    dimension: usize,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum OpenAIEmbedInput {
    Single(String),
    Batch(Vec<String>),
}

#[derive(Deserialize)]
struct OpenAIEmbedRequest {
    input: OpenAIEmbedInput,
    model: Option<String>,
    dimensions: Option<usize>,
}

#[derive(Serialize)]
struct OpenAIEmbedResponse {
    object: String,
    data: Vec<OpenAIEmbedData>,
    model: String,
    usage: OpenAIUsage,
}

#[derive(Serialize)]
struct OpenAIEmbedData {
    object: String,
    index: usize,
    embedding: Vec<f32>,
}

#[derive(Serialize)]
struct OpenAIUsage {
    prompt_tokens: usize,
    total_tokens: usize,
}

#[derive(Serialize)]
struct HealthResponse {
    status: String,
    model: String,
    dimension: usize,
    embedding_count: u64,
    dimensions_supported: bool,
    rss_kb: u64,
    uptime_seconds: u64,
}

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

struct AppState {
    backend: Arc<dyn EmbeddingBackend>,
    embedding_count: std::sync::atomic::AtomicU64,
    start_time: tokio::time::Instant,
}

type SharedState = Arc<AppState>;

// ---------------------------------------------------------------------------
// Wrapper that runs CPU-bound embedding on a blocking thread.
// The backend itself is Send+Sync so we call it directly inside spawn_blocking
// only if the implementation is CPU-heavy (tract). ort's GPU backend is
// already async-safe.
// ---------------------------------------------------------------------------

async fn compute_embedding_async(
    state: &SharedState,
    text: &str,
) -> Vec<f32> {
    let backend = state.backend.clone();
    let text = text.to_string();
    let dim = backend.dimension();
    tokio::task::spawn_blocking(move || backend.compute_embedding(&text))
        .await
        .unwrap_or_else(|_| vec![0.0f32; dim])
}

// ---------------------------------------------------------------------------
// HTTP handlers
// ---------------------------------------------------------------------------

fn read_rss_kb() -> u64 {
    let status = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    for line in status.lines() {
        if line.starts_with("VmRSS:") {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 2 {
                if let Ok(kb) = parts[1].parse::<u64>() {
                    return kb;
                }
            }
        }
    }
    0
}

async fn health(state: axum::extract::State<SharedState>) -> Json<HealthResponse> {
    let count = state.embedding_count.load(std::sync::atomic::Ordering::Relaxed);
    let uptime = state.start_time.elapsed().as_secs();
    Json(HealthResponse {
        status: "ok".into(),
        model: state.backend.model_name().into(),
        dimension: state.backend.dimension(),
        embedding_count: count,
        dimensions_supported: true,
        rss_kb: read_rss_kb(),
        uptime_seconds: uptime,
    })
}

async fn metrics(state: axum::extract::State<SharedState>) -> String {
    let count = state.embedding_count.load(std::sync::atomic::Ordering::Relaxed);
    let uptime = state.start_time.elapsed().as_secs();
    let rss_kb = read_rss_kb();
    let dim = state.backend.dimension();
    let model = state.backend.model_name();

    let mut out = String::new();
    out.push_str("# HELP embedder_rss_bytes Resident set size of the embedder process\n");
    out.push_str("# TYPE embedder_rss_bytes gauge\n");
    out.push_str(&format!("embedder_rss_bytes {}\n", rss_kb * 1024));

    out.push_str("# HELP embedder_embedding_count Total embeddings computed\n");
    out.push_str("# TYPE embedder_embedding_count counter\n");
    out.push_str(&format!("embedder_embedding_count {}\n", count));

    out.push_str("# HELP embedder_uptime_seconds Uptime of the embedder process\n");
    out.push_str("# TYPE embedder_uptime_seconds gauge\n");
    out.push_str(&format!("embedder_uptime_seconds {}\n", uptime));

    out.push_str("# HELP embedder_dimension Embedding dimension\n");
    out.push_str("# TYPE embedder_dimension gauge\n");
    out.push_str(&format!("embedder_dimension {}\n", dim));

    out.push_str("# HELP embedder_model_info Static model info as label\n");
    out.push_str("# TYPE embedder_model_info gauge\n");
    let safe_model = model.replace('"', "_");
    out.push_str(&format!("embedder_model_info{{model=\"{}\"}} 1\n", safe_model));

    out
}

async fn embed(
    state: axum::extract::State<SharedState>,
    Json(req): Json<EmbedRequest>,
) -> Json<EmbedResponse> {
    let texts = if let Some(ts) = req.texts {
        ts
    } else if let Some(t) = req.text {
        vec![t]
    } else {
        return Json(EmbedResponse {
            embedding: vec![],
            embeddings: None,
            dimension: 0,
        });
    };
    let mut all_embeddings: Vec<Vec<f32>> = Vec::with_capacity(texts.len());

    for t in &texts {
        all_embeddings.push(compute_embedding_async(&state, t).await);
    }

    state.embedding_count.fetch_add(
        all_embeddings.len() as u64,
        std::sync::atomic::Ordering::Relaxed,
    );

    let requested_dim = req.dimensions.unwrap_or(state.backend.dimension());
    let clamped_dim = requested_dim.min(state.backend.dimension());
    for vec in &mut all_embeddings {
        vec.truncate(clamped_dim);
    }

    let dimension = clamped_dim;
    if all_embeddings.len() == 1 {
        Json(EmbedResponse {
            embedding: all_embeddings.into_iter().next().unwrap(),
            embeddings: None,
            dimension,
        })
    } else {
        let first = all_embeddings.first().cloned().unwrap_or_default();
        Json(EmbedResponse {
            embedding: first,
            embeddings: Some(all_embeddings),
            dimension,
        })
    }
}

/// Extract text strings from an OpenAI-format request body.
fn openai_texts(input: &OpenAIEmbedInput) -> Vec<String> {
    match input {
        OpenAIEmbedInput::Single(s) => vec![s.clone()],
        OpenAIEmbedInput::Batch(ts) => ts.clone(),
    }
}

/// OpenAI-compatible /v1/embeddings handler
async fn openai_embed(
    state: axum::extract::State<SharedState>,
    Json(req): Json<OpenAIEmbedRequest>,
) -> Json<Value> {
    let texts = openai_texts(&req.input);
    let text_count = texts.len();
    let total_chars: usize = texts.iter().map(|t| t.len()).sum();
    eprintln!("[embedder] /v1/embeddings: {} texts, {} chars total", text_count, total_chars);

    if texts.is_empty() || texts.iter().any(|t| t.is_empty()) {
        eprintln!("[embedder] /v1/embeddings: invalid input (empty text)");
        return Json(json!({
            "error": {
                "message": "input must be a non-empty string or array of non-empty strings",
                "type": "invalid_request_error"
            }
        }));
    }

    let model_name = req.model.unwrap_or_else(|| state.backend.model_name().into());
    let mut all_embeddings: Vec<Vec<f32>> = Vec::with_capacity(texts.len());
    for t in &texts {
        // Truncate very long inputs (~512 tokens max for CPU stability)
        let input = if t.len() > 1800 { &t[..1800] } else { t.as_str() };
        all_embeddings.push(compute_embedding_async(&state, input).await);
    }

    state.embedding_count.fetch_add(
        all_embeddings.len() as u64,
        std::sync::atomic::Ordering::Relaxed,
    );

    let requested_dim = req.dimensions.unwrap_or(state.backend.dimension());
    let clamped_dim = requested_dim.min(state.backend.dimension());
    for vec in &mut all_embeddings {
        vec.truncate(clamped_dim);
    }

    let data: Vec<OpenAIEmbedData> = all_embeddings
        .into_iter()
        .enumerate()
        .map(|(i, vec)| OpenAIEmbedData {
            object: "embedding".into(),
            index: i,
            embedding: vec,
        })
        .collect();

    eprintln!("[embedder] /v1/embeddings: returning {} embeddings at {} dims", data.len(), clamped_dim);
    Json(json!(OpenAIEmbedResponse {
        object: "list".into(),
        data,
        model: model_name,
        usage: OpenAIUsage {
            prompt_tokens: texts.iter().map(|t| t.len() / 4).sum(),
            total_tokens: texts.iter().map(|t| t.len() / 4).sum(),
        },
    }))
}

// ---------------------------------------------------------------------------
// Backend initialisation — CPU (default) or GPU (CUDA/ROCm)
// ---------------------------------------------------------------------------

#[allow(unused_variables)]
fn create_backend(model_path: &str, model_name: &str, tokenizer: tokenizers::Tokenizer) -> Box<dyn EmbeddingBackend> {
    // Check if GPU is requested via env var EMBEDDER_BACKEND=cuda or EMBEDDER_BACKEND=rocm
    let backend_env = std::env::var("EMBEDDER_BACKEND").unwrap_or_default();

    #[cfg(feature = "cuda")]
    if backend_env == "cuda" || backend_env == "gpu" {
        eprintln!("[embedder] Initialising GPU backend (CUDA) via ort");
        return Box::new(backend::OrtBackend::new(model_path, model_name, tokenizer, true));
    }

    #[cfg(feature = "rocm")]
    if backend_env == "rocm" || backend_env == "gpu" {
        eprintln!("[embedder] Initialising GPU backend (ROCm) via ort");
        return Box::new(backend::OrtBackend::new(model_path, model_name, tokenizer, true));
    }

    #[cfg(any(feature = "cuda", feature = "rocm"))]
    if backend_env == "cpu" {
        eprintln!("[embedder] GPU features compiled but CPU backend requested via EMBEDDER_BACKEND=cpu");
        // Fall through to CPU
    }

    // Default: CPU via tract-onnx
    eprintln!("[embedder] Initialising CPU backend via tract-onnx");
    Box::new(backend::TractCpuBackend::new(model_path, model_name, tokenizer))
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    println!("Embedder: loading model...");

    let model_name = std::env::var("MODEL_NAME")
        .unwrap_or_else(|_| "BAAI/bge-m3".to_string());

    let tokenizer = tokenizers::Tokenizer::from_pretrained(
        &model_name,
        None,
    )
    .expect("Failed to load tokenizer. Check network / HF hub access.");

    let model_path = std::env::var("MODEL_PATH")
        .unwrap_or_else(|_| format!("model/{}.onnx", model_name.split('/').last().unwrap_or("model")));

    let backend = create_backend(&model_path, &model_name, tokenizer);

    println!(
        "Embedder: ready. dimension={} model={} backend={}",
        backend.dimension(),
        model_path,
        {
            #[cfg(feature = "cuda")]
            { "CUDA (ort)" }
            #[cfg(feature = "rocm")]
            { "ROCm (ort)" }
            #[cfg(not(any(feature = "cuda", feature = "rocm")))]
            { "CPU (tract-onnx)" }
        },
    );

    let state = Arc::new(AppState {
        backend: Arc::from(backend),
        embedding_count: std::sync::atomic::AtomicU64::new(0),
        start_time: tokio::time::Instant::now(),
    });

    let app = Router::new()
        .route("/health", axum::routing::get(health))
        .route("/metrics", axum::routing::get(metrics))
        .route("/embed", post(embed))
        .route("/v1/embeddings", post(openai_embed))
        .with_state(state);

    let port: u16 = std::env::var("PORT")
        .unwrap_or_else(|_| "9090".to_string())
        .parse()
        .expect("PORT must be a valid port number");

    let addr = format!("0.0.0.0:{}", port);
    println!("Embedder: listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // openai_texts
    // -----------------------------------------------------------------------

    #[test]
    fn test_openai_texts_single() {
        let input = OpenAIEmbedInput::Single("hello world".into());
        let texts = openai_texts(&input);
        assert_eq!(texts, vec!["hello world"]);
    }

    #[test]
    fn test_openai_texts_batch() {
        let input = OpenAIEmbedInput::Batch(vec!["a".into(), "b".into(), "c".into()]);
        let texts = openai_texts(&input);
        assert_eq!(texts, vec!["a", "b", "c"]);
    }

    #[test]
    fn test_openai_texts_single_empty() {
        let input = OpenAIEmbedInput::Single(String::new());
        let texts = openai_texts(&input);
        assert_eq!(texts, vec![""]);
    }

    // -----------------------------------------------------------------------
    // EmbedRequest deserialize
    // -----------------------------------------------------------------------

    #[test]
    fn test_embed_request_text_field() {
        let json = r#"{"text": "foo"}"#;
        let req: EmbedRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.text, Some("foo".into()));
        assert_eq!(req.texts, None);
        assert_eq!(req.dimensions, None);
    }

    #[test]
    fn test_embed_request_texts_field() {
        let json = r#"{"texts": ["x", "y"]}"#;
        let req: EmbedRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.text, None);
        assert_eq!(req.texts, Some(vec!["x".into(), "y".into()]));
        assert_eq!(req.dimensions, None);
    }

    #[test]
    fn test_embed_request_with_dimensions() {
        let json = r#"{"texts": ["a"], "dimensions": 256}"#;
        let req: EmbedRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.dimensions, Some(256));
    }

    #[test]
    fn test_embed_request_empty_object() {
        let json = r#"{}"#;
        let req: EmbedRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.text, None);
        assert_eq!(req.texts, None);
        assert_eq!(req.dimensions, None);
    }

    // -----------------------------------------------------------------------
    // OpenAIEmbedRequest deserialize (untagged enum)
    // -----------------------------------------------------------------------

    #[test]
    fn test_openai_embed_request_single() {
        let json = r#"{"input": "single text"}"#;
        let req: OpenAIEmbedRequest = serde_json::from_str(json).unwrap();
        match req.input {
            OpenAIEmbedInput::Single(s) => assert_eq!(s, "single text"),
            _ => panic!("expected Single variant"),
        }
        assert_eq!(req.model, None);
        assert_eq!(req.dimensions, None);
    }

    #[test]
    fn test_openai_embed_request_batch() {
        let json = r#"{"input": ["first", "second", "third"]}"#;
        let req: OpenAIEmbedRequest = serde_json::from_str(json).unwrap();
        match req.input {
            OpenAIEmbedInput::Batch(v) => assert_eq!(v, vec!["first", "second", "third"]),
            _ => panic!("expected Batch variant"),
        }
    }

    #[test]
    fn test_openai_embed_request_with_dimensions() {
        let json = r#"{"input": "text", "model": "test-model", "dimensions": 512}"#;
        let req: OpenAIEmbedRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.dimensions, Some(512));
        assert_eq!(req.model, Some("test-model".into()));
    }

    #[test]
    fn test_openai_embed_request_single_with_model() {
        let json = r#"{"input": "hello", "model": "bge-m3"}"#;
        let req: OpenAIEmbedRequest = serde_json::from_str(json).unwrap();
        match req.input {
            OpenAIEmbedInput::Single(s) => assert_eq!(s, "hello"),
            _ => panic!("expected Single variant"),
        }
        assert_eq!(req.model, Some("bge-m3".into()));
    }

    // -----------------------------------------------------------------------
    // HealthResponse serialize
    // -----------------------------------------------------------------------

    #[test]
    fn test_health_response_serialize() {
        let resp = HealthResponse {
            status: "ok".into(),
            model: "bge-m3".into(),
            dimension: 1024,
            embedding_count: 42,
            dimensions_supported: true,
            rss_kb: 1024,
            uptime_seconds: 3600,
        };
        let json = serde_json::to_value(&resp).unwrap();
        assert_eq!(json["status"], "ok");
        assert_eq!(json["model"], "bge-m3");
        assert_eq!(json["dimension"], 1024);
        assert_eq!(json["embedding_count"], 42);
        assert_eq!(json["dimensions_supported"], true);
    }

    #[test]
    fn test_health_response_serialize_zero_count() {
        let resp = HealthResponse {
            status: "ok".into(),
            model: "minilm".into(),
            dimension: 384,
            embedding_count: 0,
            dimensions_supported: false,
            rss_kb: 2048,
            uptime_seconds: 7200,
        };
        let json = serde_json::to_value(&resp).unwrap();
        assert_eq!(json["status"], "ok");
        assert_eq!(json["dimensions_supported"], false);
        assert_eq!(json["embedding_count"], 0);
    }

    // -----------------------------------------------------------------------
    // Edge: empty texts case for openai_texts
    // -----------------------------------------------------------------------

    #[test]
    fn test_openai_texts_empty_batch() {
        let input = OpenAIEmbedInput::Batch(vec![]);
        let texts = openai_texts(&input);
        assert!(texts.is_empty());
    }
}
