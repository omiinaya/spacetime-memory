#!/bin/bash
# GPU Embedder startup script — replaces the old Rust CPU embedder
# Used by systemd/s6 for auto-restart on crash or reboot

set -euo pipefail

cd $HOME/spacetime-memory/server

export PYTHONUNBUFFERED=1
export MODEL_NAME="${MODEL_NAME:-BAAI/bge-m3}"
export MODEL_PATH="${MODEL_PATH:-$HOME/spacetime-memory/server/embedder/model}"
export PORT="${PORT:-9090}"

exec $HOME/spacetime-memory/.venv/bin/python3 -u embedder_gpu.py
