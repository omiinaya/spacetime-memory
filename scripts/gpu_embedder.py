#!/usr/bin/env python3
"""GPU-accelerated embedder using onnxruntime-gpu.

Loads bge-m3 ONNX model on CUDA and provides the same API
as the Rust embedder.
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import uvicorn
from fastapi import FastAPI, Request, Response
from tokenizers import Tokenizer

app = FastAPI()

# Constants
SCRIPT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = SCRIPT_DIR / "server" / "embedder" / "model"
MODEL_NAME = os.environ.get("MODEL_NAME", "BAAI/bge-m3")
MODEL_PATH = MODEL_DIR / "bge-m3.onnx"
TOKENIZER_PATH = MODEL_DIR / "bge-m3-tokenizer.json"
MAX_SEQ_LEN = 8192
EMBED_DIM = 1024

ort_session = None
tokenizer = None
model_input_names = []


def _mean_pooling(token_embeddings, attention_mask):
    input_mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(token_embeddings.dtype)
    input_mask_expanded = np.broadcast_to(input_mask_expanded, token_embeddings.shape)
    sum_embeddings = np.sum(token_embeddings * input_mask_expanded, axis=1)
    sum_mask = np.clip(np.sum(input_mask_expanded, axis=1), a_min=1e-9, a_max=None)
    return sum_embeddings / sum_mask


def _normalize(embeddings):
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / np.clip(norms, a_min=1e-12, a_max=None)


def load_model():
    global ort_session, tokenizer, model_input_names

    print(f"[gpu-embedder] Loading tokenizer from {TOKENIZER_PATH}", flush=True)
    if TOKENIZER_PATH.exists():
        tokenizer = Tokenizer.from_file(str(TOKENIZER_PATH))
    else:
        from tokenizers import Tokenizer as HF_Tokenizer
        tokenizer = HF_Tokenizer.from_pretrained(MODEL_NAME)
        TOKENIZER_PATH.parent.mkdir(parents=True, exist_ok=True)
        tokenizer.save(str(TOKENIZER_PATH))

    tokenizer.enable_truncation(max_length=MAX_SEQ_LEN)
    tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=None)

    print(f"[gpu-embedder] Loading ONNX model from {MODEL_PATH}", flush=True)
    print(f"[gpu-embedder] Available providers: {ort.get_available_providers()}", flush=True)

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.intra_op_num_threads = 4

    providers = [
        ("CUDAExecutionProvider", {"device_id": 0, "arena_extend_strategy": "kNextPowerOfTwo", "gpu_mem_limit": 12 * 1024 * 1024 * 1024}),
        "CPUExecutionProvider",
    ]

    ort_session = ort.InferenceSession(str(MODEL_PATH), sess_options=so, providers=providers)

    # Detect model inputs
    model_input_names = [inp.name for inp in ort_session.get_inputs()]
    print(f"[gpu-embedder] Model input names: {model_input_names}", flush=True)
    print(f"[gpu-embedder] Provider: {ort_session.get_providers()[0]}", flush=True)

    # Warm up
    print("[gpu-embedder] Warming up...", flush=True)
    test_text = "Warm up embedding."
    test_tokens = tokenizer.encode(test_text)
    input_ids = np.array([test_tokens.ids], dtype=np.int64)
    attention_mask = np.array([test_tokens.attention_mask], dtype=np.int64)

    onnx_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
    if "token_type_ids" in model_input_names and hasattr(test_tokens, 'type_ids') and test_tokens.type_ids:
        onnx_inputs["token_type_ids"] = np.array([test_tokens.type_ids], dtype=np.int64)

    _ = ort_session.run(None, onnx_inputs)
    print("[gpu-embedder] Warmup complete", flush=True)


@app.on_event("startup")
async def startup():
    load_model()


@app.get("/health")
async def health():
    provider = ort_session.get_providers()[0] if ort_session else "unknown"
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "dimension": EMBED_DIM,
        "backend": f"onnxruntime-gpu ({provider})",
        "uptime_seconds": int(time.time() - start_time),
    }


def _encode_texts(texts):
    """Encode a list of texts and return normalized embeddings."""
    batch_size = 32
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i + batch_size]
        batch_tokens = tokenizer.encode_batch(batch_texts)

        input_ids = np.array([t.ids for t in batch_tokens], dtype=np.int64)
        attention_mask = np.array([t.attention_mask for t in batch_tokens], dtype=np.int64)

        onnx_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in model_input_names and batch_tokens[0].type_ids:
            onnx_inputs["token_type_ids"] = np.array([t.type_ids for t in batch_tokens], dtype=np.int64)

        outputs = ort_session.run(None, onnx_inputs)
        last_hidden_state = outputs[0]

        pooled = _mean_pooling(last_hidden_state, attention_mask)
        normalized = _normalize(pooled)
        all_embeddings.append(normalized.tolist())

    return [emb for batch in all_embeddings for emb in batch]


@app.post("/embed")
async def embed(request: Request):
    body = await request.json()
    texts = body.get("texts", [])
    if not texts:
        return Response(status_code=400, content=json.dumps({"error": "no texts"}))

    embeddings = _encode_texts(texts)
    if len(embeddings) == 1:
        return {"embedding": embeddings[0]}
    return {"embedding": embeddings}


@app.post("/v1/embeddings")
async def openai_embed(request: Request):
    body = await request.json()
    input_text = body.get("input", "")
    model = body.get("model", MODEL_NAME)

    if isinstance(input_text, str):
        texts = [input_text]
    elif isinstance(input_text, list):
        texts = input_text
    else:
        texts = [str(input_text)]

    embeddings = _encode_texts(texts)
    data = [{"object": "embedding", "index": i, "embedding": emb} for i, emb in enumerate(embeddings)]

    return {
        "object": "list",
        "model": model,
        "data": data,
        "usage": {"prompt_tokens": sum(len(t.ids) for t in tokenizer.encode_batch(texts))},
    }


start_time = time.time()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9093"))
    print(f"[gpu-embedder] Starting on port {port}...", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
