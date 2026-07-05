# SQL Injection Audit

**Date:** 2026-07-05
**Auditor:** Cyber Elf (hermes)
**Repo:** spacetime-memory
**Task:** task_49797b619f444947

## Summary

The `_sql()` endpoint sends raw SQL strings as POST body to SpacetimeDB's HTTP SQL API (`/v1/database/{db}/sql`). The SDK provides `_esc()` which only escapes single quotes (`'` → `''`), protecting string values. However, multiple call sites interpolate user-controlled values into SQL strings **without** calling `_esc()`, creating exploitable SQL injection vectors.

No parameterized query support exists in STDB v2, making defense-in-depth via consistent `_esc()` usage essential.

## Risk Classification

| Severity | Count | Description |
|----------|-------|-------------|
| CRITICAL | 4     | User-controlled input from MCP/API arguments interpolated unescaped into SQL |
| MODERATE | 4     | CLI arguments interpolated unescaped (lower blast radius) |
| BROKEN   | 1     | Dead LIKE clause: `{q}` literal text, `query` param never interpolated |

All call sites that use **hardcoded SQL** (no f-string / `.format()` interpolation) are safe by construction.

---

## CRITICAL Findings

### C1. Hermes Plugin — KG query (line 641)

**File:** `plugins/hermes/__init__.py:641`
**Code (before fix):**
```python
f"label LIKE '%{query}%' "
```
`query` comes from `args.get("query", "")` — an MCP tool argument. No `_esc()` wrapping.

**Exploit:**
```
query = "' OR 1=1 --"
→ label LIKE '%' OR 1=1 -- %'
→ returns ALL nodes (data leak)
```

**Fix applied:** Wrapped `query` with `_esc()`.

### C2. Hermes Plugin — Profile query (line 674)

**File:** `plugins/hermes/__init__.py:674, 692`
**Code (before fix):**
```python
f"WHERE peer_id = '{peer_id}'"
```
`peer_id` comes from `args.get("peer_id", "")` — an MCP tool argument. No `_esc()`.

**Exploit:**
```
peer_id = "' OR 1=1; DROP TABLE profile; --"
```

**Fix applied:** Wrapped both `peer_id` references with `_esc()`.

### C3. MCP Server — get_mental_model (line 2194)

**File:** `server/mcp/main.py:2194`
**Code (before fix):**
```python
rows = client._sql(f"SELECT * FROM mental_model WHERE id = '{id}'")
```
`id` is a direct tool argument. No `_esc()`.

**Fix applied:** Wrapped `id` with `_esc()`.

### C4. MCP Server — list_mental_models (lines 2208-2210)

**File:** `server/mcp/main.py:2208-2211`
**Code (before fix):**
```python
where = f"workspace_id = '{workspace_id}'"
if status:
    where += f" AND status = '{status}'"
```
Both `workspace_id` and `status` are direct tool arguments. Neither used `_esc()`.

**Fix applied:** Wrapped both with `_esc()`.

---

## MODERATE Findings

### M1. Replication daemon (line 255)

**File:** `scripts/replication_daemon.py:255`
**Code (before fix):**
```python
"AND workspace_id = '{}' ".format(workspace_id)
```
`workspace_id` comes from the sync request. Used `.format()` without `_esc()`.

**Fix applied:** Changed to f-string with `_esc()`.

### M2. SDK CLI — memory list (lines 700-710)

**File:** `sdk/python/spacetime_memory/cli.py:700-710`
**Code (before fix):**
```python
f"workspace_id = '{workspace_id}'"
```
`workspace_id`, `memory_type`, `tier` interpolated via f-strings without `_esc()`.
(Note: `cli/stmem.py` already uses `_esc()` — this was a fork divergence.)

**Fix applied:** Wrapped all three with `_esc()`.

### M3. SDK CLI — mental model list (line 2727)

**File:** `sdk/python/spacetime_memory/cli.py:2727`
**Code (before fix):**
```python
where = f"status = '{status}'"
```
CLI argument, no `_esc()`.

**Fix applied:** Wrapped `status` with `_esc()`.

---

## BROKEN

### B1. Hermes Plugin — Notes search (line 609)

**File:** `plugins/hermes/__init__.py:609`
**Code (before fix):**
```python
"AND (title LIKE '%{q}%' OR content LIKE '%{q}%') "
```
This is a **regular string** (no `f` prefix), so `{q}` is literal text sent to the database. The `query` variable was never interpolated. The LIKE condition is dead code — it never matched anything meaningful.

**Fix applied:** Changed to f-string with `_esc(query)`.

---

## Safe-by-construction patterns

- **SDK client.py internal `_sql()` calls** — all use `_esc()` consistently
- **Hardcoded SQL** (no interpolation) — safe
- **`scripts/rotate-keys.py`** — hardcoded SQL, safe
- **`scripts/mental_model_synthesis.py`** — uses `_esc()` for interpolated values, safe
- **`scripts/backup.py`** — uses `_esc(ws)`, safe
- **`cli/stmem.py`** — uses `_esc()` consistently (unlike its SDK counterpart)

## Recommendations

1. **Immediate (done):** Wrap all user-controlled values with `_esc()` at the identified call sites.
2. **Short-term:** Add a linter rule (`flake8-bandit` or `semgrep`) to flag `_sql()` calls with f-strings that don't wrap interpolated variables in `_esc()`.
3. **Medium-term:** Move all read operations to use `_call()` reducers instead of raw `_sql()`, gating them through the STDB auth layer. The `_query()` method already does this — use it as the pattern.
4. **Long-term:** Push for STDB parameterized query support so `_esc()` is no longer needed.
