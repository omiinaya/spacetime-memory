# SQL Injection Audit — 2026-07-05

**Task**: SQL injection audit of the `_sql` endpoint and its usage across the codebase.

## Summary

The SDK exposes a `_sql()` method that sends raw SQL strings to SpacetimeDB's `/v1/database/{db}/sql` HTTP endpoint. The SDK provides `_esc()` (single-quote doubling) as the only SQL injection defense, but it is insufficient and inconsistently applied. The proper defense — the `_query()` method backed by the `query_table` reducer — exists but is not used everywhere it should be.

**Risk level**: Medium-High. A compromised client identity or a CLI command receiving crafted input can query tables the user should not have access to, bypassing workspace-level row security.

---

## Architecture: Two Query Paths

### Path A: Safe — `_query()` → `query_table` reducer

```
SDK._query(table, workspace_id, filter_dict, columns)
  → _call("query_table", [query_id, table, workspace_id, filter_json, columns_json])
    → Rust reducer: require_auth + check_space_access + whitelist check
      → writes to query_result table (scoped by random query_id)
SDK reads from query_result WHERE query_id = ?
```

**Auth**: `query_table` checks authentication (`require_auth`) AND workspace access (`check_space_access`).

**Table whitelist**: Only tables in the `ALLOWED_TABLES` constant can be queried (60+ tables, but explicitly controlled).

### Path B: Unsafe — `_sql()` → raw HTTP POST to `/sql`

```
SDK._sql("SELECT * FROM memory WHERE ...")
  → POST /v1/database/{db}/sql with body = raw SQL string
    → SpacetimeDB's built-in SQL endpoint
      → auth: identity-token-based (no workspace-level check)
      → no table whitelist
      → no row-level security
```

**Auth**: HTTP-level identity token only (SpacetimeDB's built-in auth). Any authenticated client can query **any public table**, regardless of workspace membership.

---

## `_esc()` Analysis

```python
def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")
```

**What it prevents**: String breakouts in `WHERE col = '{value}'` patterns.

**What it does NOT prevent**:

| Risk | Example | Impact |
|------|---------|--------|
| Non-string injection | `WHERE id = {user_number}` (no quotes around value) | Type coercion, time-based inference |
| ORDER BY injection | `ORDER BY {user_column}` | Error-based enumeration of columns |
| LIMIT injection | `LIMIT {user_value}` | Error-based inference, possible resource exhaustion |
| No escaping at all | `WHERE workspace_id = '{workspace_id}'` where workspace_id is unescaped | Full SQL injection |
| LIKE injection | `WHERE name LIKE '%{user_input}%'` | `_esc()` doesn't escape `%` or `_` wildcards |

---

## Vulnerable CLI Patterns

### 1. Unescaped workspace_id (stmem.py:709)

```python
clauses = [f"workspace_id = '{workspace_id}'", "is_active = true"]
where = " AND ".join(clauses)
rows = client._sql(f"SELECT * FROM memory WHERE {where}")
```

`workspace_id` comes from a `click.argument()` — user-controlled. Not escaped.

### 2. Unescaped status filter (stmem.py:2810)

```python
where = f"status = '{status}'"
rows = client._sql(f"SELECT * FROM mental_model WHERE {where} ORDER BY created_at DESC")
```

`status` comes from `click.option()` — user-controlled. Not escaped.

### 3. Escaped but still in raw SQL path (stmem.py:1202, 2918, 2925)

```python
rows = _sdk_client()._sql(f"SELECT * FROM fact WHERE id = '{_esc(fact_id)}'")
```

`_esc()` is applied, which prevents string breakout, but the query still runs through the unprotected SQL endpoint. If `_esc()` were to be removed or a different quoting context arises, injection is trivial.

### 4. Escaped but read from public result table (stmem.py:387-391, 1147-1149)

```python
rows = client._sql(f"SELECT * FROM space_member_result WHERE ...")
```

Properly escaped, but reads from result tables via raw SQL rather than the protected `_query` path. Result tables are public in SpacetimeDB — any authenticated client could craft SQL to read another user's results if they can guess the query_id.

---

## Server-Side Impact

On the SpacetimeDB server:

1. **`account` table** is declared `private` — SpacetimeDB prevents direct SQL access to private tables. The `require_auth`/`require_admin` pattern in reducers is the only way to read account data. So a SQL injection attack on `_sql()` cannot directly read password hashes.

2. **`api_key` table** is also `private` — key hashes are protected from raw SQL.

3. **Public tables** (memory, note, kg_node, etc.) are readable by any authenticated client via raw SQL. The workspace-level access control only applies when queries go through the `query_table` reducer.

4. **DELETE/UPDATE via SQL**: SpacetimeDB's HTTP SQL endpoint typically only allows SELECT queries from the HTTP API for safety. Mutations go through reducers. However, if the SpacetimeDB configuration allows write SQL through the HTTP endpoint, the impact escalates significantly.

---

## Recommendations

### Immediate fixes (P0)

1. **Add `_esc()` to ALL user-supplied values in CLI SQL queries** — specifically workspace_id (line 709) and status (line 2810, 2808 in stmem.py).

2. **Move memory listing (stmem.py:698-709) to use `_query()` with filter_dict** instead of raw SQL. The `_query()` method supports workspace_id + tier + is_active + memory_type filtering.

3. **Move mental_model listing (stmem.py:2806-2810) to use a reducer** or at minimum escape the status parameter.

### Medium-term fixes (P1)

4. **Audit ALL `_sql()` calls in CLI/SDK/server** and replace with `_query()` where possible. `_sql()` should only be used for public result tables (`hybrid_result`, `query_result`, etc.) where the query is purely system-generated.

5. **Add `require_auth` to any new SQL query reducer** — every reducer that reads from private tables must call `require_auth()` first.

### Defensive hardening (P2)

6. **Document that `_sql()` is for system-generated queries only and MUST always use `_esc()` for any interpolated value**. Add a linter rule or type annotation to enforce this.

7. **Consider adding a SpacetimeDB proxy/sidecar that intercepts raw SQL** and enforces table whitelists + workspace access, so that even compromised clients are constrained.

---

## Files inspected

| File | Lines | Role |
|------|-------|------|
| `sdk/python/spacetime_memory/client.py` | 521-553, 5113-5115 | `_sql()` + `_esc()` definitions |
| `plugins/hermes/__init__.py` | 184-203 | Hermes plugin `_sql()` wrapper |
| `cli/stmem.py` | 384-391, 698-709, 1138-1149, 1197-1206, 2799-2810, 2910-2928 | CLI commands with raw SQL |
| `server/spacetimedb/src/query.rs` | 1-120 | `query_table` reducer (whitelist-based safe path) |
| `server/spacetimedb/src/auth.rs` | 354-359 | `require_auth()` implementation |

## Timeline

- Audit conducted: 2026-07-05
- Branch: `cyber-elf/task_49797b619f444947_`
- Committed alongside ROADMAP.md update marking task complete
