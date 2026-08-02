#!/bin/bash
# ============================================================================
# download-model.sh — Download ONNX embedding model for the embedder sidecar
# ============================================================================
# Downloads the ONNX model for BAAI/bge-m3 (or a lightweight ONNX variant for
# CPU inference). The tokenizer is loaded at runtime from HuggingFace.
# ============================================================================
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/app/model}"
MODEL_NAME="${MODEL_NAME:-bge-m3}"
ONNX_REPO="${ONNX_REPO:-Xenova/bge-small-en-v1.5}"
ONNX_FILE="${ONNX_FILE:-onnx/model.onnx}"

mkdir -p "$MODEL_DIR"

echo "==> Downloading ONNX model: $ONNX_REPO / $ONNX_FILE"
echo "    Target: $MODEL_DIR/$MODEL_NAME.onnx"

python3 -c "
import os, sys
from huggingface_hub import hf_hub_download

repo = os.environ.get('ONNX_REPO', 'Xenova/bge-small-en-v1.5')
filename = os.environ.get('ONNX_FILE', 'onnx/model.onnx')
model_dir = os.environ.get('MODEL_DIR', '/app/model')
model_name = os.environ.get('MODEL_NAME', 'bge-m3')

print(f'  Downloading {repo}/{filename}...')
try:
    model_path = hf_hub_download(
        repo_id=repo,
        filename=filename,
        local_dir=model_dir,
        local_dir_use_symlinks=False,
    )
    target = os.path.join(model_dir, f'{model_name}.onnx')
    if model_path != target:
        import shutil
        shutil.copy2(model_path, target)
        print(f'  Copied to {target}')
    print('  Done.')
except Exception as e:
    print(f'  WARNING: download failed: {e}')
    print(f'  The embedder will use the default model path and may fail if')
    print(f'  the ONNX file is not present at runtime.')
    sys.exit(0)
"

echo "==> Model download complete."
echo "    Model path: $MODEL_DIR/$MODEL_NAME.onnx"
ls -lh "$MODEL_DIR/$MODEL_NAME.onnx" 2>/dev/null || echo "    (file not found)"
