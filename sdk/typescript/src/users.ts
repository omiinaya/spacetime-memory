/**
 * User management.
 */
import type { ClientLike } from "./types";

export async function addUser(client: ClientLike, userId: string, email = "", firstName = "", lastName = "", metadataJson = ""): Promise<Record<string, unknown>> {
  return await client._call("add_user", [userId, email, firstName, lastName, metadataJson]);
}

export async function getUser(client: ClientLike, userId: string): Promise<Record<string, unknown>> {
  await client._call("get_user", [userId]);
  const rows = await client._query("user_get_result", "", { id: `get_user:${userId}` });
  if (!rows.length) throw new Error(`User '${userId}' not found`);
  return rows[0];
}

export async function updateUser(client: ClientLike, userId: string, email = "", firstName = "", lastName = "", metadataJson = ""): Promise<Record<string, unknown>> {
  return await client._call("update_user", [userId, email, firstName, lastName, metadataJson]);
}

export async function deleteUser(client: ClientLike, userId: string): Promise<Record<string, unknown>> {
  return await client._call("delete_user", [userId]);
}

export async function listUsers(client: ClientLike): Promise<Record<string, unknown>[]> {
  await client._call("list_users", []);
  const rows = await client._query("user_get_result");
  return rows.filter((r: Record<string, unknown>) => String(r.id ?? "").startsWith("list_users:"));
}

export async function getUserSessions(client: ClientLike, userId: string): Promise<Record<string, unknown>[]> {
  const queryId = `user_sessions:${userId}`;
  await client._call("get_user_sessions", [userId]);
  return await client._query("user_session_result", "", { query_id: queryId });
}
