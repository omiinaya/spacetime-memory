/**
 * MemFS — virtual filesystem for SpacetimeDB-backed hierarchical storage.
 *
 * Provides a virtual filesystem with files, directories, and mount points
 * that bridge to other SpacetimeDB data sources (memories, notes, sessions).
 *
 * Wraps the corresponding SpacetimeDB reducers defined in
 * ``server/spacetimedb/src/memfs.rs``.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

/** A virtual file or directory entry. */
export interface MemfsEntry {
  id: string;
  workspace_id: string;
  parent_id: string;
  name: string;
  path: string;
  entry_type: "file" | "directory";
  mime_type: string;
  data: string;
  size: number;
  is_mounted: boolean;
  mount_source: string;
  created_at: number;
  updated_at: number;
}

/** A mount point mapping a virtual path to a SpacetimeDB data source. */
export interface MemfsMount {
  id: string;
  workspace_id: string;
  mount_path: string;
  source_type: "workspace" | "memory" | "note" | "session" | "custom";
  source_config: string;
  filter_query: string;
  created_at: number;
}

/** A result row from the memfs_result table (used for query responses). */
export interface MemfsResult {
  id: string;
  data: string;
  created_at: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Parse a memfs_result row into its typed representation.
 * The "data" field contains a JSON string of the entry or mount.
 */
function parseMemfsResultRow(row: Record<string, unknown>): Record<string, any> {
  const data = row.data as string | undefined;
  if (data) {
    try {
      return JSON.parse(data) as Record<string, any>;
    } catch {
      return row;
    }
  }
  return row;
}

/**
 * Query the memfs_result table after a reducer call, filtering out
 * internal count/status rows, and return parsed entries or mounts.
 */
async function readMemfsResults(
  client: ClientLike,
  workspaceId: string,
  excludePattern: string,
): Promise<Record<string, any>[]> {
  const rows = await client._sqlExec(
    `SELECT * FROM memfs_result WHERE id NOT LIKE :excl`,
    { ws: workspaceId, excl: excludePattern },
    { like: true },
  );
  return rows.map(parseMemfsResultRow);
}

// ---------------------------------------------------------------------------
// Entry operations
// ---------------------------------------------------------------------------

/**
 * Create a file or directory entry.
 */
export async function createMemfsEntry(
  client: ClientLike,
  workspaceId: string,
  parentId: string,
  name: string,
  entryType: "file" | "directory",
  mimeType: string = "",
  data: string = "",
): Promise<Record<string, any>> {
  return client._call("create_memfs_entry", [
    workspaceId,
    parentId,
    name,
    entryType,
    mimeType,
    data,
  ]) as Promise<Record<string, any>>;
}

/**
 * Delete an entry (recursive for directories).
 */
export async function deleteMemfsEntry(
  client: ClientLike,
  workspaceId: string,
  entryId: string,
): Promise<Record<string, any>> {
  return client._call("delete_memfs_entry", [
    workspaceId,
    entryId,
  ]) as Promise<Record<string, any>>;
}

/**
 * Update an entry's name, data, and/or MIME type.
 * Pass empty strings for fields that should remain unchanged.
 */
export async function updateMemfsEntry(
  client: ClientLike,
  workspaceId: string,
  entryId: string,
  name: string = "",
  data: string = "",
  mimeType: string = "",
): Promise<Record<string, any>> {
  return client._call("update_memfs_entry", [
    workspaceId,
    entryId,
    name,
    data,
    mimeType,
  ]) as Promise<Record<string, any>>;
}

/**
 * List children of a directory.
 * Calls the reducer then reads results from memfs_result.
 */
export async function getMemfsEntries(
  client: ClientLike,
  workspaceId: string,
  parentId: string,
): Promise<Record<string, any>[]> {
  await client._call("get_memfs_entries", [workspaceId, parentId]);
  return readMemfsResults(client, workspaceId, `_count_${parentId}%`);
}

/**
 * Look up an entry by its full virtual path.
 * Returns the entry, or null if not found.
 */
export async function getMemfsEntryByPath(
  client: ClientLike,
  workspaceId: string,
  path: string,
): Promise<Record<string, any> | null> {
  await client._call("get_memfs_entry_by_path", [workspaceId, path]);
  const rows = await client._sqlExec(
    `SELECT * FROM memfs_result WHERE id LIKE :pattern`,
    { ws: workspaceId, pattern: "found_%" },
    { like: true },
  );
  if (rows.length === 0) return null;
  return parseMemfsResultRow(rows[0]);
}

/**
 * Read a file's content.
 * Returns the file entry with data, or null if not found.
 */
export async function readMemfsFile(
  client: ClientLike,
  workspaceId: string,
  entryId: string,
): Promise<Record<string, any> | null> {
  await client._call("read_memfs_file", [workspaceId, entryId]);
  const rows = await client._sqlExec(
    `SELECT * FROM memfs_result WHERE id = :id`,
    { ws: workspaceId, id: `read_${entryId}` },
  );
  if (rows.length === 0) return null;
  return parseMemfsResultRow(rows[0]);
}

/**
 * Write data to an existing file entry.
 */
export async function writeMemfsFile(
  client: ClientLike,
  workspaceId: string,
  entryId: string,
  data: string,
): Promise<Record<string, any>> {
  return client._call("write_memfs_file", [
    workspaceId,
    entryId,
    data,
  ]) as Promise<Record<string, any>>;
}

// ---------------------------------------------------------------------------
// Mount operations
// ---------------------------------------------------------------------------

/**
 * Create a mount point.
 *
 * Mount points map virtual paths to SpacetimeDB data sources (memories,
 * notes, sessions, etc.) so that listing the directory returns records
 * from the mounted source.
 *
 * @param sourceType One of "workspace", "memory", "note", "session", "custom".
 * @param sourceConfig JSON object or string for the source configuration.
 * @param filterQuery Optional query filter.
 */
export async function createMemfsMount(
  client: ClientLike,
  workspaceId: string,
  mountPath: string,
  sourceType: string,
  sourceConfig: Record<string, unknown> | string = "",
  filterQuery: string = "",
): Promise<Record<string, any>> {
  const configJson = typeof sourceConfig === "string"
    ? sourceConfig
    : JSON.stringify(sourceConfig);
  return client._call("create_memfs_mount", [
    workspaceId,
    mountPath,
    sourceType,
    configJson,
    filterQuery,
  ]) as Promise<Record<string, any>>;
}

/**
 * Remove a mount point.
 */
export async function deleteMemfsMount(
  client: ClientLike,
  workspaceId: string,
  mountId: string,
): Promise<Record<string, any>> {
  return client._call("delete_memfs_mount", [
    workspaceId,
    mountId,
  ]) as Promise<Record<string, any>>;
}

/**
 * List all mount points for a workspace.
 */
export async function getMemfsMounts(
  client: ClientLike,
  workspaceId: string,
): Promise<Record<string, any>[]> {
  await client._call("get_memfs_mounts", [workspaceId]);
  return readMemfsResults(client, workspaceId, `_mount_count_${workspaceId}%`);
}

// ---------------------------------------------------------------------------
// Convenience functions
// ---------------------------------------------------------------------------

/**
 * Mount a workspace at a virtual path.
 * Shortcut for createMemfsMount with sourceType="workspace".
 */
export async function mountWorkspace(
  client: ClientLike,
  workspaceId: string,
  mountPath: string = "/workspace",
  filterQuery: string = "",
): Promise<Record<string, any>> {
  return createMemfsMount(client, workspaceId, mountPath, "workspace", {}, filterQuery);
}

/**
 * Mount memories at a virtual path.
 * Shortcut for createMemfsMount with sourceType="memory".
 */
export async function mountMemories(
  client: ClientLike,
  workspaceId: string,
  mountPath: string = "/memories",
  filterQuery: string = "",
): Promise<Record<string, any>> {
  return createMemfsMount(client, workspaceId, mountPath, "memory", {}, filterQuery);
}
