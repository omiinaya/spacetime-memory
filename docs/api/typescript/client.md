# TypeScript Client API

The `Client` class provides a type-safe interface to the SpacetimeDB HTTP SQL and reducer APIs. All methods are async and return `Promise<T>`.

```typescript
import { Client } from "spacetime-memory";

const client = new Client();
```

---

## Construction

### `new Client(opts?)`

**`ClientOptions`**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `host` | `string` | `SPACETIMEDB_HOST` env \|\| `"127.0.0.1"` | SpacetimeDB host |
| `port` | `number \| string` | `SPACETIMEDB_PORT` env \|\| `"3001"` | SpacetimeDB port |
| `database` | `string` | `SPACETIMEDB_DB` env \|\| `"spacetime-memory"` | Database identity |
| `embedderUrl` | `string` | `EMBEDDER_URL` env \|\| `"http://127.0.0.1:4000"` | Embedder sidecar URL |
| `tantivyUrl` | `string` | `TANTIVY_URL` env \|\| `"http://127.0.0.1:9091"` | Tantivy BM25 sidecar URL |
| `mcpUrl` | `string` | `MCP_URL` env \|\| `"http://127.0.0.1:8099"` | MCP server for cross-encoder |

---

## Auth / Account

### `client.register(username, displayName?, password?): Promise<void>`
Register a new account. First user becomes admin.

### `client.login(username, password): Promise<void>`
Login with username + password. Links this identity to the account.

### `client.logout(): Promise<void>`
Logout — detach the current identity from its account.

### `client.updateAccount(displayName?, currentPassword?, newPassword?): Promise<void>`
Update account display name and/or password.

### `client.deactivateAccount(password): Promise<void>`
Soft-delete this account (is_active=false).

### `client.promoteAdmin(targetIdentity): Promise<void>`
Promote a user to admin. Caller must be admin.

### `client.demoteAdmin(targetIdentity): Promise<void>`
Demote an admin to regular user. Requires admin. Cannot demote self.

### `client.listAdmins(): Promise<Record<string, unknown>[]>`
List all admin accounts.

---

## Workspace

### `client.createWorkspace(name, description?): Promise<void>`
Create a new workspace.

### `client.listWorkspaces(): Promise<Workspace[]>`
List all workspaces.

**`Workspace`** `{ id, name, description?, created_at? }`

### `client.updateWorkspace(id, name, description): Promise<void>`
Update workspace name and description.

### `client.deleteWorkspace(workspaceId): Promise<void>`
Delete a workspace.

### `client.setWorkspaceVisibility(workspaceId, isPublic): Promise<void>`
Set workspace visibility (public/private).

### `client.getWorkspaceContext(workspaceId): Promise<Record<string, unknown> | null>`
Retrieve workspace context info.

### `client.listSpaceMembers(workspaceId): Promise<SpaceMemberRecord[]>`
List members of a space.

**`SpaceMemberRecord`** `{ id, workspace_id, peer_id, permission, joined_at? }`

### `client.listPeers(workspaceId?): Promise<PeerRecord[]>`
List peers, optionally filtered by workspace.

**`PeerRecord`** `{ id, workspace_id, name, peer_type, metadata, created_at, updated_at }`

### `client.grantSpaceAccess(workspaceId, peerId, permission): Promise<void>`
Grant a peer access to a workspace.

### `client.revokeSpaceAccess(workspaceId, peerId): Promise<void>`
Revoke a peer's access to a workspace.

---

## API Keys

### `client.createApiKey(workspaceId, name, permissions?): Promise<Record<string, unknown>>`
Create a new API key. Returns the secret key (shown only once) and its DB ID.

- `permissions` — JSON string, default: `'["read"]'`

Returns: `{ status, api_key, id, note }`

### `client.deactivateApiKey(keyId): Promise<void>`
Revoke an API key.

### `client.listApiKeys(workspaceId): Promise<Record<string, unknown>[]>`
List all API keys for a workspace.

