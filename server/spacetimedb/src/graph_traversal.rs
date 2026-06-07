use spacetimedb::*;

use crate::knowledge_graph::{kg_edge, kg_node};
use crate::{now_micros, uuid_v4};

use std::collections::{HashMap, HashSet, VecDeque};

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
