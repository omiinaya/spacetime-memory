# TypeScript Tags API

Tag CRUD, memory tagging, and tag-filtered search.

```typescript
import { createTag, tagMemory, searchByTags } from "spacetime-memory/tags";

const tagId = await createTag(client, "ws-1", "important", "#e11d48");
await tagMemory(client, tagId, memoryId);
```

## CRUD

### `createTag(client, workspaceId, name, color?)`

Creates a tag (default color `""`).

### `updateTag(client, tagId, name?, color?)`

Updates tag name/color (defaults `""` / `"#808080"`).

### `deleteTag(client, tagId)`

Deletes a tag and its memory associations.

### `listTags(client, workspaceId)`

Lists tags for a workspace (reads `tag` table).

## Memory Tagging

### `tagMemory(client, tagId, memoryId)` / `untagMemory(client, tagId, memoryId)`

Tags or untags a single memory.

### `batchTagMemories(client, tagId, memoryIds)` / `batchUntagMemories(client, tagId, memoryIds)`

Batch tag/untag (no-op on empty arrays).

### `listTagsByMemory(client, memoryId)`

Returns `memory_tag_result` rows for a memory (id, memory_id, tag_id, tag_name, tag_color).

## Search

### `searchByTags(client, workspaceId, tagIds, query?, limit?)`

Searches memories filtered by tags. When `query` is provided, embeds it with the `Represent this sentence for searching relevant passages:` prefix and calls `search_by_tags`; results are read from `hybrid_result` and sorted by score descending.

---

See also: [memories](memories.md), [types](types.md)
