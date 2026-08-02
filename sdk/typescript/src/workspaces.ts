/**
 * Workspace CRUD, members, permissions.
 */
import type { ClientLike, Workspace, SpaceMemberRecord, PeerRecord, CrossLinkResult, LintResult, StoreAnswerResult, OverviewResult, KGNodeRecord } from "./types";
import { sortByCreatedDesc } from "./helpers";

export async function createWorkspace(client: ClientLike, name: string, description?: string): Promise<void> {
  return client._call("create_workspace", [name, description ?? ""]);
}

export async function listWorkspaces(client: ClientLike): Promise<Workspace[]> {
  return (await client._sql("SELECT * FROM workspace")) as Workspace[];
}

export async function updateWorkspace(client: ClientLike, id: string, name: string, description: string): Promise<void> {
  return client._call("update_workspace", [id, name, description]);
}

export async function deleteWorkspace(client: ClientLike, workspaceId: string): Promise<void> {
  return client._call("delete_workspace", [workspaceId]);
}

export async function setWorkspaceVisibility(client: ClientLike, workspaceId: string, isPublic: boolean): Promise<void> {
  return client._call("set_workspace_visibility", [workspaceId, isPublic]);
}

export async function getWorkspaceContext(client: ClientLike, workspaceId: string): Promise<Record<string, unknown> | null> {
  await client._call("get_workspace_context", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM workspace_context_result WHERE workspace_id = :wsid",
    { wsid: workspaceId },
  );
  return rows.length > 0 ? rows[0] : null;
}

export async function listSpaceMembers(client: ClientLike, workspaceId: string): Promise<SpaceMemberRecord[]> {
  return (await client._sqlExec(
    "SELECT * FROM space_member WHERE workspace_id = :ws",
    { ws: workspaceId },
  )) as SpaceMemberRecord[];
}

export async function grantSpaceAccess(client: ClientLike, workspaceId: string, peerId: string, permission: string): Promise<void> {
  return client._call("grant_space_access", [workspaceId, peerId, permission]);
}

export async function revokeSpaceAccess(client: ClientLike, workspaceId: string, peerId: string): Promise<void> {
  return client._call("revoke_space_access", [workspaceId, peerId]);
}

export async function setWorkspaceContext(client: ClientLike, workspaceId: string, context: string): Promise<void> {
  return client._call("set_workspace_context", [workspaceId, context]);
}

export async function getDecayConfig(client: ClientLike, workspaceId: string): Promise<Record<string, unknown> | null> {
  const rows = await client._sqlExec(
    "SELECT * FROM workspace_config WHERE id = :wsid",
    { wsid: workspaceId },
  );
  return rows.length > 0 ? rows[0] : null;
}

export async function setDecayModel(client: ClientLike, workspaceId: string, modelType: string, halfLife: number, maxStrength: number): Promise<void> {
  return client._call("set_decay_model", [workspaceId, modelType, halfLife, maxStrength]);
}

export async function initWorkspaceEncryption(client: ClientLike, workspaceId: string): Promise<Record<string, unknown>> {
  return await client._call("init_workspace_encryption", [workspaceId]);
}

export async function setWorkspaceEncryptionEnabled(client: ClientLike, workspaceId: string, enabled: boolean): Promise<Record<string, unknown>> {
  return await client._call("set_workspace_encryption_enabled", [workspaceId, enabled]);
}

export async function rotateWorkspaceEncryptionKey(client: ClientLike, workspaceId: string): Promise<Record<string, unknown>> {
  return await client._call("rotate_workspace_encryption_key", [workspaceId]);
}

export async function encryptExistingMemories(client: ClientLike, workspaceId: string): Promise<Record<string, unknown>> {
  return await client._call("encrypt_existing_memories", [workspaceId]);
}

export async function getDecryptedMemory(client: ClientLike, memoryId: string): Promise<Record<string, unknown> | null> {
  await client._call("get_decrypted_memory", [memoryId]);
  const rows = await client._query("decrypted_memory_result");
  return rows.length ? rows[0] : null;
}

