# TypeScript Compounder API

`Compounder` implements the **LLM Wiki** pattern (Karpathy-style) — it turns interactions into persistent knowledge by automatically creating wiki pages, extracting entities, linking them together, and growing the knowledge graph over time. All methods degrade gracefully returning empty/null results when features are not configured.

```typescript
import { Client, Compounder } from "spacetime-memory";

const client = new Client();
const cp = new Compounder(client);

const result = await cp.storeAnswer(
  "What's the relationship between neural nets and evolution?",
  "Both are optimization processes...",
);
```

---

## Constructor

### `new Compounder(client)`

| Param    | Type     | Description                   |
|----------|----------|-------------------------------|
| `client` | `Client` | An authenticated Client instance |

---

## Methods

### 1. `searchEntities(workspaceId?, opts?)`

Search knowledge-graph entities by label, type, or semantic query.

**Params:**

| Param         | Type     | Default      | Description                               |
|---------------|----------|--------------|-------------------------------------------|
| `workspaceId` | `string` | `"default"`  | Target workspace                          |
| `opts.label`  | `string` | —            | Filter by exact label                     |
| `opts.nodeType` | `string` | —          | Filter by node type (e.g. `"concept"`)    |
| `opts.semanticQuery` | `string` | —    | Semantic search query                     |
| `opts.limit`  | `number` | `20`         | Max results                               |

**Returns:** `Promise<Record<string, unknown>[]>` — merged entity records (semantic first, then filtered, deduped).

---

### 2. `findNearDuplicates(content, workspaceId?, opts?)`

Find semantically-similar memories above a score threshold.

**Params:**

| Param          | Type     | Default      | Description                        |
|----------------|----------|--------------|------------------------------------|
| `content`      | `string` | —            | Text to find duplicates of         |
| `workspaceId`  | `string` | `"default"`  | Target workspace                   |
| `opts.threshold` | `number` | `0.92`     | Minimum similarity score           |
| `opts.limit`   | `number` | `5`          | Max results                        |

**Returns:** `Promise<SearchResult[]>`

---

### 3. `storeAnswer(query, answer, opts?)`

Persist a Q&A pair as a wiki page + KG entities. Automatically extracts capitalized entity phrases, creates KG nodes, and links them to the note via `informed_by` edges. Checks for duplicates before storing.

**Params:**

| Param                 | Type       | Default      | Description                              |
|-----------------------|------------|--------------|------------------------------------------|
| `query`               | `string`   | —            | The question/query                       |
| `answer`              | `string`   | —            | The answer text (markdown)               |
| `opts.workspaceId`    | `string`   | `"default"`  | Target workspace                         |
| `opts.title`          | `string`   | auto         | Note title (auto-generated from query)   |
| `opts.sourceMemoryIds` | `string[]` | —           | Source memory IDs to link                |
| `opts.embed`          | `boolean`  | `true`       | Generate embedding for search            |
| `opts.skipDuplicates` | `boolean`  | `true`       | Skip if duplicate detected               |
| `opts.duplicateThreshold` | `number` | `0.92`    | Similarity threshold for duplicate check |

**Returns:** `Promise<StoreAnswerResultEx>`

```typescript
{
  note: Record<string, unknown>;           // Created note metadata
  entities: Array<{ id: string; label: string }>;  // Created KG nodes
  links: string[];                          // Edge IDs created
  duplicateOf?: string;                     // If duplicate found, the existing ID
  duplicateScore?: number;                  // Similarity score of the duplicate
}
```

---

### 4. `storeAnswers(qaPairs, workspaceId?, opts?)`

Batch version of `storeAnswer`. Stores multiple Q&A pairs sequentially.

**Params:**

| Param       | Type                      | Default      | Description               |
|-------------|---------------------------|--------------|---------------------------|
| `qaPairs`   | `[string, string][]`      | —            | Array of [query, answer]  |
| `workspaceId` | `string`                | `"default"`  | Target workspace          |
| `opts`      | `Omit<StoreAnswerOptions, "title">` | —  | Shared options             |

**Returns:** `Promise<StoreAnswerResultEx[]>`

---

### 5. `crossLink(workspaceId?, opts?)`

Auto-link semantically related memories by searching for similar content and creating `related_to` edges.

**Params:**

| Param                     | Type     | Default     | Description                           |
|---------------------------|----------|-------------|---------------------------------------|
| `workspaceId`             | `string` | `"default"` | Target workspace                      |
| `opts.limit`              | `number` | `50`        | Max recent memories to check          |
| `opts.similarityThreshold` | `number` | `0.7`      | Minimum similarity for edge creation  |

**Returns:** `Promise<CompounderCrossLinkResult>`

```typescript
{
  linksCreated: number;
  pairsChecked: number;
}
```

---

### 6. `suggestConnections(workspaceId?, limit?)`

Triangle-count heuristic — find KG node pairs that share neighbors but aren't directly connected.

**Params:**

| Param         | Type     | Default     | Description                |
|---------------|----------|-------------|----------------------------|
| `workspaceId` | `string` | `"default"` | Target workspace           |
| `limit`       | `number` | `50`        | Max nodes to examine       |