---

## Memory

### `client.store(workspaceId, content, opts?): Promise<void>`
Store a memory. Auto-indexes with embedding.

**`StoreOptions`**

| Option | Type | Default |
|--------|------|---------|
| `summary` | `string` | `""` |
| `memoryType` | `string` | `"experience"` |
| `peerId` | `string` | `""` |
| `tier` | `string` (L0/L1/L2) | unset |
| `images` | `string \| string[]` | unset |

### `client.search(workspaceId, query, opts?): Promise<SearchResult[]>`
Hybrid or keyword search across memories.

**`SearchOptions`**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `memoryType` | `string` | `""` | Filter by memory type |
| `tier` | `string` | `""` | Filter by tier |
| `limit` | `number` | `20` | Max results |
| `semantic` | `boolean` | `true` | Use embedding search |
| `crossEncoder` | `boolean` | `true` | Apply cross-encoder reranking |
| `temporalFilter` | `{ from?, to? }` | — | Unix μs timestamp range |
| `before` | `number` | — | `created_at < before` |
| `after` | `number` | — | `created_at > after` |

**`SearchResult`**

```typescript
{
  id: string;
  entity_id: string;
  entity_type: string;
  content: string;
  score: number;
  strategy: string;
  memory_content?: string;
  node_label?: string;
  context_json?: string;
  created_at?: number; // μs
}
```

### `client.getMemory(memoryId): Promise<MemoryRecord[]>`
Get a single memory by ID. Also reinforces it.

### `client.deleteMemory(memoryId): Promise<void>`
Soft-delete a memory (deactivate).

### `client.batchDeleteMemories(memoryIds): Promise<void>`
Batch-delete multiple memories in one call.

### `client.reinforce(memoryId): Promise<void>`
Reinforce a memory (increment access count).

### `client.updateMemory(memoryId, content, summary?, confidence?, expiresAt?): Promise<void>`
Update a memory's content and metadata.

### `client.rateMemory(memoryId, rating, peerId): Promise<void>`
Rate a memory with user feedback.

### `client.listMemories(workspaceId, opts?): Promise<MemoryRecord[]>`
List memories sorted by recency.

**`ListMemoriesOptions`** `{ memoryType?, limit? (default 50) }`

### `client.getUserMemories(userScope, workspaceId): Promise<Record<string, unknown>[]>`
Get all memories scoped to a specific user.

### `client.consolidateMemories(workspaceId, sourceIds, targetContent, targetSummary): Promise<void>`
Merge multiple memories into one.

### `client.expireMemories(): Promise<void>`
Deactivate all expired memories.

### `client.getMemoryStats(workspaceId): Promise<Record<string, string> | null>`
Get memory metrics (counts by tier, type, etc.).

### `client.getMemoryHistory(memoryId): Promise<MemoryRevisionRecord[]>`
Get revision history of a memory.

### `client.searchDirectoryContents(workspaceId, directoryPath): Promise<Record<string, unknown>[]>`
Search directory contents.

### `client.fuzzyGet(workspaceId, name, field?, threshold?, limit?): Promise<Record<string, unknown> | null>`
Best-matching memory by string similarity (dice coefficient).

### `client.globGet(workspaceId, pattern, field?, limit?): Promise<Record<string, unknown>[]>`
Glob-style memory matching (`*`, `?` wildcards).

---

## Knowledge Graph

### `client.createNode(workspaceId, label, nodeType?, summary?): Promise<void>`
Create a KG node. Optionally indexes with embedding.

- `nodeType` — e.g. `"concept"`, `"person"`, `"org"` (default: `"concept"`)

### `client.getNode(nodeId): Promise<Record<string, unknown>[]>`
Get a KG node by ID.

### `client.updateNode(nodeId, summary?, nodeType?): Promise<void>`
Update a KG node's summary and/or type.

### `client.deleteNode(nodeId): Promise<void>`
Delete a KG node.

