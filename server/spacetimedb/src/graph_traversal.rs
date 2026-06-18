use spacetimedb::*;
use crate::auth::require_auth;

use crate::knowledge_graph::{kg_edge, kg_node};
use crate::{now_micros, uuid_v4};


/// Stores the result of a BFS/DFS traversal.
#[table(accessor = graph_traversal_result, public)]
#[derive(Debug, Clone)]
pub struct GraphTraversalResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Which query this belongs to (hash of the request)
    pub query_id: String,
    pub node_id: String,
    pub node_label: String,
    pub node_type: String,
    pub depth: u32,
    pub path_json: String,
    pub created_at: i64,
}

/// Stores the result of a shortest-path computation.
#[table(accessor = shortest_path_result, public)]
#[derive(Debug, Clone)]
pub struct ShortestPathResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub query_id: String,
    pub step_order: u32,
    pub node_id: String,
    pub node_label: String,
    pub node_type: String,
    pub created_at: i64,
}

/// BFS traversal from a start node up to max_depth.
/// Stores results in graph_traversal_result, keyed by query_id.
/// Callers read via SQL SELECT after reducer completes.
#[reducer]
pub fn graph_bfs(
    ctx: &ReducerContext,
    workspace_id: String,
    start_node_id: String,
    max_depth: u32,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let qid = format!("{:x}", ctx.timestamp.to_micros_since_unix_epoch());
    let now = now_micros(ctx);
    let max_depth = max_depth.min(6).max(1);

    // Pre-collect edges for this workspace to avoid repeated full scans
    let edge_pairs: Vec<(String, String)> = ctx
        .db
        .kg_edge()
        .iter()
        .filter(|e| e.workspace_id == workspace_id)
        .map(|e| (e.source_node_id.clone(), e.target_node_id.clone()))
        .collect();

    // Pre-collect node labels
    let node_map: std::collections::HashMap<String, (String, String)> = ctx
        .db
        .kg_node()
        .iter()
        .filter(|n| n.workspace_id == workspace_id)
        .map(|n| (n.id.clone(), (n.label.clone(), n.node_type.clone())))
        .collect();

    // BFS
    let mut visited: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut queue: std::collections::VecDeque<(String, u32, Vec<String>)> =
        std::collections::VecDeque::new();
    queue.push_back((start_node_id.clone(), 0, vec![start_node_id.clone()]));

    while let Some((current, depth, path)) = queue.pop_front() {
        if !visited.insert(current.clone()) {
            continue;
        }

        // Write this node to results
        let label_type = node_map.get(&current);
        let label = label_type.map(|(l, _)| l.as_str()).unwrap_or("");
        let ntype = label_type.map(|(_, t)| t.as_str()).unwrap_or("");
        let path_json = serde_json::to_string(&path).unwrap_or_default();

        ctx.db.graph_traversal_result().insert(GraphTraversalResult {
            id: uuid_v4(ctx),
            workspace_id: workspace_id.clone(),
            query_id: qid.clone(),
            node_id: current.clone(),
            node_label: label.to_string(),
            node_type: ntype.to_string(),
            depth,
            path_json,
            created_at: now,
        });

        if depth >= max_depth {
            continue;
        }

        // Explore neighbours (undirected — traverse both directions)
        let neighbours: Vec<String> = edge_pairs
            .iter()
            .filter(|(s, t)| s == &current || t == &current)
            .map(|(s, t)| if s == &current { t.clone() } else { s.clone() })
            .filter(|n| !visited.contains(n))
            .collect();

        for n in neighbours {
            let mut new_path = path.clone();
            new_path.push(n.clone());
            queue.push_back((n, depth + 1, new_path));
        }
    }

    Ok(())
}

