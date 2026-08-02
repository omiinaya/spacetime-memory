/**
 * Knowledge graph — nodes, edges, communities.
 */
import type { ClientLike, KGNodeRecord, KGEdgeRecord } from "./types";

export async function createNode(client: ClientLike, workspaceId: string, label: string, nodeType?: string, summary?: string, sourceMemoryId?: string, sourceDocumentId?: string): Promise<void> {
  await client._call("create_node", [workspaceId, label, nodeType ?? "concept", summary ?? "", "{}", sourceMemoryId ?? "", sourceDocumentId ?? ""]);
  const content = summary ? `${label}: ${summary}` : label;
  const emb = await client._embed(content);
  if (emb.length > 0) {
    const nodes = await client._sqlExec("SELECT id FROM kg_node WHERE workspace_id = :ws AND label = :label", { ws: workspaceId, label });
    if (nodes.length > 0) {
      await client._call("index_entity", [workspaceId, "node", nodes[nodes.length - 1].id as string, content, JSON.stringify(emb)]);
    }
  }
}

export async function createEdge(client: ClientLike, workspaceId: string, sourceNodeId: string, targetNodeId: string, relation: string, weight?: number): Promise<void> {
  return client._call("create_edge", [workspaceId, sourceNodeId, targetNodeId, relation, weight ?? 1.0, "EXTRACTED", "{}"]);
}

export async function queryGraph(client: ClientLike, workspaceId: string, query?: string): Promise<KGNodeRecord[]> {
  if (query) {
    const rows = await client._sqlExec("SELECT * FROM kg_node WHERE workspace_id = :ws", { ws: workspaceId });
    const q = query.toLowerCase();
    return (rows as KGNodeRecord[]).filter(r => String(r.label ?? "").toLowerCase().includes(q));
  }
  return (await client._sqlExec("SELECT * FROM kg_node WHERE workspace_id = :ws", { ws: workspaceId })) as KGNodeRecord[];
}

export async function getNeighbors(client: ClientLike, nodeId: string): Promise<KGEdgeRecord[]> {
  return (await client._sqlExec(
    "SELECT source_node_id, target_node_id, relation, weight FROM kg_edge WHERE source_node_id = :nid OR target_node_id = :nid",
    { nid: nodeId },
  )) as KGEdgeRecord[];
}

export async function updateNode(client: ClientLike, nodeId: string, summary?: string, nodeType?: string): Promise<void> {
  await client._call("update_node", [nodeId, summary ?? "", nodeType ?? ""]);
}

export async function deleteNode(client: ClientLike, nodeId: string): Promise<void> {
  return client._call("delete_node", [nodeId]);
}

export async function updateEdge(client: ClientLike, edgeId: string, weight?: number): Promise<void> {
  await client._call("update_edge", [edgeId, weight ?? 1.0]);
}

export async function deleteEdge(client: ClientLike, edgeId: string): Promise<void> {
  return client._call("delete_edge", [edgeId]);
}

export async function getNode(client: ClientLike, nodeId: string): Promise<Record<string, unknown>[]> {
  return client._sqlExec("SELECT * FROM kg_node WHERE id = :nid", { nid: nodeId });
}

export async function getNeighborsViaReducer(client: ClientLike, workspaceId: string, nodeId: string): Promise<void> {
  return client._call("get_neighbors", [workspaceId, nodeId]);
}

export async function graphBfs(client: ClientLike, workspaceId: string, startNodeId: string, maxDepth: number = 3): Promise<Record<string, unknown>[]> {
  await client._call("graph_bfs", [workspaceId, startNodeId, maxDepth]);
  return await client._sqlExec("SELECT * FROM graph_traversal_result WHERE workspace_id = :ws", { ws: workspaceId });
}

export async function bfs(client: ClientLike, workspaceId: string, startNodeId: string, maxDepth?: number): Promise<Record<string, unknown>[]> {
  await client._call("graph_bfs", [workspaceId, startNodeId, maxDepth ?? 5]);
  return await client._sqlExec("SELECT * FROM bfs_result WHERE workspace_id = :ws", { ws: workspaceId });
}

export async function shortestPath(client: ClientLike, workspaceId: string, sourceId: string, targetId: string, maxHops: number = 6): Promise<Record<string, unknown>[]> {
  await client._call("shortest_path", [workspaceId, sourceId, targetId, maxHops]);
  const rows = await client._sqlExec("SELECT * FROM shortest_path_result WHERE workspace_id = :ws", { ws: workspaceId });
  return (rows as Record<string, unknown>[]).sort((a, b) => Number(a.step_order ?? 0) - Number(b.step_order ?? 0));
}

