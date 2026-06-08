# ============================================================================
# Spacetime Memory — Multi-stage Docker Build
# ============================================================================
# Stage 1: Build the ONNX embedder sidecar (Rust binary, listens :9090)
# ============================================================================
FROM rust:1.80-slim AS embedder-builder
WORKDIR /build
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
COPY server/embedder/Cargo.toml server/embedder/Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs
# Cache dependencies
RUN cargo build --release 2>/dev/null || true
COPY server/embedder/src/ src/
# Force rebuild of our actual code with retry for network flakes
RUN touch src/main.rs && \
    for i in 1 2 3; do cargo build --release && break; sleep 5; done

# ============================================================================
# Stage 2: Build the SpacetimeDB module (Rust → wasm)
# ============================================================================
FROM rust:1.80-slim AS module-builder
WORKDIR /build
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
RUN rustup target add wasm32-unknown-unknown
COPY server/spacetimedb/ .
RUN cargo build --release --target wasm32-unknown-unknown

# ============================================================================
# Stage 3: Build the frontend (Vite + React + TypeScript)
# ============================================================================
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ .
RUN npm run build

# ============================================================================
# Stage 4: Runtime image — contains everything needed to run
# ============================================================================
FROM python:3.11-slim
WORKDIR /app

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- SpacetimeDB CLI + Standalone (v2.4.1) ----
RUN curl -fsSL https://github.com/clockworklabs/SpacetimeDB/releases/download/v2.4.1/spacetime-x86_64-unknown-linux-gnu.tar.gz | \
    tar xz -C /usr/local/bin/

# ---- Python SDK ----
COPY sdk/python/ sdk/python/
RUN pip install --no-cache-dir -e sdk/python

# ---- Python CLI ----
COPY cli/ cli/
RUN pip install --no-cache-dir -e cli

# ---- Rust embedder binary ----
COPY --from=embedder-builder /build/target/release/embedder /usr/local/bin/embedder

# ---- ONNX embedding model ----
COPY scripts/download-model.sh ./scripts/download-model.sh
RUN apt-get update && apt-get install -y python3-pip && pip install huggingface-hub && bash scripts/download-model.sh

# ---- SpacetimeDB WASM module ----
COPY --from=module-builder /build/target/wasm32-unknown-unknown/release/spacetime_memory.wasm /app/module/spacetime_memory.wasm
COPY server/spacetimedb/Cargo.toml /app/module/Cargo.toml

# ---- Frontend static build ----
COPY --from=frontend-builder /build/dist/ /app/frontend/

# ---- Config ----
# config.toml is generated at build time (may not exist in build context)
RUN mkdir -p /app/data && \
    if [ ! -f /app/data/config.toml ]; then \
        printf '[logs]\ndirectives = [\n    "spacetimedb=debug",\n    "spacetimedb_client_api=debug",\n    "spacetimedb_lib=debug",\n    "spacetimedb_standalone=debug",\n    "spacetimedb_commitlog=info",\n    "spacetimedb_durability=info",\n]\n' > /app/data/config.toml; \
    fi
# Generate JWT keys if not present
RUN if [ ! -f /app/data/id_ecdsa_pkcs8.pem ]; then \
        apt-get install -y --no-install-recommends openssl && \
        openssl ecparam -genkey -name prime256v1 -noout -out /app/data/id_ecdsa.pem && \
        openssl ec -in /app/data/id_ecdsa.pem -pubout -out /app/data/id_ecdsa.pub && \
        openssl pkcs8 -topk8 -nocrypt -in /app/data/id_ecdsa.pem -out /app/data/id_ecdsa_pkcs8.pem && \
        rm -f /app/data/id_ecdsa.pem && \
        apt-get purge -y openssl && apt-get autoremove -y; \
    fi
COPY .env.example /app/.env

# Expose ports:
#   3001 – SpacetimeDB
#   9090 – Embedder
#   5173 – Frontend (static HTTP server)
EXPOSE 3001 9090 5173

# ---- Entrypoint ----
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV SPACETIMEDB_HOST=0.0.0.0
ENV SPACETIMEDB_PORT=3001
ENV EMBEDDER_MODEL_PATH=/app/model/all-MiniLM-L6-v2.onnx
ENV SPACETIMEDB_DB=spacetime-memory

ENTRYPOINT ["docker-entrypoint.sh"]
