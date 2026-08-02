#!/usr/bin/env python3
"""
GPU-accelerated embedding server (Python) — drop-in replacement for the Rust CPU embedder.
Uses onnxruntime-gpu with CUDA 11.8 for ~20-50x speedup over tract-onnx CPU backend.
"""
import json
import os
import sys
import time
import signal
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import numpy as np
import onnxruntime as ort

app = FastAPI()

# ---------------------------------------------------------------------------
# Globals (set during startup)
# ---------------------------------------------------------------------------
session = None
tokenizer = None
model_name = "BAAI/bge-m3"
dimension = 1024
start_time = time.time()
embedding_count = 0

# ---------------------------------------------------------------------------
# Tokenizer (lightweight HuggingFace tokenizer replacement)
# ---------------------------------------------------------------------------
class SimpleTokenizer:
    """Minimal tokenizer using HuggingFace tokenizers."""
    
    def __init__(self, model_dir):
        self._mode = "simple"
        self._hf = None
        
        # Try to find the tokenizer file
        tok_candidates = [
            os.path.join(model_dir, "bge-m3-tokenizer.json"),
            os.path.join(model_dir, "tokenizer.json"),
        ]
        
        # Also check parent directory if model_dir doesn't exist
        if not os.path.isdir(model_dir):
            parent = os.path.dirname(model_dir)
            tok_candidates = [
                os.path.join(parent, "bge-m3-tokenizer.json"),
                os.path.join(parent, "tokenizer.json"),
            ]
        
        tok_file = None
        for p in tok_candidates:
            if os.path.exists(p):
                tok_file = p
                break
        
        if tok_file:
            try:
                from tokenizers import Tokenizer as HFTokenizer
                self._hf = HFTokenizer.from_file(tok_file)
                self._mode = "hf"
                print(f"[gpu-embedder] Loaded tokenizer from {tok_file}", flush=True)
            except Exception as e:
                print(f"[gpu-embedder] Failed to load tokenizer file ({e}), using simple fallback", flush=True)
        else:
            print(f"[gpu-embedder] No tokenizer file found in {model_dir}, trying HF hub...", flush=True)
            try:
                from tokenizers import Tokenizer as HFTokenizer
                model_name = os.environ.get("MODEL_NAME", "BAAI/bge-m3")
                self._hf = HFTokenizer.from_pretrained(model_name)
                self._mode = "hf"
                print(f"[gpu-embedder] Loaded tokenizer from HF hub: {model_name}", flush=True)
            except Exception as e:
                print(f"[gpu-embedder] HF hub failed ({e}), using simple fallback", flush=True)
    
    def encode(self, text: str, max_length: int = 512):
        if self._mode == "hf":
            encoding = self._hf.encode(text)
            ids = encoding.ids[:max_length]
            attention_mask = encoding.attention_mask[:max_length]
            token_type_ids = getattr(encoding, 'type_ids', [0] * len(ids))[:max_length]
        else:
            # Simple whitespace tokenizer fallback
            tokens = text.split()[:max_length - 2]
            ids = [101] + [hash(t) % 30000 + 1000 for t in tokens] + [102]
            ids = ids[:max_length]
            attention_mask = [1] * len(ids)
            token_type_ids = [0] * len(ids)
        
        # Pad to max_length
        padding_len = max_length - len(ids)
        if padding_len > 0:
            ids = ids + [0] * padding_len
            attention_mask = attention_mask + [0] * padding_len
            token_type_ids = token_type_ids + [0] * padding_len
        
        return {
            "input_ids": np.array([ids], dtype=np.int64),
            "attention_mask": np.array([attention_mask], dtype=np.int64),
            "token_type_ids": np.array([token_type_ids], dtype=np.int64),
        }


def mean_pooling(last_hidden_state, attention_mask):
    """Mean pooling + L2 normalization (same as Rust embedder)."""
    input_mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(last_hidden_state.dtype)
    sum_embeddings = np.sum(last_hidden_state * input_mask_expanded, axis=1)
    sum_mask = np.clip(np.sum(input_mask_expanded, axis=1), a_min=1e-9, a_max=None)
    pooled = sum_embeddings / sum_mask
    
    # L2 normalize
    norm = np.linalg.norm(pooled, axis=1, keepdims=True)
    norm = np.clip(norm, a_min=1e-12, a_max=None)
    pooled = pooled / norm
    
    return pooled


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    global session, tokenizer, dimension, model_name
    
    model_name = os.environ.get("MODEL_NAME", "BAAI/bge-m3")
    model_dir = os.environ.get("MODEL_PATH", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "embedder", "model"
    ))
    
    # Find the ONNX model file
    model_file = os.path.join(model_dir, "bge-m3.onnx")
    if not os.path.exists(model_file):
        model_file = os.path.join(model_dir, "model.onnx")
    if not os.path.exists(model_file):
        alt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embedder", "model", "bge-m3.onnx")
        if os.path.exists(alt_path):
            model_file = alt_path
        else:
            print(f"[gpu-embedder] ERROR: Model not found at {model_file} or {alt_path}", flush=True)
            raise RuntimeError(f"Model file not found: {model_file}")
    
    print(f"[gpu-embedder] Loading model: {model_file}")
    print(f"[gpu-embedder] Model name: {model_name}")
    
    # Create ONNX Runtime session with CUDA
    available = ort.get_available_providers()
    print(f"[gpu-embedder] Available providers: {available}")
    
    providers = []
    provider_options = []
    
    if 'CUDAExecutionProvider' in available:
        providers.append('CUDAExecutionProvider')
        provider_options.append({
            'device_id': 0,
            'cudnn_conv_algo_search': 'DEFAULT',
        })
        print("[gpu-embedder] CUDAExecutionProvider enabled")
    
    if 'TensorrtExecutionProvider' in available:
        providers.append('TensorrtExecutionProvider')
        provider_options.append({
            'device_id': 0,
            'trt_max_workspace_size': 4294967296,  # 4GB
        })
        print("[gpu-embedder] TensorrtExecutionProvider enabled")
    
    providers.append('CPUExecutionProvider')
    provider_options.append({})
    
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = 4
    
    session = ort.InferenceSession(
        model_file,
        sess_options=options,
        providers=providers,
        provider_options=provider_options,
    )
    
    print(f"[gpu-embedder] Active providers: {session.get_providers()}")
    
    # Probe dimension
    model_dir_path = model_dir if os.path.isdir(model_dir) else os.path.dirname(model_dir)
    tokenizer = SimpleTokenizer(model_dir_path)
    
    tokens = tokenizer.encode("hello world", max_length=32)
    # Remove token_type_ids if model doesn't need it
    feed = {"input_ids": tokens["input_ids"], "attention_mask": tokens["attention_mask"]}
    
    # Check if model has 3 inputs
    input_names = [inp.name for inp in session.get_inputs()]
    print(f"[gpu-embedder] Model input names: {input_names}")
    
    if "token_type_ids" in input_names:
        feed["token_type_ids"] = tokens["token_type_ids"]
    
    output = session.run(None, feed)
    dim = output[0].shape[-1]
    dimension = dim
    print(f"[gpu-embedder] Model dimension: {dim}")
    print(f"[gpu-embedder] GPU embedder ready on port {os.environ.get('PORT', '9093')}")


