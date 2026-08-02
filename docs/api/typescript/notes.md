# TypeScript Notes API

Wiki-style notes with backlinks and version history.

```typescript
import { createNote, getBacklinks } from "spacetime-memory/notes";

await createNote(client, "ws-1", "RLHF", "Reinforcement learning from human feedback...", { embed: true });
const links = await getBacklinks(client, noteId);
```

## CRUD

### `createNote(client, workspaceId, title, content, opts?)`

Creates a note. `opts` supports `{ note_date?, embed? }` — set `embed: true` to make it semantically searchable.

### `updateNote(client, noteId, title?, content?, embeddingJson?, expectedVersion?)`

Optimistic-concurrency note update (pass `expectedVersion` to detect conflicts).

### `deleteNote(client, noteId)` / `listNotes(client, workspaceId)` / `getNote(client, noteId)`

Note deletion/listing/reads.

## Lookups

### `getNoteByDate(client, noteDate)` / `getNoteByTitle(client, title)`

Indexed lookups by date or title.

### `getNoteHistory(client, noteId)`

Returns `note_revision` history.

## Linking

### `getBacklinks(client, noteId)` / `getOutgoingLinks(client, noteId)`

Wiki-link backlinks and outgoing links (from `note_backlink` / `note_block`).

---

See also: [documents](documents.md), [types](types.md)
