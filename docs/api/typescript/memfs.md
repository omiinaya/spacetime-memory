# memfs

Source: `sdk/typescript/src/memfs.ts`

## API Reference

### createMemfsEntry

MemFS — virtual filesystem for SpacetimeDB-backed hierarchical storage.
Provides a virtual filesystem with files, directories, and mount points
that bridge to other SpacetimeDB data sources (memories, notes, sessions).
Wraps the corresponding SpacetimeDB reducers defined in
``server/spacetimedb/src/memfs.rs``.
/
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
Parse a memfs_result row into its typed representation.
The "data" field contains a JSON string of the entry or mount.
/
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
Query the memfs_result table after a reducer call, filtering out
internal count/status rows, and return parsed entries or mounts.
/
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
Create a file or directory entry.

---

### deleteMemfsEntry

Delete an entry (recursive for directories).

---

### updateMemfsEntry

Update an entry's name, data, and/or MIME type.
Pass empty strings for fields that should remain unchanged.

---

### getMemfsEntries

List children of a directory.
Calls the reducer then reads results from memfs_result.

---

### getMemfsEntryByPath

Look up an entry by its full virtual path.
Returns the entry, or null if not found.

---

### readMemfsFile

Read a file's content.
Returns the file entry with data, or null if not found.

---

### writeMemfsFile

Write data to an existing file entry.

---

### createMemfsMount

Create a mount point.
Mount points map virtual paths to SpacetimeDB data sources (memories,
notes, sessions, etc.) so that listing the directory returns records
from the mounted source.
@param sourceType One of "workspace", "memory", "note", "session", "custom".
@param sourceConfig JSON object or string for the source configuration.
@param filterQuery Optional query filter.

---

### deleteMemfsMount

Remove a mount point.

---

### getMemfsMounts

List all mount points for a workspace.

---

### mountWorkspace

Mount a workspace at a virtual path.
Shortcut for createMemfsMount with sourceType="workspace".

---

### mountMemories

Mount memories at a virtual path.
Shortcut for createMemfsMount with sourceType="memory".

---
