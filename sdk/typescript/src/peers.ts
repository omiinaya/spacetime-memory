/**
 * Peer management.
 */
import type { ClientLike, PeerRecord, FactRecord, AddFactOptions } from "./types";

export async function listPeers(client: ClientLike, workspaceId?: string): Promise<PeerRecord[]> {
  if (workspaceId) {
    return (await client._sqlExec("SELECT * FROM peer WHERE workspace_id = :ws", { ws: workspaceId })) as PeerRecord[];
  }
  return (await client._sqlExec("SELECT * FROM peer", {})) as PeerRecord[];
}

export async function getPeerReputation(client: ClientLike, peerId: string): Promise<Record<string, unknown> | null> {
  await client._call("get_peer_reputation", [peerId]);
  const rows = await client._sqlExec("SELECT * FROM peer_reputation_result WHERE peer_id = :pid", { pid: peerId });
  return rows.length > 0 ? rows[0] : null;
}

export async function addFact(client: ClientLike, workspaceId: string, peerId: string, content: string, opts?: AddFactOptions): Promise<void> {
  await client._call("add_fact", [workspaceId, peerId, content, opts?.factType ?? "", opts?.confidence ?? 0.8]);
}

export async function listFacts(client: ClientLike, workspaceId: string, peerId: string): Promise<FactRecord[]> {
  return (await client._sqlExec(
    "SELECT * FROM fact_result WHERE workspace_id = :ws AND peer_id = :pid",
    { ws: workspaceId, pid: peerId },
  )) as FactRecord[];
}

export async function deleteFact(client: ClientLike, factId: string): Promise<void> {
  return client._call("delete_fact", [factId]);
}

export async function updateFact(client: ClientLike, factId: string, content: string, confidence?: number): Promise<void> {
  await client._call("update_fact", [factId, content, confidence ?? 0.8]);
}

export async function searchFacts(client: ClientLike, workspaceId: string, query: string): Promise<FactRecord[]> {
  const rows = await client._sqlExec("SELECT * FROM fact WHERE workspace_id = :ws", { ws: workspaceId });
  const q = query.toLowerCase();
  return (rows as FactRecord[]).filter(r => String(r.content ?? "").toLowerCase().includes(q));
}
