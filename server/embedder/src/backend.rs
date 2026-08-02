// ---------------------------------------------------------------------------
// Embedding backend abstraction + GPU (CUDA/ROCm) backend via ort
// ---------------------------------------------------------------------------

use std::sync::Mutex;

/// Shared embedding backend interface.
pub trait EmbeddingBackend: Send + Sync {
    fn compute_embedding(&self, text: &str) -> Vec<f32>;
    fn dimension(&self) -> usize;
    fn model_name(&self) -> &str;
}

// ---------------------------------------------------------------------------
// CPU backend (tract-onnx) — the default
// ---------------------------------------------------------------------------

pub struct TractCpuBackend {
    model: Mutex<std::sync::Arc<tract_onnx::tract_core::plan::SimplePlan<
        tract_onnx::prelude::TypedFact,
        Box<dyn tract_onnx::prelude::TypedOp>,
    >>>,
    tokenizer: tokenizers::Tokenizer,
    dimension: usize,
    num_inputs: usize,
    model_name: String,
}

impl TractCpuBackend {
    pub fn new(
        model_path: &str,
        model_name: &str,
        tokenizer: tokenizers::Tokenizer,
    ) -> Self {
        let model = tract_onnx::prelude::onnx()
            .model_for_path(model_path)
            .unwrap()
            .into_optimized()
            .unwrap()
            .into_runnable()
            .unwrap();

        // Probe dimension and input count
        let dummy_ids: Vec<i64> = vec![101i64, 200, 102];
        let dummy_mask: Vec<i64> = vec![1i64, 1, 1];

        use tract_onnx::prelude::*;
        let (dimension, num_inputs) = {
            let di = Tensor::from_shape(&[1, 3], &dummy_ids).unwrap();
            let dm = Tensor::from_shape(&[1, 3], &dummy_mask).unwrap();
            let dt = Tensor::from_shape(&[1, 3], &vec![0i64, 0, 0]).unwrap();
            match model.run(tvec!(di.into(), dm.into(), dt.into())) {
                Ok(mut m) => {
                    let val = m.remove(0);
                    let sv = val.to_plain_array_view::<f32>().unwrap();
                    (sv.shape()[2], 3)
                }
                Err(_) => {
                    let di2 =
                        Tensor::from_shape(&[1, 3], &dummy_ids).unwrap();
                    let dm2 =
                        Tensor::from_shape(&[1, 3], &dummy_mask).unwrap();
                    let mut m =
                        model.run(tvec!(di2.into(), dm2.into())).unwrap();
                    let val = m.remove(0);
                    let sv = val.to_plain_array_view::<f32>().unwrap();
                    (sv.shape()[2], 2)
                }
            }
        };

        TractCpuBackend {
            model: Mutex::new(model),
            tokenizer,
            dimension,
            num_inputs,
            model_name: model_name.to_string(),
        }
    }
}

impl EmbeddingBackend for TractCpuBackend {
    fn compute_embedding(&self, text: &str) -> Vec<f32> {
        use tract_onnx::prelude::*;

        let encoding = self.tokenizer.encode(text, true).unwrap();

        let ids: Vec<i64> =
            encoding.get_ids().iter().map(|&id| id as i64).collect();
        let mask: Vec<i64> = encoding
            .get_attention_mask()
            .iter()
            .map(|&m| m as i64)
            .collect();
        let seq_len = ids.len();

        let input_ids = Tensor::from_shape(&[1, seq_len], &ids).unwrap();
        let attention_mask =
            Tensor::from_shape(&[1, seq_len], &mask).unwrap();

        let guard = match self.model.lock() {
            Ok(g) => g,
            Err(_) => return vec![0.0f32; self.dimension],
        };
        let result = match if self.num_inputs >= 3 {
            let type_ids: Vec<i64> = vec![0i64; seq_len];
            let token_type_ids =
                Tensor::from_shape(&[1, seq_len], &type_ids).unwrap();
            guard.run(tvec!(
                input_ids.into(),
                attention_mask.into(),
                token_type_ids.into()
            ))
        } else {
            guard.run(tvec!(input_ids.into(), attention_mask.into()))
        } {
            Ok(r) => r,
            Err(e) => {
                eprintln!("[tract] Inference error: {:?}", e);
                return vec![0.0f32; self.dimension];
            }
        };
        let last_hidden_state = &result[0];
        let attn_t = Tensor::from_shape(&[1, seq_len], &mask).unwrap();
        mean_pool_and_normalize(last_hidden_state, &attn_t.into())
    }

    fn dimension(&self) -> usize {
        self.dimension
    }

    fn model_name(&self) -> &str {
        &self.model_name
    }
}

// ---------------------------------------------------------------------------
// GPU backend (ort — CUDA or ROCm)
// ---------------------------------------------------------------------------

#[cfg(any(feature = "cuda", feature = "rocm"))]
pub struct OrtBackend {
    session: Mutex<ort::session::Session>,
    tokenizer: tokenizers::Tokenizer,
    dimension: usize,
    model_name: String,
}