/// Shortest path between two nodes via BFS.
/// Stores the result path in shortest_path_result, ordered by step_order.
#[reducer]
pub fn shortest_path(
    ctx: &ReducerContext,
    workspace_id: String,
    source_id: String,
    target_id: String,
    max_hops: u32,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let qid = format!("{:x}", ctx.timestamp.to_micros_since_unix_epoch());
    let now = now_micros(ctx);
    let max_hops = max_hops.min(12).max(1);

    // Pre-collect edges
    let edge_pairs: Vec<(String, String)> = ctx
        .db
        .kg_edge()
        .iter()
        .filter(|e| e.workspace_id == workspace_id)
        .map(|e| (e.source_node_id.clone(), e.target_node_id.clone()))
        .collect();

    // Pre-collect node labels
    let node_map: std::collections::HashMap<String, (String, String)> = ctx
        .db
        .kg_node()
        .iter()
        .filter(|n| n.workspace_id == workspace_id)
        .map(|n| (n.id.clone(), (n.label.clone(), n.node_type.clone())))
        .collect();

    // BFS for shortest path
    let mut visited: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut queue: std::collections::VecDeque<(String, u32, Vec<String>)> =
        std::collections::VecDeque::new();
    queue.push_back((source_id.clone(), 0, vec![source_id.clone()]));
    visited.insert(source_id.clone());

    let mut found_path: Option<Vec<String>> = None;

    while let Some((current, depth, path)) = queue.pop_front() {
        if current == target_id {
            found_path = Some(path);
            break;
        }

        if depth >= max_hops {
            continue;
        }

        let neighbours: Vec<String> = edge_pairs
            .iter()
            .filter(|(s, t)| s == &current || t == &current)
            .map(|(s, t)| if s == &current { t.clone() } else { s.clone() })
            .filter(|n| visited.insert(n.clone()))
            .collect();

        for n in neighbours {
            let mut new_path = path.clone();
            new_path.push(n.clone());
            queue.push_back((n, depth + 1, new_path));
        }
    }

    // Write results
    if let Some(path) = found_path {
        for (i, nid) in path.iter().enumerate() {
            let label_type = node_map.get(nid);
            let label = label_type.map(|(l, _)| l.as_str()).unwrap_or("");
            let ntype = label_type.map(|(_, t)| t.as_str()).unwrap_or("");

            ctx.db.shortest_path_result().insert(ShortestPathResult {
                id: uuid_v4(ctx),
                workspace_id: workspace_id.clone(),
                query_id: qid.clone(),
                step_order: i as u32,
                node_id: nid.clone(),
                node_label: label.to_string(),
                node_type: ntype.to_string(),
                created_at: now,
            });
        }
    }

    Ok(())
}

/// Get immediate neighbours of a node.
/// Stores results in graph_traversal_result with depth=1.
#[reducer]
pub fn get_neighbors(
    ctx: &ReducerContext,
    workspace_id: String,
    node_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let qid = format!("{:x}", ctx.timestamp.to_micros_since_unix_epoch());
    let now = now_micros(ctx);

    // Pre-collect node labels
    let node_map: std::collections::HashMap<String, (String, String)> = ctx
        .db
        .kg_node()
        .iter()
        .filter(|n| n.workspace_id == workspace_id)
        .map(|n| (n.id.clone(), (n.label.clone(), n.node_type.clone())))
        .collect();

    // Find all neighbours via edges
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    seen.insert(node_id.clone());

    for edge in ctx.db.kg_edge().iter() {
        if edge.workspace_id != workspace_id {
            continue;
        }
        let neighbor_id = if edge.source_node_id == node_id {
            edge.target_node_id.clone()
        } else if edge.target_node_id == node_id {
            edge.source_node_id.clone()
        } else {
            continue;
        };

        if !seen.insert(neighbor_id.clone()) {
            continue;
        }

        let label_type = node_map.get(&neighbor_id);
        let label = label_type.map(|(l, _)| l.as_str()).unwrap_or("");
        let ntype = label_type.map(|(_, t)| t.as_str()).unwrap_or("");

        ctx.db.graph_traversal_result().insert(GraphTraversalResult {
            id: uuid_v4(ctx),
            workspace_id: workspace_id.clone(),
            query_id: qid.clone(),
            node_id: neighbor_id,
            node_label: label.to_string(),
            node_type: ntype.to_string(),
            depth: 1,
            path_json: String::new(),
            created_at: now,
        });
    }

    Ok(())
}

