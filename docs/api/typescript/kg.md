# TypeScript KG API

Knowledge graph — nodes, edges, traversal, communities, citations, and entity resolution.

```typescript
import { createNode, createEdge, shortestPath } from "spacetime-memory/kg";

await createNode(client, "ws-1", "Caroline", "entity", "A person");
await createEdge(client, "ws-1", nodeA, nodeB, "knows", 1.0);
const path = await shortestPath(client, "ws-1", nodeA, nodeB);
```

## Nodes & Edges

### `createNode(client, workspaceId, label, nodeType?, summary?, sourceMemoryId?, sourceDocumentId?)`

Creates a KG node (default `nodeType` `"entity"`).

### `createEdge(client, workspaceId, sourceNodeId, targetNodeId, relation, weight?)`

Creates a typed edge (default weight 1.0).

### `updateNode(client, nodeId, summary?, nodeType?)` / `deleteNode(client, nodeId)` / `getNode(client, nodeId)`

Node updates/deletion/reads.

### `updateEdge(client, edgeId, weight?)` / `deleteEdge(client, edgeId)`

Edge updates/deletion.

## Traversal

### `queryGraph(client, workspaceId, query?)`

Returns `KGNodeRecord[]` (optionally filtered by query).

### `getNeighbors(client, nodeId)` / `getNeighborsViaReducer(client, workspaceId, nodeId)`

Neighbor discovery (direct SQL vs reducer path).

### `graphBfs(client, workspaceId, startNodeId, maxDepth = 3)` / `bfs(client, workspaceId, startNodeId, maxDepth?)`

Breadth-first traversal.

### `shortestPath(client, workspaceId, sourceId, targetId, maxHops = 6)`

BFS shortest path between two nodes.

### `getEdgeHistory(client, edgeGroupId)`

Bi-temporal edge history (as-of queries).

## Communities & Analytics

### `detectCommunities(client, workspaceId)` / `seedCommunities(client, workspaceId)` / `getCommunity(client, communityId)` / `computeCommunityHierarchy(client, workspaceId)` / `detectBridgeNodes(client, workspaceId, limit?, minCommunities?)` / `computePageRank(client, workspaceId, damping?, maxIterations?)` / `computeKgStats(client, workspaceId)`

Community detection, bridge-node analysis, PageRank, and KG statistics.

## Citations

### `addNodeCitation(client, workspaceId, nodeId, memoryId, description?)` / `addEdgeCitation(client, workspaceId, edgeId, memoryId, description?)` / `getCitations(client, workspaceId, entityId, entityType?)`

Source citation tracking on nodes/edges.

## Entity Resolution

### `resolveEntity(client, workspaceId, name)` / `createEntityLink(client, workspaceId, name, entityType, description?)` / `addAlias(client, entityLinkId, alias)` / `extractEntities(client, workspaceId, content)` / `extractEntitiesLlm(client, workspaceId, content)`

Canonical entity resolution with alias support and LLM extraction.

---

See also: [memories](memories.md), [types](types.md)
