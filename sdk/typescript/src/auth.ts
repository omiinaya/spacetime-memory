/**
 * Auth / Account operations.
 */
import type { ClientLike } from "./types";

export async function register(client: ClientLike, username: string, displayName: string = "", password: string = ""): Promise<void> {
  return client._call("register", [username, displayName, password]);
}

export async function login(client: ClientLike, username: string, password: string): Promise<void> {
  return client._call("login", [username, password]);
}

export async function logout(client: ClientLike): Promise<void> {
  return client._call("logout", []);
}

export async function updateAccount(client: ClientLike, displayName: string = "", currentPassword: string = "", newPassword: string = ""): Promise<void> {
  return client._call("update_account", [displayName, currentPassword, newPassword]);
}

export async function deactivateAccount(client: ClientLike, password: string): Promise<void> {
  return client._call("deactivate_account", [password]);
}

export async function createApiKey(client: ClientLike, workspaceId: string, name: string, permissions?: string): Promise<Record<string, unknown>> {
  const raw = new Uint8Array(32);
  crypto.getRandomValues(raw);
  const hex = Array.from(raw).map(b => b.toString(16).padStart(2, "0")).join("");
  const apiKey = "sk-" + hex;
  const encoder = new TextEncoder();
  const hashBuffer = await crypto.subtle.digest("SHA-256", encoder.encode(apiKey));
  const keyHash = Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, "0")).join("");

  const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map(b => b.toString(16).padStart(2, "0")).join("");

  const perms = permissions ?? '["read"]';

  await client._call("create_api_key", [workspaceId, name, perms, keyHash, requestId]);

  const rows = await client._query("api_key_result", "", { request_id: requestId, operation: "create" });
  const keyId = (rows[0]?.api_key_id as string) ?? "";

  return { status: "ok", api_key: apiKey, id: keyId, note: "Save this key — it will not be shown again." };
}

export async function deactivateApiKey(client: ClientLike, keyId: string): Promise<void> {
  return client._call("deactivate_api_key", [keyId]);
}

export async function listApiKeys(client: ClientLike, workspaceId: string): Promise<Record<string, unknown>[]> {
  await client._call("list_api_keys", [workspaceId]);
  const rows = await client._query("api_key_result", "", { request_id: workspaceId });
  return rows.sort((a, b) => Number(b.created_at ?? 0) - Number(a.created_at ?? 0));
}

export async function verifyApiKey(client: ClientLike, rawKey: string): Promise<Record<string, unknown>> {
  try {
    await client._call("verify_api_key", [rawKey]);
  } catch (e: unknown) {
    return { valid: false, error: String(e instanceof Error ? e.message : e) };
  }
  const rows = await client._sql(
    "SELECT api_key_id, workspace_id, name, permissions, scope, is_active, created_at, last_used_at, verified_at FROM api_key_verification_result"
  );
  (rows as Record<string, unknown>[]).sort((a, b) => Number(b.verified_at ?? 0) - Number(a.verified_at ?? 0));
  if (!rows.length) return { valid: false, error: "Key not found or deactivated" };
  const row = rows[0];
  return { valid: true, ...row };
}

export async function updateApiKey(client: ClientLike, keyId: string, name = "", permissions = "", scope = "", isActive = true): Promise<Record<string, unknown>> {
  return await client._call("update_api_key", [keyId, name, permissions, scope, isActive]);
}