// ── Pattern Detection: Bridge Nodes ──────────────────────────

/// A bridge node connects multiple communities — it's a cross-domain
/// concept that spans knowledge boundaries. High bridge scores indicate
/// important integrative concepts.
#[table(accessor = bridge_result, public)]
#[derive(Debug, Clone)]
pub struct BridgeResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub node_id: String,
    pub node_label: String,
    pub node_type: String,
    /// Number of distinct communities this node connects to
    pub community_count: u32,
    /// Bridge score 0.0–1.0: (community_count - 1) / total_communities
    /// Normalized so single-community nodes score 0.0
    pub bridge_score: f64,
    /// JSON array of community IDs this node touches
    pub community_ids_json: String,
    pub created_at: i64,
}

/// Detect bridge nodes — nodes that connect multiple communities.
///
/// A bridge node has edges whose endpoints belong to different communities,
/// or the node itself belongs to a different community than its neighbors.
///
/// * `workspace_id` — target workspace
/// * `limit` — max results (default 20)
/// * `min_communities` — minimum distinct communities to qualify (default 2)
#[reducer]
pub fn detect_bridge_nodes(
    ctx: &ReducerContext,
    workspace_id: String,
    limit: u32,
    min_communities: u32,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let limit = if limit == 0 { 20 } else { limit };
    let min_communities = if min_communities == 0 { 2 } else { min_communities };

    // Clear previous results
    let old: Vec<_> = ctx.db.bridge_result().iter()
        .filter(|r| r.workspace_id == workspace_id)
        .collect();
    for r in old {
        ctx.db.bridge_result().id().delete(&r.id);
    }

    use std::collections::{HashMap, HashSet};

    // Build node_id → community_id map
    let node_community: HashMap<String, u64> = ctx
        .db
        .kg_node()
        .iter()
        .filter(|n| n.workspace_id == workspace_id)
        .map(|n| (n.id.clone(), n.community_id))
        .collect();

    // Count total distinct communities (excluding 0 = unassigned)
    let total_communities: u64 = node_community
        .values()
        .filter(|&&c| c > 0)
        .collect::<HashSet<_>>()
        .len() as u64;

    if total_communities == 0 {
        return Ok(()); // No communities to bridge
    }

    // For each node, collect community IDs of its neighbors
    let mut node_communities: HashMap<String, HashSet<u64>> = HashMap::new();

    for edge in ctx.db.kg_edge().iter()
        .filter(|e| e.workspace_id == workspace_id)
    {
        let src_cid = node_community.get(&edge.source_node_id).copied().unwrap_or(0);
        let tgt_cid = node_community.get(&edge.target_node_id).copied().unwrap_or(0);

        if src_cid > 0 {
            node_communities
                .entry(edge.source_node_id.clone())
                .or_default()
                .insert(tgt_cid);
            // Also include the node's own community
            let own_cid = node_community.get(&edge.source_node_id).copied().unwrap_or(0);
            if own_cid > 0 {
                node_communities
                    .entry(edge.source_node_id.clone())
                    .or_default()
                    .insert(own_cid);
            }
        }

        if tgt_cid > 0 {
            node_communities
                .entry(edge.target_node_id.clone())
                .or_default()
                .insert(src_cid);
            let own_cid = node_community.get(&edge.target_node_id).copied().unwrap_or(0);
            if own_cid > 0 {
                node_communities
                    .entry(edge.target_node_id.clone())
                    .or_default()
                    .insert(own_cid);
            }
        }
    }

    // Score and filter bridge nodes
    let mut bridges: Vec<(String, String, String, u32, f64, String)> = Vec::new();

    for (node_id, communities) in &node_communities {
        let count = communities.len() as u32;
        if count < min_communities {
            continue;
        }

        let bridge_score = if total_communities > 1 {
            (count as f64 - 1.0) / (total_communities as f64 - 1.0)
        } else {
            0.0
        };

        let node = ctx.db.kg_node().id().find(node_id);
        let label = node.as_ref().map(|n| n.label.clone()).unwrap_or_default();
        let ntype = node.as_ref().map(|n| n.node_type.clone()).unwrap_or_default();

        let cids: Vec<u64> = communities.iter().copied().collect();
        let cids_json = serde_json::to_string(&cids).unwrap_or_else(|_| "[]".to_string());

        bridges.push((
            node_id.clone(),
            label,
            ntype,
            count,
            bridge_score,
            cids_json,
        ));
    }

    bridges.sort_by(|a, b| b.4.partial_cmp(&a.4).unwrap_or(std::cmp::Ordering::Equal));
    bridges.truncate(limit as usize);

    for (node_id, label, ntype, count, score, cids_json) in &bridges {
        ctx.db.bridge_result().insert(BridgeResult {
            id: uuid_v4(ctx),
            workspace_id: workspace_id.clone(),
            node_id: node_id.clone(),
            node_label: label.clone(),
            node_type: ntype.clone(),
            community_count: *count,
            bridge_score: *score,
            community_ids_json: cids_json.clone(),
            created_at: now,
        });
    }

    Ok(())
}

