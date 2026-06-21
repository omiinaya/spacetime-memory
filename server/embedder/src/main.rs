use axum::{routing::{get, post}, Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};
use tract_onnx::prelude::*;
use tract_onnx::tract_core::plan::SimplePlan;

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
}

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

struct AppState {
    model: Mutex<Arc<SimplePlan<TypedFact, Box<dyn TypedOp>>>>,
    tokenizer: tokenizers::Tokenizer,
    embedding_count: std::sync::atomic::AtomicU64,
    dimension: usize,
    num_inputs: usize,  // 2 or 3 — some ONNX exports omit token_type_ids
    model_name: String,
}

type SharedState = Arc<AppState>;

// ---------------------------------------------------------------------------
// Inference
// ---------------------------------------------------------------------------

fn mean_pool_and_normalize(
    last_hidden_state: &TValue,
    attention_mask: &TValue,
) -> Vec<f32> {
    let state = last_hidden_state.to_plain_array_view::<f32>().unwrap();
    let mask = attention_mask.to_plain_array_view::<i64>().unwrap();

    let seq_len = state.shape()[1];
    let hidden_dim = state.shape()[2];

    let mask_sum: f32 = (0..seq_len).map(|i| mask[[0, i]] as f32).sum();

    if mask_sum == 0.0 {
        return vec![0.0f32; hidden_dim];
    }

    let mut pooled = vec![0.0f32; hidden_dim];
    for j in 0..hidden_dim {
        let mut sum = 0.0f32;
        for i in 0..seq_len {
            sum += state[[0, i, j]] * mask[[0, i]] as f32;
        }
        pooled[j] = sum / mask_sum;
    }

    let norm: f32 = pooled.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm > 0.0 {
        for v in &mut pooled {
            *v /= norm;
        }
    }

    pooled
}

fn compute_embedding(
    model: &Mutex<Arc<SimplePlan<TypedFact, Box<dyn TypedOp>>>>,
    tokenizer: &tokenizers::Tokenizer,
    text: &str,
    num_inputs: usize,
) -> Vec<f32> {
    let encoding = tokenizer.encode(text, true).unwrap();

    let ids: Vec<i64> = encoding.get_ids().iter().map(|&id| id as i64).collect();
    let mask: Vec<i64> = encoding.get_attention_mask().iter().map(|&m| m as i64).collect();
    let seq_len = ids.len();

    let input_ids = Tensor::from_shape(&[1, seq_len], &ids).unwrap();
    let attention_mask = Tensor::from_shape(&[1, seq_len], &mask).unwrap();

    let guard = match model.lock() {
        Ok(g) => g,
        Err(_) => {
            // Mutex poisoned — previous request panicked. Return zero vector.
            return vec![0.0f32; 1024];
        }
    };
    let result = match if num_inputs >= 3 {
        let type_ids: Vec<i64> = vec![0i64; seq_len];
        let token_type_ids = Tensor::from_shape(&[1, seq_len], &type_ids).unwrap();
        guard.run(tvec!(input_ids.into(), attention_mask.into(), token_type_ids.into()))
    } else {
        guard.run(tvec!(input_ids.into(), attention_mask.into()))
    } {
        Ok(r) => r,
        Err(e) => {
            eprintln!("Embedder inference error: {:?}", e);
            return vec![0.0f32; 1024];
        }
    };
    let last_hidden_state = &result[0];
    let attn_t = Tensor::from_shape(&[1, seq_len], &mask).unwrap();

    mean_pool_and_normalize(last_hidden_state, &attn_t.into())
}

/// Wrapper that runs CPU-bound embedding on a blocking thread.
async fn compute_embedding_async(
    state: &SharedState,
    text: &str,
) -> Vec<f32> {
    let state = state.clone();
    let text = text.to_string();
    let dim = state.dimension;
    tokio::task::spawn_blocking(move || {
        compute_embedding(&state.model, &state.tokenizer, &text, state.num_inputs)
    })
    .await
    .unwrap_or_else(|_| vec![0.0f32; dim])
}

// ---------------------------------------------------------------------------
// HTTP handlers
// ---------------------------------------------------------------------------

async fn health(state: axum::extract::State<SharedState>) -> Json<HealthResponse> {
    let count = state.embedding_count.load(std::sync::atomic::Ordering::Relaxed);
    Json(HealthResponse {
        status: "ok".into(),
        model: state.model_name.clone(),
        dimension: state.dimension,
        embedding_count: count,
        dimensions_supported: true,
    })
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

    let requested_dim = req.dimensions.unwrap_or(state.dimension);
    let clamped_dim = requested_dim.min(state.dimension);
    // Truncate each embedding to the requested dimension
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

    let model_name = req.model.unwrap_or_else(|| state.model_name.clone());
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

    let requested_dim = req.dimensions.unwrap_or(state.dimension);
    let clamped_dim = requested_dim.min(state.dimension);
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
// HTTP handlers
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    println!("Embedder: loading model...");

    let model_name = std::env::var("MODEL_NAME")
        .unwrap_or_else(|_| "BAAI/bge-large-en-v1.5".to_string());

    let tokenizer = tokenizers::Tokenizer::from_pretrained(
        &model_name,
        None,
    )
    .expect("Failed to load tokenizer. Check network / HF hub access.");

    let model_path = std::env::var("MODEL_PATH")
        .unwrap_or_else(|_| format!("model/{}.onnx", model_name.split('/').last().unwrap_or("model")));

    let model = onnx()
        .model_for_path(&model_path)
        .unwrap()
        .into_optimized()
        .unwrap()
        .into_runnable()
        .unwrap();

    // Probe dimension and input count
    let dummy_ids: Vec<i64> = vec![101i64, 200, 102];
    let dummy_mask: Vec<i64> = vec![1i64, 1, 1];

    // Try 3 inputs first (BERT/MiniLM), fall back to 2 (MPNet)
    let (dimension, num_inputs) = {
        let di = Tensor::from_shape(&[1, 3], &dummy_ids).unwrap();
        let dm = Tensor::from_shape(&[1, 3], &dummy_mask).unwrap();
        let dt = Tensor::from_shape(&[1, 3], &vec![0i64, 0, 0]).unwrap();
        match model.run(tvec!(di.into(), dm.into(), dt.into())) {
            Ok(mut m) => {
                let val = m.remove(0); let sv = val.to_plain_array_view::<f32>().unwrap();
                (sv.shape()[2], 3)
            }
            Err(_) => {
                let di2 = Tensor::from_shape(&[1, 3], &dummy_ids).unwrap();
                let dm2 = Tensor::from_shape(&[1, 3], &dummy_mask).unwrap();
                let mut m = model.run(tvec!(di2.into(), dm2.into())).unwrap();
                let val = m.remove(0); let sv = val.to_plain_array_view::<f32>().unwrap();
                (sv.shape()[2], 2)
            }
        }
    };
    println!("Embedder: ready. dimension={} num_inputs={} model={}", dimension, num_inputs, model_path);

    let state = Arc::new(AppState {
        model: Mutex::new(model),
        tokenizer,
        embedding_count: std::sync::atomic::AtomicU64::new(0),
        dimension,
        num_inputs,
        model_name: model_name.clone(),
    });

    let app = Router::new()
        .route("/health", axum::routing::get(health))
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