**Returns:** `Promise<SuggestConnectionResult[]>`

```typescript
{
  sourceId: string;
  targetId: string;
  sourceLabel: string;
  targetLabel: string;
  commonNeighbours: string[];
  commonCount: number;
}
```

---

### 7. `lintWorkspace(workspaceId?, opts?)`

Health-check a workspace for orphan nodes, missing cross-references, and note orphans.

**Params:**

| Param                          | Type      | Default     | Description                                  |
|--------------------------------|-----------|-------------|----------------------------------------------|
| `workspaceId`                  | `string`  | `"default"` | Target workspace                             |
| `opts.checkOrphans`            | `boolean` | `true`      | Find KG nodes with no edges                  |
| `opts.checkMissingCrossrefs`   | `boolean` | `true`      | Find memories mentioning entities but no edge|
| `opts.checkNoteOrphans`        | `boolean` | `true`      | Find notes not linked to any KG node         |
| `opts.limit`                   | `number`  | `100`       | Max memories to scan                         |

**Returns:** `Promise<LintResult>`

```typescript
{
  orphans: Array<{ id: string; label: string; nodeType: string }>;
  missingCrossrefs: Array<{ entityId: string; entityType: string; mentionedLabel: string; targetNodeId: string }>;
  noteOrphans: Array<{ id: string; title: string; reason: string }>;
  contradictions: Array<{ idA: string; idB: string; contentA: string; contentB: string; explanation: string }>;
  summary: {
    orphanCount: number;
    missingCrossrefCount: number;
    noteOrphanCount: number;
    contradictionCount: number;
    totalIssues: number;
  };
}
```

---

### 8. `ingestSource(sourceText, sourceTitle, workspaceId?, opts?)`

Full source ingestion: creates a wiki page, extracts entities, creates KG nodes, and links them.

**Params:**

| Param              | Type     | Default      | Description                    |
|--------------------|----------|--------------|--------------------------------|
| `sourceText`       | `string` | —            | Full source content            |
| `sourceTitle`      | `string` | —            | Display title for the source   |
| `workspaceId`      | `string` | `"default"`  | Target workspace               |
| `opts.sourceType`  | `string` | `"article"`  | Source type label              |
| `opts.embed`       | `boolean`| `true`       | Generate embedding             |

**Returns:** `Promise<IngestSourceResult>`

```typescript
{
  note: Record<string, unknown>;
  entities: Record<string, unknown>[];
  links: string[];
  contradictions: Array<{ memoryId: string; existingContent: string; explanation: string }>;
}
```

---

### 9. `createEntityPage(name, description, entityType?, workspaceId?, opts?)`

Create a structured entity wiki page + KG node. If the node already exists, it is reused (no duplicate).

**Params:**

| Param                 | Type       | Default      | Description                          |
|-----------------------|------------|--------------|--------------------------------------|
| `name`                | `string`   | —            | Entity name                          |
| `description`         | `string`   | —            | Entity description                   |
| `entityType`          | `string`   | `"concept"`  | Node type (`concept`, `person`, `org`) |
| `workspaceId`         | `string`   | `"default"`  | Target workspace                     |
| `opts.tags`           | `string[]` | —            | Tags for the page                    |
| `opts.relations`      | `Array<{name: string; relation: string}>` | — | Relations to other entities |
| `opts.embed`          | `boolean`  | `true`       | Generate embedding                   |

**Returns:** `Promise<EntityPageResult>`

```typescript
{
  node: Record<string, unknown> | null;  // KG node
  note: Record<string, unknown>;          // Wiki note
}
```

---

### 10. `updateEntityPage(name, workspaceId?, opts?)`

Update an existing entity wiki page + KG node. Updates the node summary, note content, tags, and relations.

**Params:**

| Param                 | Type       | Default      | Description                          |
|-----------------------|------------|--------------|--------------------------------------|
| `name`                | `string`   | —            | Entity name to update                |
| `workspaceId`         | `string`   | `"default"`  | Target workspace                     |
| `opts.description`    | `string`   | —            | New description                      |
| `opts.entityType`     | `string`   | —            | New node type                        |
| `opts.tags`           | `string[]` | —            | New tags                             |
| `opts.relations`      | `Array`    | —            | New relations                        |
| `opts.embed`          | `boolean`  | `true`       | Generate embedding                   |

**Returns:** `Promise<EntityPageResult>`

---

### 11. `createConceptPage(concept, definition, workspaceId?, opts?)`

Create a concept definition wiki page with related concept `[[wiki-links]]` and a KG node.

**Params:**

| Param                 | Type       | Default      | Description                    |
|-----------------------|------------|--------------|--------------------------------|
| `concept`             | `string`   | —            | Concept name                   |
| `definition`          | `string`   | —            | Definition text                |
| `workspaceId`         | `string`   | `"default"`  | Target workspace               |
| `opts.relatedConcepts` | `string[]` | —           | Related concept names          |
| `opts.embed`          | `boolean`  | `true`       | Generate embedding             |

**Returns:** `Promise<EntityPageResult>`

---

