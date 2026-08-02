# Adapter Authoring Guide

How to add a new competitor-compatible adapter to Spacetime-Memory.

## What an Adapter Is

Adapters give the SDK a drop-in API surface compatible with a third-party
memory system (Mem0, Zep, Graphiti, Honcho, LangMem, Cognee, Hindsight, Letta,
QMD, Mnemosyne, GBrain). Each adapter lives in
`sdk/python/spacetime_memory/sdks/<name>/` and wraps Spacetime-Memory's native
primitives behind the target library's public API.

## Steps

1. **Create the module**
   ```bash
   mkdir -p sdk/python/spacetime_memory/sdks/<name>
   ```
   Put the main client class in `_client.py`, split large mixins into
   `_search.py`, `_models.py`, etc. Keep files under ~600 lines.

2. **Match the upstream API surface**
   - Read the upstream library's README and public classes.
   - Implement every public method **with the same signatures**.
   - Return types should match upstream shapes (records, result objects).

3. **Back everything with native primitives**
   - `Client.store()` / `Client.search()` → memory operations
   - `Client.create_node()` / `create_edge()` / KG queries → graph operations
   - `Client._query()` for workspace-scoped reads (respects ACL)
   - **Never** shell out to the upstream library itself — the point is native
     implementation with zero runtime dependencies.

4. **Export it**
   ```python
   # sdks/__init__.py
   from .<name> import <MainClass>
   ```

5. **Write tests**
   - Unit tests in `sdk/python/tests/test_<name>_adapter.py` with mocked HTTP.
   - Wire-compat tests that assert the adapter's method names match upstream.
   - Every feature must have at least one test that exercises it.

6. **Update the parity matrix**
   - Add a row to `ADAPTER_COMPAT.md` with the feature checklist.
   - Mark each feature ✅ (implemented + tested) / 🔄 (mapped) / ❌ (gap).

7. **Document it**
   - Add a page under `docs/api/python/` or the adapter's README.
   - Keep `docs/development.md` quick-checklist in sync.

## Rules

- **Zero external deps** — adapters must work with only the SDK's own
  dependencies (httpx, click, rich, onnxruntime optional). If the upstream
  library is needed for a feature, implement the behavior natively instead.
- **Graceful degradation** — LLM-powered features must degrade to a sensible
  fallback when no API key is configured.
- **Tests gate completion** — an adapter is not "done" until its test file
  passes in the full suite (`pytest tests/ -m unit`).
