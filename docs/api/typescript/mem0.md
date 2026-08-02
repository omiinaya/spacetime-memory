# TypeScript Mem0 Adapter API

Drop-in replacement for `mem0.Memory` that uses Spacetime Memory as the backend store. Matches the public API shape of the official Mem0 TypeScript SDK (`mem0ai/mem0` packages).

```typescript
import { Memory } from "spacetime-memory/mem0";

const m = new Memory({ host: "127.0.0.1", port: 3001 });
await m.add("I like pizza", { userId: "alice" });
const results = await m.search("food preferences", { userId: "alice" });
```

**Mapping:**

| Mem0 concept     | Spacetime Memory equivalent |
|------------------|-----------------------------|
| `user_id`        | `workspace_id`              |
| `agent_id`       | `peer_id`                   |
| `run_id`         | `source_session_id`         |

---

## Constructor

### `new Memory(config?)`

| Param           | Type          | Default | Description                         |
|-----------------|---------------|---------|-------------------------------------|
| `config.host`   | `string`      | `127.0.0.1` | SpacetimeDB host           |
| `config.port`   | `number\|string` | `3001` | SpacetimeDB port                  |
| `config.db`     | `string`      | `"spacetime-memory"` | Database name         |
| `config.embedderUrl` | `string` | `http://127.0.0.1:4000` | Embedder sidecar |
| `config.mcpUrl` | `string`      | `http://127.0.0.1:8099` | MCP server URL |
| `config.llmConfig` | `Record<string, {model?, apiKey?, baseUrl?}>` | — | Per-user LLM overrides |

---

## Static Methods

### `Memory.fromConfig(configDict)`

Create a Memory instance from a config object (Mem0 v2+ compatibility).

**Returns:** `Memory`

---

## Methods

### `add(messages, options)`

Store a memory. Accepts either a plain string or an array of conversation messages.

**Params:**

| Param                      | Type       | Default | Description                          |
|----------------------------|------------|---------|--------------------------------------|
| `messages`                 | `string \| Array<{role, content}>` | — | Memory content or conversation |
| `options.userId`           | `string`   | —       | User scope (→ workspace)             |
| `options.agentId`          | `string`   | —       | Agent identifier (→ peer_id)         |
| `options.runId`            | `string`   | —       | Session identifier                   |
| `options.metadata`         | `Record<string, unknown>` | — | Custom metadata              |
| `options.filters`          | `Record<string, unknown>` | — | Shorthand filter (user_id, agent_id, run_id) |
| `options.infer`            | `boolean`  | `true`  | Extract facts via LLM                |
| `options.memoryType`       | `string`   | `"experience"` | Memory type label             |

When `infer` is `true` and a string is passed, the adapter attempts to infer-merge: it searches for an existing memory with `score > 0.85` and appends the new content to it (rather than creating a duplicate), then optionally extracts and stores facts as KG nodes.

**Returns:** `Promise<AddResult>`

```typescript
{
  results: Array<{
    id: string;
    memory: string;
    event: "ADD" | "UPDATE";
    user_id: string;
    agent_id: string;
  }>;
  relation_events: unknown[];
}
```

---

### `search(query, options)`

Search memories by semantic similarity.

**Params:**

| Param                 | Type       | Default | Description                              |
|-----------------------|------------|---------|------------------------------------------|
| `query`               | `string`   | —       | Search query                             |
| `options.userId`      | `string`   | —       | Filter by user                           |
| `options.agentId`     | `string`   | —       | Filter by agent                          |
| `options.runId`       | `string`   | —       | Filter by run                            |
| `options.limit`       | `number`   | `100`   | Max results                              |
| `options.threshold`   | `number`   | `0.0`   | Minimum score threshold                  |
| `options.topK`        | `number`   | —       | Override for limit (Mem0 compat)         |
| `options.filters`     | `object`   | —       | Shorthand filter (user_id, agent_id, run_id) |
| `options.rerank`      | `boolean`  | —       | Enable cross-encoder reranking           |
| `options.graphContext`| `boolean`  | `true`  | Enrich results with KG context           |

**Returns:** `Promise<{ results: MemoryResult[] }>`

Each `MemoryResult`:

```typescript
{
  id: string;
  memory: string;
  score?: number;
  user_id: string;
  agent_id: string;
  metadata?: {
    graph_context?: string[];   // Related KG entity labels
  };
}
```

---

### `get(memoryId)`

Retrieve a single memory by its ID.

| Param      | Type     | Description    |
|------------|----------|----------------|
| `memoryId` | `string` | Memory ID      |

**Returns:** `Promise<{ results: MemoryResult[] }>` — empty array if not found (or soft-deleted).

---