### `client.createEdge(workspaceId, sourceNodeId, targetNodeId, relation, weight?): Promise<void>`
Create a directed edge between two nodes.

- `relation` — e.g. `"related_to"`, `"informed_by"`
- `weight` — default: `1.0`

### `client.updateEdge(edgeId, weight?): Promise<void>`
Update an edge's weight.

### `client.deleteEdge(edgeId): Promise<void>`
Delete an edge.

### `client.queryGraph(workspaceId, query?): Promise<KGNodeRecord[]>`
Search KG nodes by label (LIKE match). Returns all if no query.

### `client.getNeighbors(nodeId): Promise<KGEdgeRecord[]>`
Get all edges (incoming + outgoing) for a node.

### `client.getNeighborsViaReducer(workspaceId, nodeId): Promise<void>`
Get neighboring nodes via the `get_neighbors` reducer (results stored in `graph_traversal_result` table).

| Param | Type | Description |
|-------|------|-------------|
| `workspaceId` | `string` | Workspace ID |
| `nodeId` | `string` | Node ID |

### `client.graphBfs(workspaceId, startNodeId, maxDepth?): Promise<Record<string, unknown>[]>`
BFS traversal from a start node. `maxDepth` default: `3`.

### `client.bfs(workspaceId, startNodeId, maxDepth?): Promise<Record<string, unknown>[]>`
Alias for `graphBfs` using a different result table.

### `client.shortestPath(workspaceId, sourceId, targetId, maxHops?): Promise<Record<string, unknown>[]>`
Shortest path between two nodes. `maxHops` default: `6`.

### `client.detectCommunities(workspaceId): Promise<void>`
Detect communities in the KG.

### `client.seedCommunities(workspaceId): Promise<void>`
Seed communities (init community structure).

### `client.getCommunity(communityId): Promise<Record<string, unknown>[]>`
Get community info by ID.

### `client.computePageRank(workspaceId, damping?, maxIterations?): Promise<void>`
Compute PageRank for all nodes.

### `client.computeKgStats(workspaceId): Promise<Record<string, unknown> | null>`
Compute KG statistics.

### `client.computeCommunityHierarchy(workspaceId): Promise<void>`
Compute community hierarchy.

### `client.detectBridgeNodes(workspaceId, limit?, minCommunities?): Promise<Record<string, unknown>[]>`
Detect bridge nodes connecting multiple communities.

### `client.getEdgeHistory(edgeGroupId): Promise<Record<string, unknown>[]>`
Get revision history for an edge group.

### `client.addNodeCitation(workspaceId, nodeId, memoryId, description?): Promise<void>`
Cite a source memory for a KG node.

### `client.addEdgeCitation(workspaceId, edgeId, memoryId, description?): Promise<void>`
Cite a source memory for a KG edge.

### `client.getCitations(workspaceId, entityId, entityType?): Promise<Record<string, unknown>[]>`
Get citations for a KG entity (node or edge).

---

## Notes / Wiki

### `client.createNote(workspaceId, title, content, opts?): Promise<void>`
Create a wiki note.

**Options:** `{ note_date?: string; embed?: boolean }` (embed defaults `true`)

### `client.updateNote(noteId, title?, content?, embeddingJson?, expectedVersion?): Promise<void>`
Update a note with optimistic concurrency check.

### `client.deleteNote(noteId): Promise<void>`
Delete a note.

### `client.listNotes(workspaceId): Promise<NoteRecord[]>`
List all notes in a workspace.

### `client.getNote(noteId): Promise<NoteRecord[]>`
Get a single note by ID.

### `client.getNoteByDate(noteDate): Promise<NoteRecord[]>`
Get notes by date string (YYYY-MM-DD).

### `client.getNoteByTitle(title): Promise<NoteRecord[]>`
Find a note by exact title.

### `client.getNoteHistory(noteId): Promise<Record<string, unknown>[]>`
Get version history of a note.

