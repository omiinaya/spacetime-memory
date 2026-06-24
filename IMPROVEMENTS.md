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
Files: client/spacetime_memory/client.py, server/spacetimedb/src/
Difficulty: Medium
Est: 3-4h

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

### .env stale config cleanup
EMBEDDER_TYPE=local has no effect — the code ignores it. Clean up
vestigial env vars and validate the config schema.
Files: client/spacetime_memory/config.py
Difficulty: Easy
Est: 20 min

---

## Recently Completed

### ✅ PyPI publish pipeline
Package is built, wtih correct packages-dir, twine verification step,
and __version__ attribute. Pushing a v* tag triggers the publish workflow.
Fixed: publish.yml packages-dir path, added twine check, added __version__
to spacetime_memory/__init__.py, updated publish guide.
Commit: e1ba6fe
Date: 2026-06-24

---

*(cron manages this section — moves items here when marked ✅, purges old ones)*
