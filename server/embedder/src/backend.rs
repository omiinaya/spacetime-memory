// ---------------------------------------------------------------------------
// Embedding backend abstraction + GPU (CUDA/ROCm) backend via ort
// ---------------------------------------------------------------------------

use std::sync::{Arc, Mutex};

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
    model: Mutex<Arc<tract_onnx::prelude::SimplePlan<
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
        let model = Arc::new(model);

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
                    let di2 = Tensor::from_shape(&[1, 3], &dummy_ids).unwrap();
                    let dm2 = Tensor::from_shape(&[1, 3], &dummy_mask).unwrap();
                    let mut m = model.run(tvec!(di2.into(), dm2.into())).unwrap();
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

        let encoding = self
            .tokenizer
            .encode(text, true)
            .unwrap();

        let ids: Vec<i64> = encoding
            .get_ids()
            .iter()
            .map(|&id| id as i64)
            .collect();
        let mask: Vec<i64> = encoding
            .get_attention_mask()
            .iter()
            .map(|&m| m as i64)
            .collect();
        let seq_len = ids.len();

        let input_ids = Tensor::from_shape(&[1, seq_len], &ids).unwrap();
        let attention_mask = Tensor::from_shape(&[1, seq_len], &mask).unwrap();

        let guard = match self.model.lock() {
            Ok(g) => g,
            Err(_) => {
                return vec![0.0f32; self.dimension];
            }
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
    session: ort::Session,
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
        let _env = ort::init().expect("Failed to initialise ONNX Runtime");

        let mut builder = ort::Session::builder()
            .expect("Failed to create ONNX Runtime session builder")
            .with_model_from_file(model_path)
            .expect("Failed to load ONNX model");

        // Register execution providers in priority order:
        // GPU provider first (if use_gpu is true), then CPU fallback.
        if use_gpu {
            #[cfg(feature = "cuda")]
            {
                eprintln!("[ort] Registering CUDA execution provider");
                builder = builder
                    .with_execution_providers([ort::ep::cuda::CUDA::default()])
                    .expect("Failed to register CUDA execution provider");
            }
            #[cfg(feature = "rocm")]
            {
                eprintln!("[ort] Registering ROCm execution provider");
                builder = builder
                    .with_execution_providers([ort::ep::rocm::ROCm::default()])
                    .expect("Failed to register ROCm execution provider");
            }
        }

        let session = builder;

        // Probe dimension with a dummy input
        let dummy_ids: Vec<i64> = vec![101i64, 200, 102];
        let dummy_mask: Vec<i64> = vec![1i64, 1, 1];

        let dimension = {
            let input_tensor = ort::ndarray::Array2::from_shape_vec(
                (1, 3),
                dummy_ids.iter().map(|&x| x as i64).collect(),
            )
            .unwrap();
            let mask_tensor = ort::ndarray::Array2::from_shape_vec(
                (1, 3),
                dummy_mask.iter().map(|&x| x as i64).collect(),
            )
            .unwrap();
            let outputs = session
                .run(ort::inputs![input_tensor.view(), mask_tensor.view()].unwrap())
                .expect("Failed to probe model dimension");
            let output = outputs[0]
                .try_extract_tensor::<f32>()
                .expect("Failed to extract probe output");
            output.shape()[2]
        };

        eprintln!(
            "[ort] Model loaded: {} dimension={} provider={}",
            model_path,
            dimension,
            if use_gpu {
                #[cfg(feature = "cuda")]
                { "CUDA" }
                #[cfg(feature = "rocm")]
                { "ROCm" }
                #[cfg(not(any(feature = "cuda", feature = "rocm")))]
                { "CPU" }
            } else {
                "CPU (fallback)"
            },
        );

        OrtBackend {
            session,
            tokenizer,
            dimension,
            model_name: model_name.to_string(),
        }
    }
}

#[cfg(any(feature = "cuda", feature = "rocm"))]
impl EmbeddingBackend for OrtBackend {
    fn compute_embedding(&self, text: &str) -> Vec<f32> {
        let encoding = self
            .tokenizer
            .encode(text, true)
            .unwrap();

        let ids: Vec<i64> = encoding
            .get_ids()
            .iter()
            .map(|&id| id as i64)
            .collect();
        let mask: Vec<i64> = encoding
            .get_attention_mask()
            .iter()
            .map(|&m| m as i64)
            .collect();
        let seq_len = ids.len();

        // Build input tensors as ndarray (ort-native format)
        let input_ids = ort::ndarray::Array2::from_shape_vec(
            (1, seq_len),
            ids,
        )
        .unwrap();
        let attention_mask = ort::ndarray::Array2::from_shape_vec(
            (1, seq_len),
            mask,
        )
        .unwrap();

        let outputs = match self
            .session
            .run(ort::inputs![input_ids.view(), attention_mask.view()].unwrap())
        {
            Ok(o) => o,
            Err(e) => {
                eprintln!("[ort] Inference error: {:?}", e);
                return vec![0.0f32; self.dimension];
            }
        };

        let output = outputs[0]
            .try_extract_tensor::<f32>()
            .expect("Failed to extract embedding output");

        // output shape: (1, seq_len, hidden_dim)
        let shape = output.shape();
        let hidden_dim = shape[2];
        let seq_len_out = shape[1];

        // Build attention mask as ndarray for mean pooling
        let mask_arr = ort::ndarray::Array2::from_shape_vec(
            (1, seq_len),
            mask,
        )
        .unwrap();

        // Mean-pool manually
        let mask_sum: f32 = mask_arr.sum();
        if mask_sum == 0.0 {
            return vec![0.0f32; hidden_dim];
        }

        let mut pooled = vec![0.0f32; hidden_dim];
        for j in 0..hidden_dim {
            let mut sum = 0.0f32;
            for i in 0..seq_len_out {
                // output is stored as flat ArrayViewD
                let idx = i * hidden_dim + j;
                sum += output[idx] * mask_arr[[0, i]] as f32;
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
// Shared mean-pool + normalize (used by tract backend, also exposed for ort)
// ---------------------------------------------------------------------------

fn mean_pool_and_normalize(
    last_hidden_state: &tract_onnx::prelude::TValue,
    attention_mask: &tract_onnx::prelude::TValue,
) -> Vec<f32> {
    use tract_onnx::prelude::*;

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