// ---------------------------------------------------------------------------
// Directory operations
// ---------------------------------------------------------------------------

export async function listDirectory(client: ClientLike, directoryId: string): Promise<Record<string, unknown>[]> {
  await client._call("get_children", [directoryId, true]);
  return client._sqlExec(
    "SELECT * FROM directory_result WHERE query_hash = :qid",
    { qid: directoryId },
  );
}

export async function traverseDirectory(client: ClientLike, workspaceId: string, rootDirectoryId: string): Promise<Record<string, unknown>[]> {
  await client._call("traverse_recursive", [workspaceId, rootDirectoryId]);
  return client._sqlExec(
    "SELECT * FROM directory_result WHERE query_hash = :qid",
    { qid: rootDirectoryId },
  );
}

export async function getDirectory(client: ClientLike, workspaceId: string, pathOrId: string): Promise<Record<string, unknown>[]> {
  await client._call("get_directory", [workspaceId, pathOrId]);
  return client._sqlExec(
    "SELECT * FROM directory_result WHERE workspace_id = :ws",
    { ws: workspaceId },
  );
}

export async function createDirectory(client: ClientLike, workspaceId: string, name: string, path: string, parentId?: string, description?: string): Promise<void> {
  return client._call("create_directory", [workspaceId, name, path, parentId ?? "", description ?? ""]);
}

export async function linkMemoryToDirectory(client: ClientLike, directoryId: string, memoryId: string, workspaceId: string): Promise<void> {
  return client._call("link_memory_to_directory", [directoryId, memoryId, workspaceId]);
}

export async function unlinkMemoryFromDirectory(client: ClientLike, directoryId: string, memoryId: string): Promise<void> {
  return client._call("unlink_memory_from_directory", [directoryId, memoryId]);
}

// ---------------------------------------------------------------------------
// Context packs
// ---------------------------------------------------------------------------

export async function listContextPacks(client: ClientLike, workspaceId: string): Promise<Record<string, unknown>[]> {
  return client._sql(`SELECT * FROM context_pack WHERE workspace_id = '${workspaceId}'`);
}

export async function listContextEntries(client: ClientLike, packId: string): Promise<Record<string, unknown>[]> {
  return client._sql(`SELECT * FROM context_entry WHERE pack_id = '${packId}'`);
}

export async function listContextDeltas(client: ClientLike, previousPackId: string): Promise<Record<string, unknown>[]> {
  return client._sql(`SELECT * FROM context_delta WHERE previous_pack_id = '${previousPackId}'`);
}

export async function storeContextPack(client: ClientLike, workspaceId: string, name: string, memoryIds: string[], contextText?: string): Promise<void> {
  await client._call("store_context_pack", [workspaceId, name, JSON.stringify(memoryIds), contextText ?? ""]);
}

// ---------------------------------------------------------------------------
// Connector configuration
// ---------------------------------------------------------------------------

export async function registerConnector(client: ClientLike, name: string, connectorType: string, configJson: string, workspaceId: string, scheduleSecs: number): Promise<void> {
  return client._call("register_connector", [name, connectorType, configJson, workspaceId, scheduleSecs]);
}

export async function updateConnector(client: ClientLike, id: string, name: string, connectorType: string, configJson: string, workspaceId: string, scheduleSecs: number, isActive: boolean): Promise<void> {
  return client._call("update_connector", [id, name, connectorType, configJson, workspaceId, scheduleSecs, isActive]);
}

export async function deleteConnector(client: ClientLike, id: string): Promise<void> {
  return client._call("delete_connector", [id]);
}

// ---------------------------------------------------------------------------
// Compounder / Wiki operations (on Client)
// ---------------------------------------------------------------------------

