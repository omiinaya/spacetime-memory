# TypeScript Workspaces API

Workspace lifecycle, visibility, members, encryption, directories, context packs, connectors, and compounder operations.

```typescript
import { createWorkspace, listWorkspaces, grantSpaceAccess } from "spacetime-memory/workspaces";

await createWorkspace(client, "research", "Caroline's research notes");
await grantSpaceAccess(client, wsId, peerId, "editor");
```

## Lifecycle

### `createWorkspace(client, name, description?)`

Creates a workspace.

### `listWorkspaces(client)`

Lists workspaces accessible to the identity.

### `updateWorkspace(client, id, name, description)` / `deleteWorkspace(client, workspaceId)`

Updates or deletes a workspace.

### `setWorkspaceVisibility(client, workspaceId, isPublic)`

Toggles workspace public/private.

## Members & Context

### `getWorkspaceContext(client, workspaceId)` / `setWorkspaceContext(client, workspaceId, context)`

Reads/sets workspace-level context.

### `listSpaceMembers(client, workspaceId)`

Returns `SpaceMemberRecord[]`.

### `grantSpaceAccess(client, workspaceId, peerId, permission)` / `revokeSpaceAccess(client, workspaceId, peerId)`

Grants `"owner" | "editor" | "viewer"` access (owner/admin only) or revokes it.

## Encryption

### `initWorkspaceEncryption(client, workspaceId)` / `setWorkspaceEncryptionEnabled(client, workspaceId, enabled)`

Initializes / toggles encryption-at-rest.

### `rotateWorkspaceEncryptionKey(client, workspaceId)` / `encryptExistingMemories(client, workspaceId)`

Rotates the key / encrypts existing rows.

### `getDecryptedMemory(client, memoryId)`

Reads decrypted memory content through the scoped `decrypted_memory_result` path.

## Decay

### `getDecayConfig(client, workspaceId)` / `setDecayModel(client, workspaceId, modelType, halfLife, maxStrength)`

Reads / configures memory decay (strength half-life model).

## Directories & Context Packs

### `listDirectory(client, directoryId)` / `traverseDirectory(client, workspaceId, rootDirectoryId)` / `getDirectory(client, workspaceId, pathOrId)` / `createDirectory(client, workspaceId, name, path, parentId?, description?)`

Directory tree navigation and creation.

### `linkMemoryToDirectory(client, directoryId, memoryId, workspaceId)` / `unlinkMemoryFromDirectory(client, directoryId, memoryId)`

Links memory rows into directories.

### `listContextPacks(client, workspaceId)` / `listContextEntries(client, packId)` / `listContextDeltas(client, previousPackId)` / `storeContextPack(client, workspaceId, name, memoryIds, contextText?)`

Context-pack diffing (delta-based context compression).

## Connectors

### `registerConnector(client, name, connectorType, configJson, workspaceId, scheduleSecs)` / `updateConnector(...)` / `deleteConnector(client, id)`

Registers / updates / removes ingestion connectors.

## Compounder

### `crossLink(client, workspaceId, limit?)` / `suggestConnections(client, workspaceId)` / `lintWorkspace(client, workspaceId)` / `generateOverview(client, workspaceId)`

Auto-linking, connection suggestions, lint, and overview generation.

### `exportWorkspace(client, workspaceId)` / `exportWorkspaceJson(client, workspaceId, opts?)`

Exports the workspace (markdown string or JSON with `includeSystemNotes`/`outputPath` options).

### `storeAnswer(client, query, answer, opts?)`

Persists an LLM synthesis as a wiki page (`workspaceId`, `title`, `sourceMemoryIds`, `embed` options).

---

See also: [client](client.md), [compounder](compounder.md), [types](types.md)