### 12. `createComparisonPage(title, items, workspaceId?, opts?)`

Create a markdown comparison table as a wiki page.

**Params:**

| Param            | Type                                  | Default      | Description                     |
|------------------|---------------------------------------|--------------|---------------------------------|
| `title`          | `string`                              | —            | Comparison title                |
| `items`          | `Record<string, string>[] \| string[]` | —           | Items to compare (objects or names) |
| `workspaceId`    | `string`                              | `"default"`  | Target workspace                |
| `opts.criteria`  | `string[]`                            | —            | Column criteria                 |
| `opts.embed`     | `boolean`                             | `true`       | Generate embedding              |

**Returns:** `Promise<{ note: Record<string, unknown> }>`

---

### 13. `exportWorkspace(workspaceId?, opts?)`

Export workspace notes as markdown files. Returns both concatenated markdown and a file list.

**Params:**

| Param                  | Type      | Default     | Description                       |
|------------------------|-----------|-------------|-----------------------------------|
| `workspaceId`          | `string`  | `"default"` | Target workspace                  |
| `opts.includeKg`       | `boolean` | `false`     | Include KG node files             |
| `opts.includeSystemNotes` | `boolean` | `false`  | Include _index / _log notes       |

**Returns:** `Promise<{ markdown: string; files: Array<{ filename: string; content: string }> }>`

---

### 14. `generateOverviewPage(workspaceId?, embed?)`

Generate or update the `_overview` wiki page with workspace statistics, entity lists, recent activity, and orphan counts.

**Params:**

| Param         | Type      | Default     | Description               |
|---------------|-----------|-------------|---------------------------|
| `workspaceId` | `string`  | `"default"` | Target workspace          |
| `embed`       | `boolean` | `true`      | Generate embedding        |

**Returns:** `Promise<OverviewResult>`

```typescript
{
  note: Record<string, unknown>;
}
```

---

## Interfaces

### `CompounderCrossLinkResult`

| Field          | Type     | Description                    |
|----------------|----------|--------------------------------|
| `linksCreated` | `number` | Number of edges created        |
| `pairsChecked` | `number` | Number of candidate pairs examined |

### `SuggestConnectionResult`

| Field             | Type       | Description                          |
|-------------------|------------|--------------------------------------|
| `sourceId`        | `string`   | Source node ID                       |
| `targetId`        | `string`   | Target node ID                       |
| `sourceLabel`     | `string`   | Source node label                    |
| `targetLabel`     | `string`   | Target node label                    |
| `commonNeighbours`| `string[]` | Neighbour IDs shared by both nodes   |
| `commonCount`     | `number`   | Count of common neighbours           |

### `StoreAnswerOptions`

| Field               | Type       | Default      | Description                     |
|---------------------|------------|--------------|---------------------------------|
| `workspaceId`       | `string`   | `"default"`  | Target workspace                |
| `title`             | `string`   | auto         | Note title                      |
| `sourceMemoryIds`   | `string[]` | —            | Source memories to link         |
| `embed`             | `boolean`  | `true`       | Generate embedding              |
| `skipDuplicates`    | `boolean`  | `true`       | Check for duplicates first      |
| `duplicateThreshold`| `number`   | `0.92`       | Similarity threshold            |

### `EntityPageResult`

| Field  | Type                          | Description            |
|--------|-------------------------------|------------------------|
| `node` | `Record<string, unknown> \| null` | KG node or null   |
| `note` | `Record<string, unknown>`     | Created wiki note      |

### `OverviewResult`

| Field  | Type                       | Description     |
|--------|----------------------------|-----------------|
| `note` | `Record<string, unknown>`  | Overview note   |

### `IngestSourceResult`

| Field           | Type       | Description                              |
|-----------------|------------|------------------------------------------|
| `note`          | `object`   | Created source note                      |
| `entities`      | `object[]` | Extracted entity records                 |
| `links`         | `string[]` | Edge IDs created                         |
| `contradictions`| `object[]` | Contradictions found with existing data  |

### `StoreAnswerResultEx`

| Field            | Type       | Description                     |
|------------------|------------|---------------------------------|
| `note`           | `object`   | Created note                    |
| `entities`       | `{id, label}[]` | Created KG entities        |
| `links`          | `string[]` | Created edge IDs                |
| `duplicateOf`    | `string`   | (optional) Existing note ID     |
| `duplicateScore` | `number`   | (optional) Similarity score     |

### `LintResult`

| Field                     | Type       | Description                |
|---------------------------|------------|----------------------------|
| `orphans`                 | `object[]` | Nodes with no edges        |
| `missingCrossrefs`        | `object[]` | Memories missing KG edges  |
| `noteOrphans`             | `object[]` | Notes not linked to nodes  |
| `contradictions`          | `object[]` | Contradictory memories     |
| `summary.orphanCount`     | `number`   | Count of orphans           |
| `summary.missingCrossrefCount` | `number` | Count of missing crossrefs |
| `summary.noteOrphanCount` | `number`   | Count of note orphans      |
| `summary.contradictionCount` | `number` | Count of contradictions    |
| `summary.totalIssues`     | `number`   | Total issues found         |
