/**
 * Shared SpacetimeDB client for the dashboard.
 *
 * Two critical STDB quirks handled here:
 *  1. The SQL endpoint expects the RAW SQL string as the request body with
 *     `Content-Type: text/plain` — NOT JSON-encoded.
 *  2. Private tables (workspace, note, profile, hybrid_result, ...) cannot be
 *     read via raw SQL even with an identity token — they require the
 *     `query_table` reducer flow (write to query_result, then read back).
 *     The dashboard reaches those through the native `stdb_sql_proxy`
 *     (scripts/stdb_sql_proxy.py) which authenticates server-side and exposes
 *     `POST /v1/database/{db}/query` for reducer-based table queries.
 */

interface StdbClient {
  host: string
  port: string
  database: string
}

/** Run a raw SQL query against a PUBLIC table (via the proxy or STDB directly). */
export async function stdbSql<T = any>(client: StdbClient, sql: string): Promise<T[]> {
  const res = await fetch(
    `http://${client.host}:${client.port}/v1/database/${encodeURIComponent(client.database)}/sql`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: sql,
      signal: AbortSignal.timeout(15000),
    },
  )
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`STDB error: ${res.status}${text ? ': ' + text.slice(0, 200) : ''}`)
  }
  const raw = await res.text()
  return parseSqlResponse<T>(raw)
}

/** Query a PRIVATE content table through the query_table reducer (proxy-backed). */
export async function stdbQuery<T = any>(
  client: StdbClient,
  table: string,
  workspaceId = '',
  filter: Record<string, any> = {},
  columns?: string[],
): Promise<T[]> {
  const res = await fetch(
    `http://${client.host}:${client.port}/v1/database/${encodeURIComponent(client.database)}/query`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ table, workspace_id: workspaceId, filter, columns: columns ?? [] }),
      signal: AbortSignal.timeout(20000),
    },
  )
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`STDB query error: ${res.status}${text ? ': ' + text.slice(0, 200) : ''}`)
  }
  const data = await res.json()
  return Array.isArray(data) ? (data as T[]) : []
}

/** Parse STDB's positional-array SQL response ({schema, rows}) into row dicts. */
export function parseSqlResponse<T = any>(raw: string): T[] {
  if (!raw || !raw.trim()) return []
  let tables: any[]
  try {
    tables = JSON.parse(raw)
  } catch {
    return []
  }
  const results: T[] = []
  for (const table of tables) {
    const elements = table?.schema?.elements ?? []
    const colNames: string[] = []
    for (const el of elements) {
      const nc = el?.name
      if (nc && typeof nc === 'object' && 'some' in nc) colNames.push(nc.some)
      else colNames.push('?col?')
    }
    for (const row of table?.rows ?? []) {
      const rowDict: Record<string, any> = {}
      for (let i = 0; i < row.length; i++) {
        rowDict[colNames[i] ?? `col${i}`] = row[i]
      }
      results.push(rowDict as T)
    }
  }
  return results
}

/** Sort rows by a string/ISO timestamp field, descending (STDB has no ORDER BY). */
export function sortDesc<T>(rows: T[], field: keyof T): T[] {
  return rows.slice().sort((a, b) => {
    const av = String((a as any)[field] ?? '')
    const bv = String((b as any)[field] ?? '')
    return bv.localeCompare(av)
  })
}

export type { StdbClient }
