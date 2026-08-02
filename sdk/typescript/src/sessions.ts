/**
 * Session lifecycle, steps, participants.
 */
import type { ClientLike, SessionStepRecord } from "./types";
import { sortByCreatedAsc } from "./helpers";

export async function createSession(client: ClientLike, workspaceId: string, name?: string): Promise<void> {
  return client._call("create_session", [workspaceId, name ?? ""]);
}

export async function joinSession(client: ClientLike, sessionId: string): Promise<void> {
  return client._call("join_session", [sessionId]);
}

export async function leaveSession(client: ClientLike, sessionId: string): Promise<void> {
  return client._call("leave_session", [sessionId]);
}

export async function addAgentStep(client: ClientLike, sessionId: string, step: string, stepType?: string): Promise<void> {
  return client._call("add_agent_step", [sessionId, step, stepType ?? "action"]);
}

export async function getSessionSteps(client: ClientLike, sessionId: string): Promise<SessionStepRecord[]> {
  return (await client._sqlExec(
    "SELECT * FROM session_step WHERE session_id = :sid",
    { sid: sessionId },
  )) as SessionStepRecord[];
}

export async function getPeerSessions(client: ClientLike, peerId: string): Promise<Record<string, unknown>[]> {
  const parts = await client._sqlExec(
    "SELECT session_id, role, joined_at FROM session_participant WHERE peer_id = :pid",
    { pid: peerId },
  );
  const results: Record<string, unknown>[] = [];
  for (const sp of parts) {
    const sessions = await client._sqlExec("SELECT * FROM session WHERE id = :sid", { sid: sp.session_id as string });
    for (const s of sessions) {
      s.role = sp.role ?? "";
      s.joined_at = sp.joined_at ?? 0;
      results.push(s);
    }
  }
  results.sort((a, b) => ((b.joined_at ?? 0) as number) - ((a.joined_at ?? 0) as number));
  return results;
}

export async function getSessionMessages(client: ClientLike, sessionId: string): Promise<Record<string, unknown>[]> {
  const rows = await client._sqlExec("SELECT * FROM message WHERE session_id = :sid", { sid: sessionId });
  return sortByCreatedAsc(rows);
}

export async function searchSessionsSemantic(client: ClientLike, query: string, limit?: number): Promise<Record<string, unknown>[]> {
  const emb = await client._embed(query);
  if (emb.length === 0) return [];
  const embJson = JSON.stringify(emb);
  await client._call("search_sessions_semantic", [embJson, limit ?? 10]);
  const qhash = `sessions:${limit ?? 10}`;
  const rows = await client._query("session_search_result", "", { query_hash: qhash });
  rows.sort((a, b) => ((b.score ?? 0) as number) - ((a.score ?? 0) as number));
  return rows.slice(0, limit ?? 10);
}

// ---------------------------------------------------------------------------
// Tours
// ---------------------------------------------------------------------------

export async function createTour(client: ClientLike, workspaceId: string, name: string, description?: string): Promise<void> {
  return client._call("create_tour", [workspaceId, name, description ?? ""]);
}

export async function addTourStop(client: ClientLike, tourId: string, nodeId: string, sequence: number): Promise<void> {
  return client._call("add_tour_stop", [tourId, nodeId, sequence]);
}

export async function removeTourStop(client: ClientLike, tourStopId: string): Promise<void> {
  return client._call("remove_tour_stop", [tourStopId]);
}

export async function deleteTourStop(client: ClientLike, stopId: string): Promise<void> {
  return removeTourStop(client, stopId);
}

export async function deleteTour(client: ClientLike, tourId: string): Promise<void> {
  return client._call("delete_tour", [tourId]);
}
