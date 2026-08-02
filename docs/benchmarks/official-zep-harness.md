# Running the Official Zep LOCOMO Harness against Spacetime-Memory

Zep publishes a LOCOMO benchmark harness at `getzep/zep/benchmarks/locomo`.
We integrate with it via a drop-in `zep_cloud` shim so the **official Zep code,
prompts, graders, and metrics** run unchanged against the Spacetime-Memory
engine. The only difference is which backend answers `graph.create /
set_ontology / add / search`.

## Zep's published number (their repo)

`zep/benchmarks/locomo/experiments/experiment_20251207_182039/experiment_summary.json`
→ LoCoMo mean accuracy **0.696 (69.6%)** across 10 runs (gpt-4o-mini as both
response model and grader, graph edge_limit=5, node_limit=2).

## Setup

```bash
git clone https://github.com/getzep/zep ~/zep
cd ~/zep/benchmarks/locomo

# Our shim (this repo) provides zep_cloud; copy it into the harness dir:
cp -r <this-repo>/scripts/benchmarks/official_zep_harness/zep_cloud ./
cp <this-repo>/scripts/benchmarks/official_zep_harness/benchmark_config_stmem.yaml ./

# Deps into the project venv (harness + SDK both importable):
/path/to/spacetime-memory/.venv/bin/pip install pandas tiktoken tenacity orjson zep-cloud
```

## Ingest + evaluate

```bash
cd ~/zep/benchmarks/locomo
OTEL_ENABLED=false \
OPENAI_API_KEY=dummy-key OPENAI_BASE_URL=http://localhost:4004/v1 \
ZEP_API_KEY=dummy STDB_DB=spacetime-memory-v2 \
  /path/to/spacetime-memory/.venv/bin/python -m benchmark \
    --ingest --config benchmark_config_stmem.yaml --prefix stmem

# then
... python -m benchmark --eval --config benchmark_config_stmem.yaml --prefix stmem
```

The shim (`zep_cloud/`) maps:
- `graph.create(graph_id, ...)` → `create_workspace` (idempotent)
- `graph.add(graph_id, type, data, created_at)` → SDK `store()` (embeds+indexes)
- `graph.search(query, graph_id, scope, reranker, limit)` → hybrid search
- `set_ontology` → no-op (engine infers schema)
- `core.api_error.ApiError` / `external_clients.ontology.EntityModel` → stubs

## Fairness notes

- Zep's published run used gpt-4o-mini response+grader. Our config uses
  deepseek-v4-flash-free via the local proxy.
- Same locomo10.json dataset, same harness code, same grader prompts.
