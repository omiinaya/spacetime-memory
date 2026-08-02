/**
 * Document management.
 */
import type { ClientLike } from "./types";

export async function createDocument(client: ClientLike, workspaceId: string, title: string, content?: string, contentType?: string, filePath?: string, sourceUrl?: string, metadata?: Record<string, unknown>): Promise<void> {
  const metaJson = metadata ? JSON.stringify(metadata) : "{}";
  return client._call("create_document", [workspaceId, title, content ?? "", contentType ?? "text", filePath ?? "", sourceUrl ?? "", metaJson]);
}

export async function getDocument(client: ClientLike, docId: string): Promise<Record<string, unknown> | null> {
  const rows = await client._sqlExec("SELECT * FROM document WHERE id = :did", { did: docId });
  return rows.length > 0 ? rows[0] : null;
}

export async function listDocuments(client: ClientLike, workspaceId: string): Promise<Record<string, unknown>[]> {
  return client._sqlExec("SELECT * FROM document WHERE workspace_id = :ws", { ws: workspaceId });
}

export async function getDocumentChunks(client: ClientLike, docId: string): Promise<Record<string, unknown>[]> {
  const rows = await client._sqlExec("SELECT * FROM document_chunk WHERE document_id = :did", { did: docId });
  return (rows as Record<string, unknown>[]).sort((a, b) => Number(a.chunk_index ?? 0) - Number(b.chunk_index ?? 0));
}

export async function deleteDocument(client: ClientLike, docId: string): Promise<void> {
  return client._call("delete_document", [docId]);
}

export async function searchDocuments(client: ClientLike, workspaceId: string, query: string, limit = 10): Promise<Record<string, unknown>[]> {
  await client._call("search_documents", [workspaceId, query, limit]);
  return await client._sqlExec("SELECT * FROM directory_content_result WHERE workspace_id = :ws", { ws: workspaceId });
}

export async function updateDocument(client: ClientLike, documentId: string, title = "", content = "", metadata: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  return await client._call("update_document", [documentId, title, content, metadata]);
}