export async function crossLink(client: ClientLike, workspaceId: string, limit?: number): Promise<CrossLinkResult> {
  const memories = await client._sqlExec(
    "SELECT id, content FROM memory WHERE workspace_id = :ws AND is_active = true",
    { ws: workspaceId },
  );
  sortByCreatedDesc(memories as Record<string, unknown>[]);

  let linksCreated = 0;
  let pairsChecked = 0;

  for (const mem of memories) {
    const mid = mem.id as string;
    const content = mem.content as string;
    if (!content || content.length < 20) continue;

    const similarRows = await client._sqlExec(
      "SELECT id, content FROM memory WHERE workspace_id = :ws AND id != :mid",
      { ws: workspaceId, mid },
    );
    const q = content.slice(0, 30).toLowerCase();
    const similar = similarRows.filter((r: Record<string, unknown>) =>
      String(r.content ?? "").toLowerCase().includes(q),
    ).slice(0, 5);

    for (const sim of similar) {
      pairsChecked++;
      const existing = await client._sqlExec(
        "SELECT id FROM kg_edge WHERE source_node_id = :mid AND target_node_id = :sid",
        { mid, sid: sim.id as string },
      );
      if (existing.length === 0) {
        try {
          await client._call("create_edge", [workspaceId, mid, sim.id as string, "related_to", 0.7, "EXTRACTED", "{}"]);
          linksCreated++;
        } catch { /* ignore */ }
      }
    }
  }

  return { linksCreated, pairsChecked };
}

export async function suggestConnections(client: ClientLike, workspaceId: string): Promise<KGNodeRecord[]> {
  await client._call("compute_community_hierarchy", [workspaceId]);
  return (await client._sqlExec(
    "SELECT * FROM kg_node WHERE workspace_id = :ws",
    { ws: workspaceId },
  )) as KGNodeRecord[];
}

export async function lintWorkspace(client: ClientLike, workspaceId: string): Promise<LintResult> {
  const allNodes = await client._sqlExec("SELECT id FROM kg_node WHERE workspace_id = :ws", { ws: workspaceId });
  let orphans = 0;
  for (const node of allNodes) {
    const edges = await client._sqlExec(
      "SELECT id FROM kg_edge WHERE source_node_id = :nid OR target_node_id = :nid LIMIT 1",
      { nid: node.id as string },
    );
    if (edges.length === 0) orphans++;
  }
  return { orphans, total: allNodes.length };
}

export async function generateOverview(client: ClientLike, workspaceId: string): Promise<OverviewResult> {
  const params = { ws: workspaceId };
  const [memories, kgNodes, kgEdges, notes] = await Promise.all([
    client._sqlExec("SELECT COUNT(*) as c FROM memory WHERE workspace_id = :ws", params),
    client._sqlExec("SELECT COUNT(*) as c FROM kg_node WHERE workspace_id = :ws", params),
    client._sqlExec("SELECT COUNT(*) as c FROM kg_edge WHERE workspace_id = :ws", params),
    client._sqlExec("SELECT COUNT(*) as c FROM note WHERE workspace_id = :ws", params),
  ]);

  return {
    workspaceId,
    memories: (memories[0]?.c ?? 0) as number,
    kgNodes: (kgNodes[0]?.c ?? 0) as number,
    kgEdges: (kgEdges[0]?.c ?? 0) as number,
    notes: (notes[0]?.c ?? 0) as number,
  };
}

export async function exportWorkspace(client: ClientLike, workspaceId: string): Promise<string> {
  const notes = await client._sqlExec(
    "SELECT title, content FROM note WHERE workspace_id = :ws",
    { ws: workspaceId },
  );
  return notes.map((n) => `# ${n.title}\n\n${n.content ?? ""}` as string).join("\n\n---\n\n");
}

