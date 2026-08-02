/**
 * Profile queries.
 */
import type { ClientLike } from "./types";

export async function getProfileContext(client: ClientLike, peerId: string): Promise<Record<string, unknown> | null> {
  await client._call("get_profile_context", [peerId]);
  const rows = await client._sqlExec("SELECT * FROM profile_context_result WHERE peer_id = :pid", { pid: peerId });
  return rows.length > 0 ? rows[0] : null;
}

export async function addProfileFact(client: ClientLike, peerId: string, fact: string): Promise<void> {
  return client._call("add_profile_fact", [peerId, fact]);
}

export async function addDynamicContext(client: ClientLike, peerId: string, context: string): Promise<void> {
  return client._call("add_dynamic_context", [peerId, context]);
}

export async function getProfile(client: ClientLike, peerId: string): Promise<Record<string, unknown> | null> {
  const rows = await client._sqlExec("SELECT * FROM profile WHERE id = :pid", { pid: peerId });
  return rows.length > 0 ? rows[0] : null;
}

export async function listProfiles(client: ClientLike, workspaceId: string): Promise<Record<string, unknown>[]> {
  return client._sqlExec(
    "SELECT p.* FROM profile p INNER JOIN peer pr ON p.id = pr.id WHERE pr.workspace_id = :ws",
    { ws: workspaceId },
  );
}

export async function searchProfiles(client: ClientLike, workspaceId: string, query: string, limit?: number): Promise<Record<string, unknown>[]> {
  const profiles = await listProfiles(client, workspaceId);
  if (query) {
    const q = query.toLowerCase();
    return profiles
      .filter((r) => ((r.static_facts_json as string) ?? "").toLowerCase().includes(q) || ((r.dynamic_context_json as string) ?? "").toLowerCase().includes(q))
      .slice(0, limit ?? 20);
  }
  return profiles.slice(0, limit ?? 20);
}

export async function upsertProfile(client: ClientLike, peerId: string, staticFacts?: string, dynamicContext?: string, preferences?: string, tags?: string): Promise<void> {
  return client._call("upsert_profile", [peerId, staticFacts ?? "", dynamicContext ?? "", preferences ?? "", tags ?? ""]);
}