#[cfg(any(feature = "cuda", feature = "rocm"))]
impl OrtBackend {
    pub fn new(
        model_path: &str,
        model_name: &str,
        tokenizer: tokenizers::Tokenizer,
        use_gpu: bool,
    ) -> Self {
        // Initialise ONNX Runtime environment
        eprintln!("[ort] Calling ort::init()...");
        let _ = ort::init();
        eprintln!("[ort] ort::init() done");

        // Build session with execution providers
        eprintln!("[ort] Creating SessionBuilder...");
        let mut builder = ort::session::builder::SessionBuilder::new()
            .expect("Failed to create ONNX Runtime session builder");
        eprintln!("[ort] SessionBuilder created");

        if use_gpu {
            // Register GPU provider first (higher priority), then CPU fallback.
            eprintln!("[ort] Creating CUDA execution provider...");
            builder = builder
                .with_execution_providers([gpu_execution_provider()])
                .expect("Failed to register GPU execution provider");
            eprintln!("[ort] CUDA execution provider registered");
        }

        let session = builder
            .commit_from_file(model_path)
            .expect("Failed to load ONNX model via ort");

        let session = Mutex::new(session);

        // Probe dimension with a dummy input
        let dummy_ids: Vec<i64> = vec![101i64, 200, 102];
        let dummy_mask: Vec<i64> = vec![1i64, 1, 1];

        let dimension = {
            use ort::value::Tensor;
            let input_tensor =
                Tensor::from_array(([1_usize, 3], dummy_ids.into_boxed_slice()))
                    .expect("Failed to create probe input tensor");
            let mask_tensor =
                Tensor::from_array(([1_usize, 3], dummy_mask.into_boxed_slice()))
                    .expect("Failed to create probe mask tensor");
            let probe_shape = {
                let mut guard = session.lock().unwrap();
                let out = guard.run(ort::inputs![input_tensor, mask_tensor])
                    .expect("Failed to probe model dimension via ort");
                let (s, _) = out[0]
                    .try_extract_tensor::<f32>()
                    .expect("Failed to extract probe output");
                // Clone to owned Vec — SessionOutput borrows from MutexGuard
                s.iter().copied().collect::<Vec<i64>>()
            };
            probe_shape[2] as usize
        };

        let provider_name = if use_gpu {
            gpu_provider_name()
        } else {
            "CPU"
        };
        eprintln!(
            "[ort] Model loaded: {} dimension={} provider={}",
            model_path, dimension, provider_name,
        );

        OrtBackend {
            session,
            tokenizer,
            dimension,
            model_name: model_name.to_string(),
        }
    }
}

#[cfg(feature = "cuda")]
fn gpu_execution_provider() -> ort::ep::ExecutionProviderDispatch {
    eprintln!("[ort] Creating CUDA execution provider");
    ort::ep::CUDA::default().build()
}

#[cfg(feature = "rocm")]
fn gpu_execution_provider() -> ort::ep::ExecutionProviderDispatch {
    eprintln!("[ort] Creating ROCm execution provider");
    Box::new(ort::ep::rocm::ROCm::default())
}

#[cfg(feature = "cuda")]
fn gpu_provider_name() -> &'static str {
    "CUDA"
}

#[cfg(feature = "rocm")]
fn gpu_provider_name() -> &'static str {
    "ROCm"
}

#[cfg(any(feature = "cuda", feature = "rocm"))]
impl EmbeddingBackend for OrtBackend {
    fn compute_embedding(&self, text: &str) -> Vec<f32> {
        let encoding = self.tokenizer.encode(text, true).unwrap();

        let ids: Vec<i64> =
            encoding.get_ids().iter().map(|&id| id as i64).collect();
        let mask: Vec<i64> = encoding
            .get_attention_mask()
            .iter()
            .map(|&m| m as i64)
            .collect();
        let seq_len = ids.len();

        // Build input tensors from raw Vecs (no ndarray dependency)
        use ort::value::Tensor;
        let input_ids =
            Tensor::from_array(([1_usize, seq_len], ids.into_boxed_slice()))
                .expect("Failed to create input_ids tensor");
        let attention_mask =
            Tensor::from_array(([1_usize, seq_len], mask.clone().into_boxed_slice()))
                .expect("Failed to create attention_mask tensor");

        let (shape, data) = {
            let mut guard = self.session.lock().expect("[ort] Mutex poisoned");
            let out = guard.run(
                ort::inputs![input_ids, attention_mask],
            ).expect("ort run failed");
            let (s, d) = out[0]
                .try_extract_tensor::<f32>()
                .expect("Failed to extract embedding output");
            // Clone to owned Vecs — SessionOutput borrows from MutexGuard
            let shape_owned: Vec<i64> = s.iter().copied().collect();
            let data_owned: Vec<f32> = d.to_vec();
            (shape_owned, data_owned)
        };

        // shape dimensions: [1, seq_len_out, hidden_dim]
        let seq_len_out = shape[1] as usize;
        let hidden_dim = shape[2] as usize;

        // Mean pool using raw mask array
        let mask_sum: f32 = mask.iter().map(|&m| m as f32).sum();
        if mask_sum == 0.0 {
            return vec![0.0f32; hidden_dim];
        }

        let mut pooled = vec![0.0f32; hidden_dim];
        for j in 0..hidden_dim {
            let mut sum = 0.0f32;
            for i in 0..seq_len_out {
                let idx = i * hidden_dim + j;
                sum += data[idx] * mask[i] as f32;
            }
            pooled[j] = sum / mask_sum;
        }

        // L2-normalize
        let norm: f32 = pooled.iter().map(|x| x * x).sum::<f32>().sqrt();
        if norm > 0.0 {
            for v in &mut pooled {
                *v /= norm;
            }
        }

        pooled
    }

    fn dimension(&self) -> usize {
        self.dimension
    }

    fn model_name(&self) -> &str {
        &self.model_name
    }
}

// ---------------------------------------------------------------------------
// Shared mean-pool + normalize (used by tract backend)
// ---------------------------------------------------------------------------

fn mean_pool_and_normalize(
    last_hidden_state: &tract_onnx::prelude::TValue,
    attention_mask: &tract_onnx::prelude::TValue,
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

#[cfg(test)]
mod tests {
    #[test]
    fn it_works() {
        assert_eq!(2 + 2, 4);
    }
}
