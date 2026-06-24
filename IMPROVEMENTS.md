# Spacetime Memory — Improvement Backlog

Living queue managed by the continuous-improvement cron. The cron reads this file,
cleans up completed items, researches new improvement opportunities, adds them,
and works the top pending item each tick.

---

## Status: PENDING

### OpenTelemetry / observability integration
Add OpenTelemetry tracing/metrics to the client SDK and server module.
Instrument search latency, embedding calls, and STDB write times.
Reference: open-telemetry/opentelemetry-python
Files: sdk/python/spacetime_memory/client.py, server/spacetimedb/src/
Difficulty: Medium
Est: 3-4h

P0: Python SDK — DONE (Jun 24)
  - Created sdk/python/spacetime_memory/tracer.py: Tracer class, get_tracer(),
    start_span() context manager, instrument_method() decorator, optional
    OTLP HTTP export, graceful degradation when OTel packages absent.
  - Added `otel` optional dependency group in pyproject.toml.
  - Exported Tracer/get_tracer/start_span from __init__.py.
  - Instrumented client.py: _call (all reducer calls), _sql, _embed,
    _embed_openai, _embed_batch, _embed_batch_openai, check_embedder_health,
    store (reducer call), store_batch (reducer call), search (hybrid search).
  - All 186 unit tests pass.
  Commit: pending

P1: Rust server module — NOT STARTED
  - Add tracing spans to server/spacetimedb/src/ reducers using
    spacetimedb::log::info or custom metrics table.
  - Reference: SpacetimeDB v2.4 SDK logging API.

### STDB 2% fatal error under heavy concurrent load
Despite the UUID collision fix, some concurrent stress scenarios still
trigger WASM fatal errors. Need root cause analysis with replicator.
Files: server/spacetimedb/src/lib.rs, tests/concurrent/
Difficulty: Hard
Est: 4-8h

### Multi-region / failover support
No tests or code for multi-region STDB deployment. Need to document
and implement failover connectivity in the client SDK.
Files: client/spacetime_memory/client.py
Difficulty: Medium
Est: 4h

### Knowledge graph visualization in frontend
The KG works (<20ms) but has no visual graph explorer in the web UI.
Add a D3/vis.js graph viewer for exploring nodes and connections.
Files: web/src/pages/
Difficulty: Medium
Est: 3h

## Recently Completed

### ✅ .env stale config cleanup
EMBEDDER_TYPE=local/openai/auto had no effect since the codebase migrated
to the OpenAI-compatible proxy path. Removed vestigial env var from
client.py, graphiti.py, all docs, example files, and scripts.
Commit: ec81a0b
Date: 2026-06-24

### ✅ PyPI publish pipeline
Package is built, wtih correct packages-dir, twine verification step,
and __version__ attribute. Pushing a v* tag triggers the publish workflow.
Fixed: publish.yml packages-dir path, added twine check, added __version__
to spacetime_memory/__init__.py, updated publish guide.
Commit: e1ba6fe
Date: 2026-06-24

---

*(cron manages this section — moves items here when marked ✅, purges old ones)*