export async function getEdgeHistory(client: ClientLike, edgeGroupId: string): Promise<Record<string, unknown>[]> {
  await client._call("get_edge_history", [edgeGroupId]);
  return await client._sqlExec("SELECT * FROM edge_history_result WHERE edge_group_id = :egid", { egid: edgeGroupId });
}

export async function addNodeCitation(client: ClientLike, workspaceId: string, nodeId: string, memoryId: string, description?: string): Promise<void> {
  return client._call("add_node_citation", [workspaceId, nodeId, memoryId, description ?? ""]);
}

export async function addEdgeCitation(client: ClientLike, workspaceId: string, edgeId: string, memoryId: string, description?: string): Promise<void> {
  return client._call("add_edge_citation", [workspaceId, edgeId, memoryId, description ?? ""]);
}

export async function getCitations(client: ClientLike, workspaceId: string, entityId: string, entityType?: string): Promise<Record<string, unknown>[]> {
  await client._call("get_citations", [workspaceId, entityId, entityType ?? "node"]);
  return await client._sqlExec("SELECT * FROM citation_result WHERE entity_id = :eid AND entity_type = :etype", { eid: entityId, etype: entityType ?? "node" });
}

export async function detectBridgeNodes(client: ClientLike, workspaceId: string, limit?: number, minCommunities?: number): Promise<Record<string, unknown>[]> {
  await client._call("detect_bridge_nodes", [workspaceId, limit ?? 20, minCommunities ?? 2]);
  const rows = await client._sqlExec("SELECT * FROM bridge_result WHERE workspace_id = :ws", { ws: workspaceId });
  return (rows as Record<string, unknown>[]).sort((a, b) => Number(b.bridge_score ?? 0) - Number(a.bridge_score ?? 0));
}

export async function computePageRank(client: ClientLike, workspaceId: string, damping?: number, maxIterations?: number): Promise<void> {
  return client._call("compute_pagerank", [workspaceId, damping ?? 0.85, maxIterations ?? 100]);
}

export async function computeKgStats(client: ClientLike, workspaceId: string): Promise<Record<string, unknown> | null> {
  await client._call("compute_kg_stats", [workspaceId]);
  const rows = await client._sqlExec("SELECT * FROM kg_stats_result WHERE workspace_id = :ws", { ws: workspaceId });
  return rows.length > 0 ? rows[0] : null;
}

export async function computeCommunityHierarchy(client: ClientLike, workspaceId: string): Promise<void> {
  return client._call("compute_community_hierarchy", [workspaceId]);
}

export async function detectCommunities(client: ClientLike, workspaceId: string): Promise<void> {
  return client._call("detect_communities", [workspaceId]);
}

export async function seedCommunities(client: ClientLike, workspaceId: string): Promise<void> {
  return client._call("seed_communities", [workspaceId]);
}

export async function getCommunity(client: ClientLike, communityId: number): Promise<Record<string, unknown>[]> {
  await client._call("get_community", [communityId]);
  return client._sqlExec("SELECT * FROM community_result WHERE community_id = :cid", { cid: String(communityId) });
}

export async function resolveEntity(client: ClientLike, workspaceId: string, name: string): Promise<void> {
  return client._call("resolve_entity", [workspaceId, name]);
}

export async function extractEntities(client: ClientLike, workspaceId: string, content: string): Promise<void> {
  return client._call("extract_entities", [workspaceId, content]);
}

export async function extractEntitiesLlm(client: ClientLike, workspaceId: string, content: string): Promise<Record<string, unknown>[]> {
  await client._call("extract_entities", [workspaceId, content]);
  const rows = await client._query("entity_extraction_result", workspaceId);
  return rows.sort((a: any, b: any) => Number(b.created_at ?? 0) - Number(a.created_at ?? 0)).slice(0, 1);
}

export async function addAlias(client: ClientLike, entityLinkId: string, alias: string): Promise<void> {
  return client._call("add_alias", [entityLinkId, alias]);
}

export async function createEntityLink(client: ClientLike, workspaceId: string, name: string, entityType: string, description: string = ""): Promise<void> {
  return client._call("create_entity_link", [workspaceId, name, "[]", entityType, description]);
}