# ---------------------------------------------------------------------------
# Handlers (mirror Rust embedder API)
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    global embedding_count
    return {
        "status": "ok",
        "model": model_name,
        "dimension": dimension,
        "embedding_count": embedding_count,
        "dimensions_supported": True,
        "rss_kb": 0,
        "uptime_seconds": int(time.time() - start_time),
        "provider": session.get_providers()[0] if session else "none",
        "gpu": True,
    }


@app.get("/metrics")
async def metrics():
    uptime = int(time.time() - start_time)
    return f"""# HELP embedder_rss_bytes Resident set size of the embedder process
# TYPE embedder_rss_bytes gauge
embedder_rss_bytes 0
# HELP embedder_embedding_count Total embeddings computed
# TYPE embedder_embedding_count counter
embedder_embedding_count {embedding_count}
# HELP embedder_uptime_seconds Uptime of the embedder process
# TYPE embedder_uptime_seconds gauge
embedder_uptime_seconds {uptime}
# HELP embedder_dimension Embedding dimension
# TYPE embedder_dimension gauge
embedder_dimension {dimension}
# HELP embedder_model_info Static model info as label
# TYPE embedder_model_info gauge
embedder_model_info{{model="{model_name}"}} 1
"""


@app.post("/embed")
async def embed(request: Request):
    global embedding_count
    data = await request.json()
    
    texts = data.get("texts") or (data.get("text") and [data.get("text")]) or []
    if not texts:
        return {"embedding": [], "embeddings": None, "dimension": 0}
    
    all_embeddings = []
    for t in texts:
        tokens = tokenizer.encode(t, max_length=512)
        feed = {"input_ids": tokens["input_ids"], "attention_mask": tokens["attention_mask"]}
        input_names = [inp.name for inp in session.get_inputs()]
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = tokens["token_type_ids"]
        
        output = session.run(None, feed)
        pooled = mean_pooling(output[0], tokens["attention_mask"])
        all_embeddings.append(pooled[0].tolist())
    
    embedding_count += len(all_embeddings)
    
    requested_dim = data.get("dimensions", dimension)
    clamped_dim = min(requested_dim, dimension)
    for vec in all_embeddings:
        while len(vec) > clamped_dim:
            vec.pop()
    
    if len(all_embeddings) == 1:
        return {"embedding": all_embeddings[0], "embeddings": None, "dimension": clamped_dim}
    else:
        return {"embedding": all_embeddings[0], "embeddings": all_embeddings, "dimension": clamped_dim}


@app.post("/v1/embeddings")
async def openai_embed(request: Request):
    global embedding_count
    data = await request.json()
    
    inp = data.get("input", "")
    if isinstance(inp, str):
        texts = [inp]
    elif isinstance(inp, list):
        texts = inp
    else:
        texts = []
    
    if not texts:
        return JSONResponse({
            "error": {"message": "input must be a non-empty string or array", "type": "invalid_request_error"}
        }, status_code=400)
    
    all_embeddings = []
    for t in texts:
        # Truncate long inputs
        if len(t) > 1800:
            t = t[:1800]
        
        tokens = tokenizer.encode(t, max_length=512)
        feed = {"input_ids": tokens["input_ids"], "attention_mask": tokens["attention_mask"]}
        input_names = [inp.name for inp in session.get_inputs()]
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = tokens["token_type_ids"]
        
        output = session.run(None, feed)
        pooled = mean_pooling(output[0], tokens["attention_mask"])
        all_embeddings.append(pooled[0].tolist())
    
    embedding_count += len(all_embeddings)
    
    requested_dim = data.get("dimensions", dimension)
    clamped_dim = min(requested_dim, dimension)
    for vec in all_embeddings:
        while len(vec) > clamped_dim:
            vec.pop()
    
    data_list = [
        {"object": "embedding", "index": i, "embedding": emb}
        for i, emb in enumerate(all_embeddings)
    ]
    
    return {
        "object": "list",
        "data": data_list,
        "model": data.get("model", model_name),
        "usage": {
            "prompt_tokens": sum(len(t) // 4 for t in texts),
            "total_tokens": sum(len(t) // 4 for t in texts),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9093"))
    print(f"[gpu-embedder] Starting GPU embedder on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
