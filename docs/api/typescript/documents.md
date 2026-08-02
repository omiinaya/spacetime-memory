# TypeScript Documents API

Document management — long-form content with chunked embedding.

```typescript
import { createDocument, searchDocuments } from "spacetime-memory/documents";

await createDocument(client, "ws-1", "Research Notes", "Full text...", "text/plain");
const hits = await searchDocuments(client, "ws-1", "embedding recall");
```

## CRUD

### `createDocument(client, workspaceId, title, content?, contentType?, filePath?, sourceUrl?, metadata?)`

Creates a document row.

| Param | Type | Description |
|-------|------|-------------|
| `client` | `ClientLike` | Authenticated client |
| `workspaceId` | `string` | Workspace ID |
| `title` | `string` | Document title |
| `content` | `string` | Full text (chunked + embedded) |
| `contentType` | `string` | MIME type |
| `filePath` | `string` | Optional source path |
| `sourceUrl` | `string` | Optional source URL |
| `metadata` | `object` | Arbitrary metadata |

### `getDocument(client, docId)` / `listDocuments(client, workspaceId)` / `deleteDocument(client, docId)`

Basic document reads/deletion.

### `updateDocument(client, documentId, title?, content?, metadata?)`

Updates title/content/metadata.

## Chunks & Search

### `getDocumentChunks(client, docId)`

Returns embedded `doc_chunk` rows for a document.

### `searchDocuments(client, workspaceId, query, limit = 10)`

Semantic search over document chunks.

---

See also: [memories](memories.md), [notes](notes.md), [types](types.md)