### `getAll(options)`

List all memories for a user.

**Params:**

| Param            | Type       | Default | Description                    |
|------------------|------------|---------|--------------------------------|
| `options.userId` | `string`   | —       | Filter by user                 |
| `options.agentId`| `string`   | —       | Filter by agent                |
| `options.runId`  | `string`   | —       | Filter by run                  |
| `options.limit`  | `number`   | `100`   | Max results                    |
| `options.filters`| `object`   | —       | Shorthand filter               |
| `options.topK`   | `number`   | —       | Override for limit             |

**Returns:** `Promise<{ results: MemoryResult[] }>`

---

### `update(memoryId, data, options?)`

Update a memory's content and/or metadata.

**Params:**

| Param      | Type                                  | Description                |
|------------|---------------------------------------|----------------------------|
| `memoryId` | `string`                              | Memory ID                  |
| `data`     | `string \| Record<string, unknown>`    | New content or object with `{content, memory}` |
| `options.metadata` | `Record<string, unknown>`     | Custom metadata            |

**Returns:** `Promise<{ message: string }>`

---

### `delete(memoryId)`

Delete a memory by ID.

| Param      | Type     | Description |
|------------|----------|-------------|
| `memoryId` | `string` | Memory ID   |

**Returns:** `Promise<{ message: string }>`

---

### `deleteAll(options?)`

Delete all memories for a user.

**Params:**

| Param            | Type       | Default | Description          |
|------------------|------------|---------|----------------------|
| `options.userId` | `string`   | —       | User to clear        |
| `options.agentId`| `string`   | —       | Filter by agent      |
| `options.runId`  | `string`   | —       | Filter by run        |
| `options.filters`| `object`   | —       | Shorthand filter     |

**Returns:** `Promise<{ status: string; deleted: number }>`

---

### `history(memoryId)`

Get version history for a memory.

| Param      | Type     | Description |
|------------|----------|-------------|
| `memoryId` | `string` | Memory ID   |

**Returns:** `Promise<HistoryEntry[]>`

```typescript
{
  version: number;
  content: string;
  summary: string;
  confidence: number;
  created_at: number;
}
```

---

### `chat(query, options)`

Generate a chat response augmented by stored memories (RAG). Stores the query as a memory, searches for relevant context, and returns the assembled result.

**Params:**

| Param                 | Type            | Default        | Description                |
|-----------------------|-----------------|----------------|----------------------------|
| `query`               | `string`        | —              | User query                 |
| `options.userId`      | `string`        | —              | User scope                 |
| `options.agentId`     | `string`        | `"assistant"`  | Agent identifier           |
| `options.runId`       | `string`        | —              | Session identifier         |
| `options.messages`    | `Array<{role, content}>` | — | Conversation history        |
| `options.memoryType`  | `string`        | —              | Memory type                |
| `options.llmConfig`   | `{provider?, model?, apiKey?, baseUrl?}` | — | LLM override              |

**Returns:** `Promise<ChatResult>`

```typescript
{
  response: string;       // Generated response (currently mirrors input when no LLM configured)
  context: string[];      // Retrieved memory context texts
  memories: MemoryResult[];  // Memory records used as context
}
```

---

### `reset()`

Reset all state — clear the workspace cache.

**Returns:** `{ status: "ok" }`

---

### `close()`

Close the underlying HTTP client (idempotent). Mem0 v2+ compat.

**Returns:** `void`

---

### `setLlmConfig(userId, llmConfig)`

Set per-user LLM configuration overrides.

| Param        | Type       | Description                           |
|--------------|------------|---------------------------------------|
| `userId`     | `string`   | User identity hash                    |
| `llmConfig`  | `{provider?, model?, apiKey?, baseUrl?}` | LLM provider config |

**Returns:** `void`

---

### `graph.add(text, options?)`

Add an entity to the knowledge graph. Uses vector-based deduplication: searches for semantically-similar existing entities (score ≥ 0.85) and adds an alias rather than creating a duplicate.

**Params:**

| Param                | Type       | Default     | Description                  |
|----------------------|------------|-------------|------------------------------|
| `text`               | `string`   | —           | Entity name                  |
| `options.entityType` | `string`   | `"concept"` | Entity type                  |
| `options.userId`     | `string`   | —           | User scope                   |
| `options.agentId`    | `string`   | —           | Agent identifier             |
| `options.metadata`   | `object`   | —           | Custom metadata              |

**Returns:** `Promise<GraphEntity>`

```typescript
{
  id: string;
  label: string;
  node_type: string;
  entity_type: string;
  summary: string;
  metadata_json: string;
  created_at: number;
  score?: number;
  merged?: boolean;  // true if matched an existing entity
}
```