### `client.getBacklinks(noteId): Promise<Record<string, unknown>[]>`
Get incoming wiki links for a note.

### `client.getOutgoingLinks(noteId): Promise<Record<string, unknown>[]>`
Get outgoing wiki links from a note.

---

## Documents

### `client.createDocument(workspaceId, title, content?, contentType?, filePath?, sourceUrl?, metadata?): Promise<void>`
Create a document with auto-chunking (≥100 chars).

- `contentType` — `"text"`, `"pdf"`, `"image"`, `"video"`, `"code"`, or `"url"`

### `client.getDocument(docId): Promise<Record<string, unknown> | null>`
Get a document by ID.

### `client.listDocuments(workspaceId): Promise<Record<string, unknown>[]>`
List all documents.

### `client.getDocumentChunks(docId): Promise<Record<string, unknown>[]>`
Get chunks for a document.

### `client.deleteDocument(docId): Promise<void>`
Delete a document.

---

## Profiles & Facts

### `client.upsertProfile(peerId, staticFacts?, dynamicContext?, preferences?, tags?): Promise<void>`
Create or update a peer profile. Each field is a JSON-encoded string.

### `client.getProfile(peerId): Promise<Record<string, unknown> | null>`
Get a peer's profile by ID.

### `client.listProfiles(workspaceId): Promise<Record<string, unknown>[]>`
List all profiles in a workspace.

### `client.searchProfiles(workspaceId, query, limit?): Promise<Record<string, unknown>[]>`
Search profiles by static_facts/dynamic_context.

### `client.addProfileFact(peerId, fact): Promise<void>`
Append a fact to a peer's profile.

### `client.addDynamicContext(peerId, context): Promise<void>`
Add dynamic context to a peer's profile.

### `client.getProfileContext(peerId): Promise<Record<string, unknown> | null>`
Get profile context result.

### `client.addFact(workspaceId, peerId, content, opts?): Promise<void>`
Add a fact about a peer.

**`AddFactOptions`** `{ factType?, confidence? (default 0.8) }`

### `client.listFacts(workspaceId, peerId): Promise<FactRecord[]>`
List facts for a peer.

### `client.updateFact(factId, content, confidence?): Promise<void>`
Update a fact's content and confidence.

### `client.deleteFact(factId): Promise<void>`
Delete a fact.

### `client.searchFacts(workspaceId, query): Promise<FactRecord[]>`
Search facts by content.

---

## Sessions

### `client.createSession(workspaceId, name?): Promise<void>`
Create a new agent session.

### `client.joinSession(sessionId): Promise<void>`
Join an existing session.

### `client.leaveSession(sessionId): Promise<void>`
Leave a session.

### `client.getPeerSessions(peerId): Promise<Record<string, unknown>[]>`
List sessions a peer has participated in.

### `client.getSessionMessages(sessionId): Promise<Record<string, unknown>[]>`
Get messages for a session.

### `client.addAgentStep(sessionId, step, stepType?): Promise<void>`
Record an agent step. `stepType`: `"action"` (default), `"thought"`, `"observation"`.

### `client.getSessionSteps(sessionId): Promise<SessionStepRecord[]>`
Get all steps in a session.

### `client.searchSessionsSemantic(query, limit?): Promise<Record<string, unknown>[]>`
Semantic search across all sessions.

---

## Tags

### `client.createTag(workspaceId, name, color?): Promise<void>`
Create a tag.

### `client.listTags(workspaceId): Promise<TagRecord[]>`
List all tags.

### `client.deleteTag(tagId): Promise<void>`
Delete a tag and its associations.

### `client.updateTag(tagId, name?, color?): Promise<void>`
Update a tag's name/color.

### `client.tagMemory(tagId, memoryId): Promise<void>`
Tag a memory.

### `client.untagMemory(tagId, memoryId): Promise<void>`
Remove a tag from a memory.

### `client.batchTagMemories(tagId, memoryIds): Promise<void>`
Batch-attach a tag to multiple memories.

