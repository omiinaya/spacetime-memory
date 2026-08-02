/**
 * Admin operations, config, diagnostics.
 */
import type { ClientLike } from "./types";
import { queryHash, sortByCreatedDesc } from "./helpers";
import { BACKUP_TABLES } from "./types";

export async function promoteAdmin(client: ClientLike, targetIdentity: string): Promise<void> {
  return client._call("promote_admin", [targetIdentity]);
}

export async function demoteAdmin(client: ClientLike, targetIdentity: string): Promise<void> {
  return client._call("demote_admin", [targetIdentity]);
}

export async function listAdmins(client: ClientLike): Promise<Record<string, unknown>[]> {
  await client._call("list_admins", []);
  const rows = await client._sqlExec("SELECT row_json FROM admin_result", {});
  return rows.map((r: Record<string, unknown>) => {
    if (r?.row_json) {
      try { return JSON.parse(r.row_json as string) as Record<string, unknown>; } catch { return r; }
    }
    return r;
  });
}

export async function backup(client: ClientLike, outputPath?: string): Promise<Record<string, unknown>> {
  const manifest: Record<string, unknown[]> = {};
  const backedUp: string[] = [];
  let totalRows = 0;

  for (const table of BACKUP_TABLES) {
    try {
      const rows = await client._query(table);
      manifest[table] = rows as unknown[];
      totalRows += (rows as unknown[]).length;
      backedUp.push(table);
    } catch {
      manifest[table] = [];
    }
  }

  const date = new Date().toISOString().slice(0, 10);
  const finalPath = outputPath ?? `spacetime-memory-backup-${date}.json`;

  const payload = {
    version: "0.3.0",
    created_at: new Date().toISOString(),
    tables: manifest,
    stats: { table_count: backedUp.length, total_rows: totalRows },
  };

  const json = JSON.stringify(payload, null, 2);
  if (typeof process !== "undefined" && typeof process.version === "string") {
    const fs = await import("fs");
    fs.writeFileSync(finalPath, json, "utf-8");
  }

  return { status: "ok", path: finalPath, tables: backedUp, total_rows: totalRows };
}

export async function restore(client: ClientLike, inputJson: string | Record<string, unknown>): Promise<Record<string, unknown>> {
  const payload: Record<string, unknown> = typeof inputJson === "string" ? JSON.parse(inputJson) : inputJson;
  const manifest = (payload.tables ?? {}) as Record<string, unknown[]>;
  const restored: string[] = [];
  let totalRestored = 0;

  for (const [table, rows] of Object.entries(manifest)) {
    if (!rows || rows.length === 0) continue;
    const firstRow = rows[0] as Record<string, unknown> | undefined;
    if (!firstRow || Object.keys(firstRow).length === 0) continue;
    try {
      const colNames = Object.keys(firstRow);
      for (const row of rows) {
        const rawRow = row as Record<string, unknown>;
        const values = colNames.map((col) => {
          const val = rawRow[col];
          if (val === null || val === undefined) return "NULL";
          if (typeof val === "boolean") return val ? "true" : "false";
          if (typeof val === "number") return String(val);
          return `'${String(val).replace(/'/g, "''")}'`;
        });
        const cols = colNames.join(", ");
        const vals = values.join(", ");
        const sql = `INSERT INTO ${table} (${cols}) VALUES (${vals})`;
        try { await client._sql(sql); } catch { /* skip duplicate/schema mismatch */ }
      }
      restored.push(table);
      totalRestored += rows.length;
    } catch { /* skip */ }
  }

  return { status: "ok", tables: restored, total_rows: totalRestored };
}

export async function ping(client: ClientLike): Promise<Record<string, unknown>> {
  return client._callWithResult("ping", []).then(
    () => ({ status: "ok" }),
    () => ({ status: "error" }),
  );
}

export async function checkEmbedderHealth(client: ClientLike): Promise<Record<string, unknown>> {
  try {
    const resp = await fetch(`${client.embedderUrl}/health`, {
      method: "GET",
      signal: AbortSignal.timeout(5_000),
    });
    if (resp.ok) {
      const data = await resp.json() as Record<string, unknown>;
      data.reachable = true;
      return data;
    }
    return { status: "error", code: resp.status, reachable: true };
  } catch (e) {
    return { status: "error", message: String(e), reachable: false };
  }
}

export async function health(client: ClientLike): Promise<Record<string, unknown>> {
  const dbCheck = await ping(client);
  const embCheck = await checkEmbedderHealth(client);
  const allOk = dbCheck.status === "ok" && embCheck.reachable === true;
  return { status: allOk ? "ok" : "degraded", database: dbCheck, embedder: embCheck };
}

export async function checkTantivyHealth(client: ClientLike): Promise<Record<string, unknown>> {
  const resp = await fetch(`${client.tantivyUrl}/health`, { signal: AbortSignal.timeout(5000) });
  if (!resp.ok) throw new Error(`tantivy health check failed: HTTP ${resp.status}`);
  return await resp.json();
}

export async function runMaintenance(client: ClientLike): Promise<void> {
  return client._call("run_maintenance", []);
}

export async function dedup(client: ClientLike, workspaceId: string): Promise<void> {
  return client._call("dedup_memories", [workspaceId]);
}

export async function suggestMerges(client: ClientLike, workspaceId: string, threshold?: number): Promise<void> {
  return client._call("suggest_merges", [workspaceId, threshold ?? 0.8]);
}

export async function approveMerge(client: ClientLike, suggestionId: string): Promise<void> {
  return client._call("approve_merge", [suggestionId]);
}

export async function rejectMerge(client: ClientLike, suggestionId: string): Promise<void> {
  return client._call("reject_merge", [suggestionId]);
}

export async function setMetricsCollector(client: ClientLike, collector: { record?: unknown; record_latency?: unknown; to_dict?: () => Record<string, unknown>; toDict?: () => Record<string, unknown> } | null): Promise<void> {
  client._metricsCollector = collector;
}

export function getMetrics(client: ClientLike): Record<string, unknown> | null {
  if (!client._metricsCollector) return null;
  const mc = client._metricsCollector;
  if (typeof mc.to_dict === "function") return mc.to_dict();
  if (typeof mc.toDict === "function") return mc.toDict();
  return null;
}