---

### `graph.search(query, options?)`

Search graph entities by label. Uses semantic search when the embedder sidecar is available, BM25 fallback, then substring matching.

**Params:**

| Param             | Type     | Default | Description         |
|-------------------|----------|---------|---------------------|
| `query`           | `string` | —       | Search text         |
| `options.userId`  | `string` | —       | User scope          |
| `options.limit`   | `number` | `10`    | Max results         |

**Returns:** `Promise<GraphEntity[]>`

---

### `graph.getAll(options?)`

List all graph entities for a user.

**Params:**

| Param            | Type     | Default | Description  |
|------------------|----------|---------|--------------|
| `options.userId` | `string` | —       | User scope   |
| `options.limit`  | `number` | `100`   | Max results  |

**Returns:** `Promise<GraphEntity[]>`

---

### `graph.delete(entityId)`

Delete a graph entity by node ID.

| Param      | Type     | Description |
|------------|----------|-------------|
| `entityId` | `string` | Node ID     |

**Returns:** `Promise<{ status: string; deleted: string }>`

---

### `createMemoryTool(options?)`

> **Deprecated.** This method was removed from upstream Mem0 v2.0. Use `chat()` for RAG or `search()`+`add()` directly.

**Returns:** `{ status: "not_implemented"; note: string }`

---

## Interfaces

### `MemoryConfig`

| Field         | Type                                                         | Default                       | Description              |
|---------------|--------------------------------------------------------------|-------------------------------|--------------------------|
| `host`        | `string`                                                     | `"127.0.0.1"`              | SpacetimeDB host         |
| `port`        | `number \| string`                                           | `3001`                        | SpacetimeDB port         |
| `db`          | `string`                                                     | `"spacetime-memory"`          | Database name            |
| `embedderUrl` | `string`                                                     | `"http://127.0.0.1:4000"` | Embedder sidecar URL     |
| `mcpUrl`      | `string`                                                     | `"http://127.0.0.1:8099"`     | MCP server URL           |
| `llmConfig`   | `Record<string, { model?, apiKey?, baseUrl? }>`              | —                             | Per-user LLM overrides   |

### `AddResult`

| Field             | Type          | Description                    |
|-------------------|---------------|--------------------------------|
| `results`         | `MemoryResult[]` | Added/updated memories       |
| `relation_events` | `unknown[]`   | Relation events (always `[]`)  |

### `MemoryResult`

| Field      | Type     | Description               |
|------------|----------|---------------------------|
| `id`       | `string` | Memory ID                 |
| `memory`   | `string` | Memory content            |
| `score?`   | `number` | Relevance score           |
| `user_id`  | `string` | User scope                |
| `agent_id` | `string` | Agent identifier          |
| `metadata?`| `object` | Additional metadata       |

### `SearchOptions`

| Field            | Type       | Default | Description                     |
|------------------|------------|---------|---------------------------------|
| `userId`         | `string`   | —       | Filter by user                  |
| `agentId`        | `string`   | —       | Filter by agent                 |
| `runId`          | `string`   | —       | Filter by run                   |
| `limit`          | `number`   | `100`   | Max results                     |
| `threshold`      | `number`   | `0.0`   | Minimum score threshold         |
| `topK`           | `number`   | —       | Override for limit              |
| `filters`        | `object`   | —       | Shorthand filter                |
| `rerank`         | `boolean`  | —       | Enable reranking                |
| `graphContext`   | `boolean`  | `true`  | Include KG context              |

### `GraphEntity`

| Field           | Type      | Description               |
|-----------------|-----------|---------------------------|
| `id`            | `string`  | Node ID                   |
| `label`         | `string`  | Entity label              |
| `node_type`     | `string`  | Node type                 |
| `entity_type`   | `string`  | Entity type               |
| `summary`       | `string`  | Entity summary            |
| `metadata_json` | `string`  | JSON metadata             |
| `created_at`    | `number`  | Creation timestamp        |
| `score?`        | `number`  | Relevance score (search)  |
| `merged?`       | `boolean` | Whether matched existing  |

### `HistoryEntry`

| Field       | Type     | Description           |
|-------------|----------|-----------------------|
| `version`   | `number` | Revision version      |
| `content`   | `string` | Memory content        |
| `summary`   | `string` | Memory summary        |
| `confidence`| `number` | Confidence score      |
| `created_at`| `number` | Creation timestamp    |

### `ChatResult`

| Field      | Type          | Description                     |
|------------|---------------|---------------------------------|
| `response` | `string`      | Generated response text         |
| `context`  | `string[]`    | Retrieved memory context texts  |
| `memories` | `MemoryResult[]` | Memory records used as context |
