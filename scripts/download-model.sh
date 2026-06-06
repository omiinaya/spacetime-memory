#!/usr/bin/env bash
# Download the all-MiniLM-L6-v2 ONNX model for the Rust embedder sidecar.
# Run from the repository root: ./scripts/download-model.sh
set -euo pipefail

MODEL_DIR="server/embedder/model"
MODEL_NAME="all-MiniLM-L6-v2"
mkdir -p "$MODEL_DIR"

echo "Downloading $MODEL_NAME ONNX model to $MODEL_DIR/..."

python3 -c "
from huggingface_hub import hf_hub_download
import os

path = hf_hub_download(
    repo_id='Xenova/all-MiniLM-L6-v2',
    filename='onnx/model.onnx',
)

# Copy to expected location
import shutil
dst = 'server/embedder/model/all-MiniLM-L6-v2.onnx'
shutil.copy2(path, dst)
print(f'Model saved to {dst} ({os.path.getsize(dst) // 1024 // 1024} MB)')
"

echo "Done. Run the embedder with: env MODEL_PATH=server/embedder/model/all-MiniLM-L6-v2.onnx server/embedder/target/release/embedder"