export async function exportWorkspaceJson(client: ClientLike, workspaceId: string, opts?: { includeSystemNotes?: boolean; outputPath?: string }): Promise<Record<string, unknown>> {
  const wsScopedTables: string[] = [
    "memory", "memory_version", "kg_node", "kg_edge", "kg_community",
    "note", "session", "session_participant", "message", "profile", "fact",
    "tour", "tour_stop", "directory", "directory_link", "backlink",
    "merge_suggestion", "context_pack", "context_entry", "context_delta",
    "document", "document_chunk", "entity_extraction", "entity_link", "change_event",
  ];

  const manifest: Record<string, unknown[]> = {};
  const backedUp: string[] = [];
  let totalRows = 0;

  for (const table of wsScopedTables) {
    try {
      let rows: Record<string, unknown>[];
      if (table === "note" && !opts?.includeSystemNotes) {
        const allRows = await client._query(table, workspaceId);
        rows = allRows.filter((r) => !(r.title as string ?? "").startsWith("_"));
      } else {
        rows = await client._query(table, workspaceId);
      }
      manifest[table] = rows;
      totalRows += rows.length;
      backedUp.push(table);
    } catch { manifest[table] = []; }
  }

  try {
    const ws = await client._sqlExec("SELECT * FROM workspace WHERE id = :ws LIMIT 1", { ws: workspaceId });
    if (ws.length > 0) { manifest["workspace"] = [ws[0] as Record<string, unknown>]; backedUp.push("workspace"); totalRows += 1; }
  } catch { manifest["workspace"] = []; }

  const payload = {
    version: "0.3.0", exported_at: new Date().toISOString(), workspace_id: workspaceId,
    tables: manifest, stats: { table_count: backedUp.length, total_rows: totalRows },
  };

  const json = JSON.stringify(payload, null, 2);
  const finalPath = opts?.outputPath;
  if (finalPath && typeof process !== "undefined" && typeof process.version === "string") {
    const fs = await import("fs");
    fs.writeFileSync(finalPath, json, "utf-8");
  }

  return { status: "ok", workspace_id: workspaceId, tables: backedUp, total_rows: totalRows, json };
}

export async function storeAnswer(client: ClientLike, query: string, answer: string, opts?: { workspaceId?: string; title?: string; sourceMemoryIds?: string[]; embed?: boolean }): Promise<StoreAnswerResult> {
  const wsId = opts?.workspaceId ?? "default";
  const title = opts?.title ?? `Q: ${query.slice(0, 60)}`;

  if (!answer.trim()) return { note: { id: '', title: '' }, entities: [], links: 0 };

  await client._call("create_note", [wsId, title, answer, opts?.embed ?? true]);

  const notes = await client._sqlExec(
    "SELECT id FROM note WHERE workspace_id = :ws AND title = :title",
    { ws: wsId, title },
  );
  sortByCreatedDesc(notes as Record<string, unknown>[]);
  if (notes.length === 0) return { note: { id: '', title: '' }, entities: [], links: 0 };
  const noteId = notes[0].id;

  const entityRegex = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b/g;
  const matches = answer.match(entityRegex) ?? [];
  const seen = new Set<string>();
  const entities: string[] = [];
  for (const m of matches) {
    const clean = m.trim();
    if (clean.length < 3 || clean.length > 60) continue;
    if (seen.has(clean.toLowerCase())) continue;
    seen.add(clean.toLowerCase());
    entities.push(clean);
  }

  let links = 0;
  for (const entity of entities.slice(0, 10)) {
    try {
      await client._call("create_node", [wsId, entity, "concept", "", "{}"]);
      const nodes = await client._sqlExec(
        "SELECT id FROM kg_node WHERE workspace_id = :ws AND label = :label",
        { ws: wsId, label: entity },
      );
      if (nodes.length > 0) {
        await client._call("create_edge", [wsId, nodes[nodes.length - 1].id, noteId, "informed_by", 1.0, "EXTRACTED", "{}"]);
        links++;
      }
    } catch { /* ignore */ }
  }

  const sourceIds = opts?.sourceMemoryIds ?? [];
  for (const sid of sourceIds) {
    try { await client._call("create_edge", [wsId, sid, noteId, "informed_by", 0.8, "EXTRACTED", "{}"]); } catch { /* ignore */ }
  }

  return { note: { id: noteId, title }, entities, links };
}