### `client.batchUntagMemories(tagId, memoryIds): Promise<void>`
Batch-remove a tag from multiple memories.

### `client.listTagsByMemory(memoryId): Promise<Record<string, unknown>[]>`
List tags for a specific memory.

### `client.searchByTags(workspaceId, tagIds, query?, limit?): Promise<Record<string, unknown>[]>`
Search memories with AND tag intersection, optionally ranked by semantic similarity.

---

## Context Packs & Directories

### `client.storeContextPack(workspaceId, name, memoryIds, contextText?): Promise<void>`
Store a context pack.

### `client.listContextPacks(workspaceId): Promise<Record<string, unknown>[]>`
List context packs.

### `client.listContextEntries(packId): Promise<Record<string, unknown>[]>`
List entries in a context pack.

### `client.listContextDeltas(previousPackId): Promise<Record<string, unknown>[]>`
List delta entries for a pack.

### `client.createDirectory(workspaceId, name, path, parentId?, description?): Promise<void>`
Create a directory.

### `client.getDirectory(workspaceId, pathOrId): Promise<Record<string, unknown>[]>`
Get a directory by ID or path.

### `client.listDirectory(directoryId): Promise<Record<string, unknown>[]>`
List children of a directory.

### `client.traverseDirectory(workspaceId, rootDirectoryId): Promise<Record<string, unknown>[]>`
Recursive BFS traversal of a directory tree.

### `client.linkMemoryToDirectory(directoryId, memoryId, workspaceId): Promise<void>`
Link a memory to a directory.

### `client.unlinkMemoryFromDirectory(directoryId, memoryId): Promise<void>`
Unlink a memory from a directory.

---

## Advanced Search

### `client.searchWithFilters(workspaceId, query, memoryType?, tier?, metadataFilter?, locationFilter?, limit?): Promise<Record<string, unknown>[]>`
Search with metadata JSON filter and location substring matching.

---

## Entity Linking

### `client.createEntityLink(workspaceId, name, entityType, description?): Promise<void>`
Create a canonical entity link.

### `client.addAlias(entityLinkId, alias): Promise<void>`
Add an alias to an entity link.

### `client.resolveEntity(workspaceId, name): Promise<void>`
Resolve an entity name via alias resolution.

---

## Entity Extraction

### `client.extractEntities(workspaceId, content): Promise<void>`
Extract entities from text and create KG nodes.

---

## Mental Models

### `client.synthesizeMentalModels(workspaceId, memoryIds): Promise<MentalModelRecord[]>`
Synthesize mental models from memories.

### `client.getMentalModel(modelId): Promise<MentalModelRecord[]>`
Get a mental model by ID.

### `client.listMentalModels(workspaceId, status?): Promise<MentalModelRecord[]>`
List mental models.

### `client.updateMentalModel(modelId, content, confidence?, status?): Promise<void>`
Update a mental model.

### `client.deleteMentalModel(modelId): Promise<void>`
Delete a mental model.

---

## Connector Configuration

### `client.registerConnector(name, connectorType, configJson, workspaceId, scheduleSecs): Promise<void>`
Register a connector. Types: `"slack"`, `"discord"`, `"webhook"`, etc.

### `client.updateConnector(id, name, connectorType, configJson, workspaceId, scheduleSecs, isActive): Promise<void>`
Update connector config.

### `client.deleteConnector(id): Promise<void>`
Delete a connector.

---

## Maintenance

### `client.runMaintenance(): Promise<void>`
Run general system maintenance.

### `client.dedup(workspaceId): Promise<void>`
Deduplicate memories.

### `client.suggestMerges(workspaceId, threshold?): Promise<void>`
Scan memories for merge suggestions.

### `client.approveMerge(suggestionId): Promise<void>`
Approve a merge suggestion.

### `client.rejectMerge(suggestionId): Promise<void>`
Reject a merge suggestion.

