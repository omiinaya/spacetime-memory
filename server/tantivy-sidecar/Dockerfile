# ============================================================================
# Tantivy BM25 Sidecar — Dockerfile
# ============================================================================
# Standalone service providing BM25 full-text search via Tantivy.
# Listens on port 9091 by default.
# ============================================================================

# ---- Builder stage ----
FROM rust:1-slim AS builder
ENV CARGO_NET_RETRY=5 \
    CARGO_HTTP_TIMEOUT=120 \
    CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs
# Pre-fetch dependencies
RUN cargo build --release 2>/dev/null || true
COPY src/ src/
RUN touch src/main.rs && cargo build --release

# ---- Runtime stage ----
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/release/tantivy-sidecar /usr/local/bin/tantivy-sidecar
EXPOSE 9091
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -sf http://localhost:9091/health || exit 1
ENTRYPOINT ["tantivy-sidecar"]
