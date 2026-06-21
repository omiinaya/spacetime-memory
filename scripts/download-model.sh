#!/usr/bin/env bash
# Download the bge-large-en-v1.5 ONNX model for the Rust embedder sidecar.
# Run from the repository root: ./scripts/download-model.sh
set -euo pipefail

MODEL_DIR="server/embedder/model"
MODEL_NAME="bge-large-en-v1.5"
mkdir -p "$MODEL_DIR"

echo "Downloading $MODEL_NAME ONNX model to $MODEL_DIR/..."

python3 -c "
from huggingface_hub import hf_hub_download
import os, shutil

path = hf_hub_download(
    repo_id='Xenova/bge-large-en-v1.5',
    filename='onnx/model.onnx',
)

dst = 'server/embedder/model/bge-large-en-v1.5.onnx'
shutil.copy2(path, dst)
print(f'Model saved to {dst} ({os.path.getsize(dst) // 1024 // 1024} MB)')
"

echo "Done. Run with: env MODEL_PATH=server/embedder/model/bge-large-en-v1.5.onnx server/embedder/target/release/embedder"