### `client.detectPatterns(workspaceId, opts?): Promise<PatternDetectionResult>`
Run client-side pattern detection (temporal clusters, frequent terms, co-occurrences).

---

## Tours

### `client.createTour(workspaceId, name, description?): Promise<void>`
Create a guided tour.

### `client.addTourStop(tourId, nodeId, sequence): Promise<void>`
Add a KG node as a tour stop.

### `client.removeTourStop(tourStopId): Promise<void>`
Remove a tour stop.

### `client.deleteTourStop(stopId): Promise<void>`
Alias for removeTourStop.

### `client.deleteTour(tourId): Promise<void>`
Delete a tour.

---

## Backup & Restore

### `client.backup(outputPath?): Promise<Record<string, unknown>>`
Export all user data tables to JSON. In Node.js writes to disk; in browser triggers download.

Returns: `{ status, path, tables: string[], total_rows }`

### `client.restore(inputJson): Promise<Record<string, unknown>>`
Import a backup JSON payload. Accepts string or parsed object.

Returns: `{ status, tables: string[], total_rows }`

### `client.exportWorkspace(workspaceId): Promise<string>`
Export workspace notes as concatenated markdown.

### `client.exportWorkspaceJson(workspaceId, opts?): Promise<Record<string, unknown>>`
Export workspace as structured JSON matching backup format.

---

## Memory Tier & Scope

### `client.updateMemoryTier(memoryId, tier): Promise<void>`
Update memory tier (L0/L1/L2).

### `client.escalateMemories(workspaceId, l2ToL1?, l1ToL0?): Promise<void>`
Batch-escalate memory tiers based on access count.

### `client.setMemoryScope(memoryId, userScope): Promise<void>`
Set memory scope for user isolation.

### `client.setDecayModel(workspaceId, modelType, halfLife, maxStrength): Promise<void>`
Set decay model configuration.

### `client.getDecayConfig(workspaceId): Promise<Record<string, unknown> | null>`
Get decay configuration for a workspace.

---

## Memory Recommendations

### `client.recommendMemories(workspaceId, limit?, minUrgency?): Promise<Record<string, unknown>[]>`
Get memory recommendations sorted by urgency.

---

## Harmonic Beliefs

### `client.storeHarmonicBeliefs(workspaceId, peerId, beliefsJson, clusterId): Promise<void>`
Store harmonized beliefs from a resonance round.

### `client.clearHarmonicBeliefs(workspaceId, minConfidence): Promise<void>`
Clear stale beliefs.

### `client.logResonanceSession(workspaceId, peerId, ...): Promise<void>`
Log a resonance session summary.

---

## Context

### `client.setWorkspaceContext(workspaceId, context): Promise<void>`
Attach context string to a workspace.

### `client.setMemoryContext(memoryId, context): Promise<void>`
Attach context string to a memory.

### `client.getContextChain(memoryId): Promise<Record<string, unknown>[]>`
Get context chain (parents, ancestors) for a memory.

---

## Peer Reputation

### `client.getPeerReputation(peerId): Promise<Record<string, unknown> | null>`
Get reputation stats for a peer.

---

## Health & Ping

### `client.ping(): Promise<Record<string, unknown>>`
Quick connectivity check. Returns `{ status: "ok" }` or `{ status: "error" }`.

### `client.checkEmbedderHealth(): Promise<Record<string, unknown>>`
Check if the embedder sidecar is reachable.

### `client.health(): Promise<Record<string, unknown>>`
Comprehensive health check (DB + embedder).

---

## Compounder / Wiki Operations (on Client)

The Client class also includes simplified compounder methods that don't require an LLM:

### `client.storeAnswer(query, answer, opts?): Promise<StoreAnswerResult>`
Store an answer as a wiki note, auto-extract entities, link to KG.

### `client.crossLink(workspaceId, limit?): Promise<CrossLinkResult>`
Cross-link related memories with "related_to" edges.

### `client.suggestConnections(workspaceId): Promise<KGNodeRecord[]>`
Find node pairs for new connections.