// ── Knowledge Graph Statistics ───────────────────────────────

/// Summary statistics for a workspace's knowledge graph.
#[table(accessor = kg_stats_result, public)]
#[derive(Debug, Clone)]
pub struct KgStatsResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Total node count
    pub node_count: u64,
    /// Total edge count
    pub edge_count: u64,
    /// Number of distinct communities (excluding 0 = unassigned)
    pub community_count: u64,
    /// Nodes with community_id == 0 (unassigned / orphans)
    pub unassigned_nodes: u64,
    /// Nodes with zero edges (true orphans — no connections)
    pub orphan_nodes: u64,
    /// Average edges per node (edge_count / node_count, or 0)
    pub avg_degree: f64,
    /// Timestamp micros
    pub created_at: i64,
}

/// Compute summary statistics for a workspace's knowledge graph.
#[reducer]
pub fn compute_kg_stats(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    use std::collections::HashSet;

    // Node stats
    let nodes: Vec<_> = ctx
        .db
        .kg_node()
        .iter()
        .filter(|n| n.workspace_id == workspace_id)
        .collect();

    let node_count = nodes.len() as u64;

    // Collect community IDs and unassigned count
    let mut community_ids = HashSet::new();
    let mut unassigned_nodes: u64 = 0;
    for n in &nodes {
        if n.community_id > 0 {
            community_ids.insert(n.community_id);
        } else {
            unassigned_nodes += 1;
        }
    }

    // Edge stats
    let edges: Vec<_> = ctx
        .db
        .kg_edge()
        .iter()
        .filter(|e| e.workspace_id == workspace_id)
        .collect();

    let edge_count = edges.len() as u64;

    // Node degree: count edges per node
    let mut degree: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
    for e in &edges {
        *degree.entry(e.source_node_id.clone()).or_insert(0) += 1;
        *degree.entry(e.target_node_id.clone()).or_insert(0) += 1;
    }

    // Orphan nodes: nodes that appear in kg_node but have 0 edges
    let orphan_nodes = nodes.iter()
        .filter(|n| !degree.contains_key(&n.id))
        .count() as u64;

    let avg_degree = if node_count > 0 {
        (edge_count * 2) as f64 / node_count as f64
    } else {
        0.0
    };

    // Clear previous
    let old: Vec<_> = ctx.db.kg_stats_result().iter()
        .filter(|r| r.workspace_id == workspace_id)
        .collect();
    for r in old {
        ctx.db.kg_stats_result().id().delete(&r.id);
    }

    ctx.db.kg_stats_result().insert(KgStatsResult {
        id: uuid_v4(ctx),
        workspace_id,
        node_count,
        edge_count,
        community_count: community_ids.len() as u64,
        unassigned_nodes,
        orphan_nodes,
        avg_degree,
        created_at: now,
    });

    Ok(())
}
// ---------------------------------------------------------------------------