### `client.lintWorkspace(workspaceId): Promise<LintResult>`
Count orphan KG nodes (nodes with no edges).

### `client.generateOverview(workspaceId): Promise<OverviewResult>`
Generate workspace overview statistics.

---

## Batch Operations

### `client.storeBatch(workspaceId, items): Promise<void>`
Batch-store multiple memories in one reducer call. Batch-embeds all items together.

### `client.batchUpdateMemories(workspaceId, memoryIds, updates): Promise<Record<string, unknown>>`
Batch-update multiple memories.

---

## Cross-Encoder Reranking

### `client.crossEncoderRerank(query, candidates, opts?): Promise<Record<string, unknown>[]>`
Re-rank candidates using the MCP cross-encoder server.

**`CrossEncoderRerankOptions`** `{ contentKey? (default "memory_content"), topK? (default 20) }`

---

## Real-Time Change Events

### `client.deltaSync: DeltaSync`

Lazy-initialized `DeltaSync` instance for real-time change-event polling. Provides callback-driven observation of inserts, updates, and deletes across SpacetimeDB tables.

```typescript
client.deltaSync.on("memory", "insert", (event) => console.log("New memory:", event));
client.deltaSync.on("kg_node", "*", (event) => console.log("Graph change:", event));
client.deltaSync.start();
```

> **See the [DeltaSync API](./delta_sync.md) reference for full method documentation.**

---

## Type Interfaces

```typescript
interface MemoryRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  content: string;
  summary: string;
  memory_type: string;
  confidence: number;
  is_active: boolean;
  tier: string;
  strength: number;
  access_count: number;
  trust_score: number;
  created_at: number;
  updated_at: number;
}

interface Workspace {
  id: string;
  name: string;
  description?: string;
  created_at?: number;
}

interface KGNodeRecord {
  id: string;
  workspace_id: string;
  label: string;
  node_type: string;
  summary?: string;
  metadata_json?: string;
  created_at?: number;
}

interface KGEdgeRecord {
  id: string;
  workspace_id: string;
  source_node_id: string;
  target_node_id: string;
  relation: string;
  weight: number;
  source?: string;
  metadata_json?: string;
  created_at?: number;
}

interface NoteRecord {
  id: string;
  workspace_id: string;
  title: string;
  content: string;
  note_date: string;
  is_active?: boolean;
  created_at?: number;
  updated_at?: number;
}

interface TagRecord {
  id: string;
  workspace_id: string;
  name: string;
  color?: string;
}

interface FactRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  content: string;
  fact_type?: string;
  confidence?: number;
  created_at?: number;
}

interface SessionRecord {
  id: string;
  workspace_id: string;
  name?: string;
  is_active?: boolean;
  created_at?: number;
}

interface PeerRecord {
  id: string;
  workspace_id: string;
  name: string;
  peer_type: string;
  metadata: string;
  created_at: number;
  updated_at: number;
}

interface SpaceMemberRecord {
  id: string;
  workspace_id: string;
  peer_id: string;
  permission: string;
  joined_at?: number;
}

interface MentalModelRecord {
  id: string;
  workspace_id: string;
  name: string;
  content: string;
  status?: string;
  confidence?: number;
  created_at?: number;
}

interface SearchResult {
  id: string;
  entity_id: string;
  entity_type: string;
  content: string;
  score: number;
  strategy: string;
  memory_content?: string;
  node_label?: string;
  context_json?: string;
  created_at?: number;
}

interface CrossLinkResult {
  linksCreated: number;
  pairsChecked: number;
}

interface LintResult {
  orphans: number;
  total: number;
}

interface StoreAnswerResult {
  note: { id: string; title: string };
  entities: string[];
  links: number;
}

interface OverviewResult {
  workspaceId: string;
  memories: number;
  kgNodes: number;
  kgEdges: number;
  notes: number;
}

interface ExportResult {
  markdown: string;
}
```
