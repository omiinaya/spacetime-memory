use spacetimedb::*;
use crate::auth::require_auth;
use crate::auth::require_admin;

use crate::{now_micros, uuid_v4};
use crate::workspace::check_space_access;

/// A node in the knowledge graph, representing a concept, entity, or document.
#[table(accessor = kg_node)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct KgNode {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub label: String,
    /// "code" | "concept" | "entity" | "document" | "topic"
    pub node_type: String,
    pub summary: String,
    /// JSON metadata blob
    pub metadata_json: String,
    /// Memory ID that created this node (empty if created directly)
    pub source_memory_id: String,
    /// Community membership (0 = unassigned)
    pub community_id: u64,
    /// JSON array of f64 embeddings
    pub embedding_json: String,
    pub created_at: i64,
}

/// A directed, typed edge between two knowledge graph nodes.
/// Supports temporal versioning (Graphiti parity).
#[table(accessor = kg_edge)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct KgEdge {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub source_node_id: String,
    pub target_node_id: String,
    pub relation: String,
    pub weight: f64,
    /// "EXTRACTED" | "INFERRED" | "AMBIGUOUS"
    pub confidence: String,
    /// JSON metadata blob
    pub metadata_json: String,
    /// Memory ID that created this edge (empty if created directly)
    pub source_memory_id: String,
    pub created_at: i64,
    /// Temporal versioning (Graphiti parity)
    /// When this edge version became valid (micros)
    pub valid_at: i64,
    /// When this edge version became invalid (0 = still valid)
    pub invalid_at: i64,
    /// Version number (starts at 1)
    pub version: u32,
    /// Group UUID linking all versions of the same logical edge
    pub edge_group_id: String,
}

/// A community (cluster) grouping related nodes in the knowledge graph.
/// Uses u64 auto-increment primary key.
#[table(accessor = kg_community)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct KgCommunity {
    #[primary_key]
    pub id: u64,
    pub workspace_id: String,
    pub name: String,
    pub summary: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Node reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_node(
    ctx: &ReducerContext,
    workspace_id: String,
    label: String,
    node_type: String,
    summary: String,
    metadata_json: String,
    source_memory_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

    // Validate node_type
    match node_type.as_str() {
        "code" | "concept" | "entity" | "document" | "topic" => {}
        _ => {
            return Err(format!(
                "Invalid node_type '{}': must be 'code', 'concept', 'entity', 'document', or 'topic'",
                node_type
            ));
        }
    }

    let node = KgNode {
        id: id.clone(),
        workspace_id,
        label,
        node_type,
        summary,
        metadata_json: if metadata_json.is_empty() {
            String::from("{}")
        } else {
            metadata_json
        },
        source_memory_id,
        community_id: 0,
        embedding_json: String::from("[]"),
        created_at: now,
    };

    ctx.db.kg_node().insert(node);
    Ok(())
}

#[reducer]
pub fn delete_node(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let node = ctx
        .db
        .kg_node()
        .id()
        .find(&id)
        .ok_or_else(|| format!("KgNode '{}' not found", id))?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &node.workspace_id, &caller, "editor")?;

    ctx.db.kg_node().id().delete(&id);
    Ok(())
}

// ---------------------------------------------------------------------------
// Edge reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_edge(
    ctx: &ReducerContext,
    workspace_id: String,
    source_node_id: String,
    target_node_id: String,
    relation: String,
    weight: f64,
    confidence: String,
    metadata_json: String,
    source_memory_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

    // Validate confidence
    match confidence.as_str() {
        "EXTRACTED" | "INFERRED" | "AMBIGUOUS" => {}
        _ => {
            return Err(format!(
                "Invalid confidence '{}': must be 'EXTRACTED', 'INFERRED', or 'AMBIGUOUS'",
                confidence
            ));
        }
    }

    let edge = KgEdge {
        id: id.clone(),
        workspace_id,
        source_node_id,
        target_node_id,
        relation,
        weight,
        confidence,
        metadata_json: if metadata_json.is_empty() {
            String::from("{}")
        } else {
            metadata_json
        },
        source_memory_id,
        created_at: now,
        // Temporal fields — first version is valid immediately
        valid_at: now,
        invalid_at: 0,
        version: 1,
        edge_group_id: uuid_v4(ctx),
    };

    ctx.db.kg_edge().insert(edge);
    Ok(())
}

#[reducer]
pub fn delete_edge(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let edge = ctx
        .db
        .kg_edge()
        .id()
        .find(&id)
        .ok_or_else(|| format!("KgEdge '{}' not found", id))?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &edge.workspace_id, &caller, "editor")?;

    ctx.db.kg_edge().id().delete(&id);
    Ok(())
}

/// Update an edge by creating a new version (temporal diff tracking).
///
/// Invalidates the current edge (sets `invalid_at`) and creates a new edge
/// with the updated fields and incremented version number.  Both share the
/// same `edge_group_id` so they can be tracked as a version history.
///
/// If the edge identified by `edge_id` is already invalidated (`invalid_at != 0`),
/// the reducer finds the latest valid version with the same `edge_group_id`
/// and invalidates that one instead.
#[reducer]
pub fn update_edge(
    ctx: &ReducerContext,
    edge_id: String,
    relation: String,
    weight: f64,
    metadata_json: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();

    // Find the initial edge by ID
    let initial = ctx
        .db
        .kg_edge()
        .id()
        .find(&edge_id)
        .ok_or_else(|| format!("KgEdge '{}' not found", edge_id))?;

    check_space_access(ctx, &initial.workspace_id, &caller, "editor")?;

    let now = now_micros(ctx);

    // Find the latest valid version in this edge group
    // If the passed edge is already invalidated, find the current valid one
    let latest_edge_id = if initial.invalid_at != 0 {
        // Find the latest version with invalid_at == 0
        ctx.db
            .kg_edge()
            .iter()
            .filter(|e: &KgEdge| {
                e.edge_group_id == initial.edge_group_id && e.invalid_at == 0
            })
            .next()
            .map(|e| e.id.clone())
            .unwrap_or(edge_id)
    } else {
        edge_id
    };

    // Find and invalidate the current valid edge
    let mut current = ctx
        .db
        .kg_edge()
        .id()
        .find(&latest_edge_id)
        .ok_or_else(|| format!("KgEdge '{}' not found", latest_edge_id))?;

    current.invalid_at = now;
    ctx.db.kg_edge().id().update(current.clone());

    // Create a new edge version
    let new_id = uuid_v4(ctx);
    let new_edge = KgEdge {
        id: new_id,
        workspace_id: current.workspace_id,
        source_node_id: current.source_node_id,
        target_node_id: current.target_node_id,
        relation,
        weight,
        confidence: current.confidence,
        metadata_json: if metadata_json.is_empty() {
            String::from("{}")
        } else {
            metadata_json
        },
        source_memory_id: current.source_memory_id.clone(),
        created_at: now,
        valid_at: now,
        invalid_at: 0,
        version: current.version + 1,
        edge_group_id: current.edge_group_id,
    };

    ctx.db.kg_edge().insert(new_edge);
    Ok(())
}

/// Result table for `get_edge_history`.
#[table(accessor = edge_history_result, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct EdgeHistoryResult {
    #[primary_key]
    pub id: String,
    pub edge_id: String,
    pub workspace_id: String,
    pub source_node_id: String,
    pub target_node_id: String,
    pub relation: String,
    pub weight: f64,
    pub confidence: String,
    pub metadata_json: String,
    pub created_at: i64,
    pub valid_at: i64,
    pub invalid_at: i64,
    pub version: u32,
    pub edge_group_id: String,
}

/// Get all versions of an edge (temporal history).
///
/// Queries by `edge_group_id` and stores results in `edge_history_result`.
#[reducer]
pub fn get_edge_history(ctx: &ReducerContext, edge_group_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Require auth
    let _caller = ctx.sender().to_hex();

    for edge in ctx
        .db
        .kg_edge()
        .iter()
        .filter(|e: &KgEdge| e.edge_group_id == edge_group_id)
    {
        ctx.db.edge_history_result().insert(EdgeHistoryResult {
            id: uuid_v4(ctx),
            edge_id: edge.id,
            workspace_id: edge.workspace_id,
            source_node_id: edge.source_node_id,
            target_node_id: edge.target_node_id,
            relation: edge.relation,
            weight: edge.weight,
            confidence: edge.confidence,
            metadata_json: edge.metadata_json,
            created_at: edge.created_at,
            valid_at: edge.valid_at,
            invalid_at: edge.invalid_at,
            version: edge.version,
            edge_group_id: edge.edge_group_id,
        });
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Community reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_community(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    summary: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);

    let community = KgCommunity {
        id: 0, // auto-increment
        workspace_id,
        name,
        summary,
        created_at: now,
    };

    ctx.db.kg_community().insert(community);
    Ok(())
}

#[reducer]
pub fn assign_to_community(
    ctx: &ReducerContext,
    node_id: String,
    community_id: u64,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let mut node = ctx
        .db
        .kg_node()
        .id()
        .find(&node_id)
        .ok_or_else(|| format!("KgNode '{}' not found", node_id))?;

    node.community_id = community_id;
    ctx.db.kg_node().id().update(node);
    Ok(())
}

// ---------------------------------------------------------------------------
// Community detection (label propagation)
// ---------------------------------------------------------------------------

/// Detect communities via label propagation.
///
/// Each node adopts the most common `community_id` among its neighbors.
/// Iterates until convergence (or up to 10 rounds).  Unassigned nodes
/// (community_id = 0) are left alone — they must be seeded first via
/// `seed_communities` or manual assignment.
#[reducer]
pub fn detect_communities(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    const MAX_ITER: u32 = 10;

    // Pre-collect edges for the workspace (avoids repeated full-scan filtering)
    let edge_pairs: Vec<(String, String)> = ctx
        .db
        .kg_edge()
        .iter()
        .filter(|e| e.workspace_id == workspace_id)
        .map(|e| (e.source_node_id.clone(), e.target_node_id.clone()))
        .collect();

    for _iter in 0..MAX_ITER {
        let mut changed = false;

        let node_ids: Vec<String> = ctx
            .db
            .kg_node()
            .iter()
            .filter(|n| n.workspace_id == workspace_id && n.community_id > 0)
            .map(|n| n.id.clone())
            .collect();

        for nid in &node_ids {
            let node = match ctx.db.kg_node().id().find(nid) {
                Some(n) => n,
                None => continue,
            };
            let current_cid = node.community_id;

            // Collect neighbour community IDs
            let neighbour_cids: Vec<u64> = edge_pairs
                .iter()
                .filter(|(s, t)| s == nid || t == nid)
                .filter_map(|(s, t)| {
                    let neighbor_id = if s == nid { t } else { s };
                    ctx.db
                        .kg_node()
                        .id()
                        .find(neighbor_id)
                        .map(|n| n.community_id)
                })
                .filter(|cid| *cid > 0)
                .collect();

            if neighbour_cids.is_empty() {
                continue;
            }

            // Find most frequent community ID among neighbours
            let mut freq = std::collections::HashMap::new();
            for cid in &neighbour_cids {
                *freq.entry(*cid).or_insert(0u32) += 1;
            }
            let best = freq
                .into_iter()
                .max_by_key(|&(_, count)| count)
                .map(|(cid, _)| cid)
                .unwrap_or(0);

            if best > 0 && best != current_cid {
                let mut updated = node;
                updated.community_id = best;
                ctx.db.kg_node().id().update(updated);
                changed = true;
            }
        }

        if !changed {
            break;
        }
    }

    Ok(())
}

/// Seed isolated nodes that are connected via edges into new communities.
/// Nodes with community_id == 0 that have edges get a fresh auto-incrementing
/// community ID (from kg_community.next_id).  Nodes with no edges stay as 0.
#[reducer]
pub fn seed_communities(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let node_ids: Vec<(String, bool)> = ctx
        .db
        .kg_node()
        .iter()
        .filter(|n| n.workspace_id == workspace_id && n.community_id == 0)
        .map(|n| {
            let has_edge = ctx.db.kg_edge().iter().take(crate::MAX_RESULTS).any(|e| {
                e.workspace_id == workspace_id
                    && (e.source_node_id == n.id || e.target_node_id == n.id)
            });
            (n.id.clone(), has_edge)
        })
        .collect();

    for (nid, has_edge) in &node_ids {
        if !has_edge {
            continue;
        }
        // Create a fresh community for each isolated-group seed
        ctx.db.kg_community().insert(KgCommunity {
            id: 0, // auto-increment
            workspace_id: workspace_id.clone(),
            name: format!("Community {}", uuid_v4(ctx).get(..8).unwrap_or("new")),
            summary: String::new(),
            created_at: now,
        });

        // The auto-increment ID is assigned server-side; we need to read it back.
        // Simplest approach: scan for highest community_id and assign that.
        let new_id = ctx
            .db
            .kg_community()
            .iter()
            .filter(|c| c.workspace_id == workspace_id)
            .map(|c| c.id)
            .max()
            .unwrap_or(1);

        let mut node = match ctx.db.kg_node().id().find(nid) {
            Some(n) => n,
            None => continue,
        };
        node.community_id = new_id;
        ctx.db.kg_node().id().update(node);
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// PageRank centrality
// ---------------------------------------------------------------------------

/// PageRank results for knowledge-graph nodes.
#[table(accessor = pagerank_result, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PagerankResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub node_id: String,
    pub node_label: String,
    pub rank: f64,
    pub iteration: u32,
    pub computed_at: i64,
}

/// Compute PageRank centrality for all nodes in a workspace.
///
/// Uses the standard PageRank algorithm:
///   PR(n) = (1-d)/N + d * sum(PR(i) / out_degree(i))  for each incoming edge i->n
///
/// Converges when max change < 1e-6 or max_iterations reached.
#[reducer]
pub fn compute_pagerank(
    ctx: &ReducerContext,
    workspace_id: String,
    damping: f64,
    max_iterations: u32,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let d = if damping <= 0.0 || damping >= 1.0 {
        0.85
    } else {
        damping
    };
    let max_iter = if max_iterations == 0 {
        100
    } else {
        max_iterations
    };
    let convergence_threshold = 1e-6;

    // Collect all nodes in this workspace
    let nodes: Vec<(String, String)> = ctx
        .db
        .kg_node()
        .iter()
        .filter(|n| n.workspace_id == workspace_id)
        .map(|n| (n.id.clone(), n.label.clone()))
        .collect();

    let n_nodes = nodes.len();
    if n_nodes == 0 {
        return Ok(());
    }

    // Build a map from node_id -> index
    let mut node_index: std::collections::HashMap<String, usize> =
        std::collections::HashMap::new();
    for (i, (nid, _)) in nodes.iter().enumerate() {
        node_index.insert(nid.clone(), i);
    }

    // Collect all edges for this workspace
    let edges: Vec<(String, String)> = ctx
        .db
        .kg_edge()
        .iter()
        .filter(|e| e.workspace_id == workspace_id)
        .map(|e| (e.source_node_id.clone(), e.target_node_id.clone()))
        .collect();

    // Build adjacency: for each node, list of incoming edge source indices
    let mut incoming: Vec<Vec<usize>> = vec![Vec::new(); n_nodes];
    // and out-degree count for each node
    let mut out_degree: Vec<f64> = vec![0.0_f64; n_nodes];

    for (src, tgt) in &edges {
        if let (Some(&si), Some(&ti)) = (node_index.get(src), node_index.get(tgt)) {
            incoming[ti].push(si);
            out_degree[si] += 1.0;
        }
    }

    // Handle dangling nodes (out_degree == 0): treat them as linking to all nodes
    let dangling: Vec<usize> = (0..n_nodes)
        .filter(|i| out_degree[*i] == 0.0)
        .collect();

    // Initialise ranks uniformly
    let init_rank = 1.0 / n_nodes as f64;
    let mut rank: Vec<f64> = vec![init_rank; n_nodes];

    let mut actual_iterations = 0u32;
    for iter in 0..max_iter {
        actual_iterations = iter + 1;

        let mut new_rank: Vec<f64> = vec![(1.0 - d) / n_nodes as f64; n_nodes];

        // Compute contribution from dangling nodes (they link to everyone)
        let dangling_contrib: f64 = if !dangling.is_empty() {
            let sum: f64 = dangling.iter().map(|&i| rank[i]).sum();
            sum / n_nodes as f64
        } else {
            0.0
        };

        for i in 0..n_nodes {
            // Add dangling contribution
            new_rank[i] += d * dangling_contrib;

            // Add contributions from regular incoming edges
            let od = out_degree[i];
            if od > 0.0 {
                let contrib: f64 = incoming[i]
                    .iter()
                    .map(|&src_idx| rank[src_idx] / out_degree[src_idx])
                    .sum();
                new_rank[i] += d * contrib;
            }
        }

        // Check convergence
        let max_change: f64 = rank
            .iter()
            .zip(new_rank.iter())
            .map(|(a, b)| (a - b).abs())
            .fold(0.0_f64, f64::max);

        rank = new_rank;

        if max_change < convergence_threshold {
            break;
        }
    }

    // Normalise so sum = 1.0
    let sum: f64 = rank.iter().sum();
    if sum > 0.0 {
        for r in &mut rank {
            *r /= sum;
        }
    }

    // Clear previous PagerankResult entries for this workspace
    let old: Vec<_> = ctx
        .db
        .pagerank_result()
        .iter()
        .filter(|p| p.workspace_id == workspace_id)
        .collect();
    for p in old {
        ctx.db.pagerank_result().id().delete(&p.id);
    }

    // Insert new results
    for (i, (nid, nlabel)) in nodes.iter().enumerate() {
        ctx.db.pagerank_result().insert(PagerankResult {
            id: uuid_v4(ctx),
            workspace_id: workspace_id.clone(),
            node_id: nid.clone(),
            node_label: nlabel.clone(),
            rank: rank[i],
            iteration: actual_iterations,
            computed_at: now,
        });
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Hierarchical community dendrogram
// ---------------------------------------------------------------------------

/// A cluster in the community hierarchy dendrogram.
#[table(accessor = hierarchy_cluster)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct HierarchyCluster {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// JSON array of community IDs in this cluster
    pub community_ids: String,
    pub depth: u32,
}

/// A parent-child relationship in the community dendrogram.
#[table(accessor = community_hierarchy)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CommunityHierarchy {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub parent_cluster_id: String,
    pub child_cluster_id: String,
    pub similarity: f64,
    pub depth: u32,
}

/// Build a hierarchical community dendrogram using agglomerative clustering.
///
/// 1. Gets all communities and their node sets (via kg_node.community_id)
/// 2. Computes Jaccard similarity between community pairs
/// 3. Repeatedly merges the two most similar clusters
/// 4. Stops when only one cluster remains or max similarity < 0.1
#[reducer]
pub fn compute_community_hierarchy(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    // Get all communities in this workspace
    let communities: Vec<(u64, String)> = ctx
        .db
        .kg_community()
        .iter()
        .filter(|c| c.workspace_id == workspace_id)
        .map(|c| (c.id, c.name.clone()))
        .collect();

    if communities.is_empty() {
        return Ok(());
    }

    // Get node membership: community_id -> set of node_ids
    let mut community_node_sets: std::collections::HashMap<
        u64,
        std::collections::HashSet<String>,
    > = std::collections::HashMap::new();
    for node in ctx.db.kg_node().iter().take(crate::MAX_RESULTS) {
        if node.workspace_id != workspace_id {
            continue;
        }
        if node.community_id > 0 {
            community_node_sets
                .entry(node.community_id)
                .or_insert_with(std::collections::HashSet::new)
                .insert(node.id.clone());
        }
    }

    // Clear previous hierarchy data for this workspace
    let old_clusters: Vec<_> = ctx
        .db
        .hierarchy_cluster()
        .iter()
        .filter(|h| h.workspace_id == workspace_id)
        .collect();
    for h in old_clusters {
        ctx.db.hierarchy_cluster().id().delete(&h.id);
    }
    let old_edges: Vec<_> = ctx
        .db
        .community_hierarchy()
        .iter()
        .filter(|h| h.workspace_id == workspace_id)
        .collect();
    for h in old_edges {
        ctx.db.community_hierarchy().id().delete(&h.id);
    }

    // Initialise: each community is its own cluster
    #[derive(Clone)]
    #[allow(dead_code)]
    struct Cluster {
        id: String,
        #[allow(dead_code)]
        depth: u32,
        community_set: std::collections::HashSet<u64>,
    }

    let mut clusters: Vec<Cluster> = communities
        .iter()
        .map(|(cid, _)| {
            let mut set = std::collections::HashSet::new();
            set.insert(*cid);
            Cluster {
                id: uuid_v4(ctx),
                depth: 0,
                community_set: set,
            }
        })
        .collect();

    // Insert initial HierarchyCluster rows
    for cluster in &clusters {
        let community_ids: Vec<String> = cluster
            .community_set
            .iter()
            .map(|c| c.to_string())
            .collect();
        ctx.db.hierarchy_cluster().insert(HierarchyCluster {
            id: cluster.id.clone(),
            workspace_id: workspace_id.clone(),
            community_ids: format!("[{}]", community_ids.join(",")),
            depth: 0,
        });
    }

    // Helper: Jaccard similarity between two clusters
    let jaccard = |set_a: &std::collections::HashSet<u64>,
                   set_b: &std::collections::HashSet<u64>|
     -> f64 {
        let mut nodes_a = std::collections::HashSet::new();
        let mut nodes_b = std::collections::HashSet::new();
        let mut nodes_union = std::collections::HashSet::new();

        for cid in set_a {
            if let Some(ns) = community_node_sets.get(cid) {
                for n in ns {
                    nodes_a.insert(n.clone());
                    nodes_union.insert(n.clone());
                }
            }
        }
        for cid in set_b {
            if let Some(ns) = community_node_sets.get(cid) {
                for n in ns {
                    nodes_b.insert(n.clone());
                    nodes_union.insert(n.clone());
                }
            }
        }

        let intersection_size = nodes_a.intersection(&nodes_b).count();
        let union_size = nodes_union.len();

        if union_size == 0 {
            return 0.0;
        }
        intersection_size as f64 / union_size as f64
    };

    let similarity_threshold = 0.1;
    let mut depth = 0u32;

    // Agglomerative clustering
    while clusters.len() > 1 {
        depth += 1;

        // Find the two most similar clusters
        let mut best_i = 0;
        let mut best_j = 1;
        let mut best_sim = -1.0_f64;

        for i in 0..clusters.len() {
            for j in (i + 1)..clusters.len() {
                let sim = jaccard(&clusters[i].community_set, &clusters[j].community_set);
                if sim > best_sim {
                    best_sim = sim;
                    best_i = i;
                    best_j = j;
                }
            }
        }

        // If best similarity is below threshold, stop
        if best_sim < similarity_threshold {
            break;
        }

        // Merge the two most similar clusters
        let parent_set: std::collections::HashSet<u64> = clusters[best_i]
            .community_set
            .union(&clusters[best_j].community_set)
            .copied()
            .collect();

        let parent_id = uuid_v4(ctx);

        // Insert HierarchyCluster for the new merged cluster
        let community_ids: Vec<String> = parent_set.iter().map(|c| c.to_string()).collect();
        ctx.db.hierarchy_cluster().insert(HierarchyCluster {
            id: parent_id.clone(),
            workspace_id: workspace_id.clone(),
            community_ids: format!("[{}]", community_ids.join(",")),
            depth,
        });

        // Insert CommunityHierarchy edges for parent -> child relationships
        let child_clusters = [clusters[best_i].clone(), clusters[best_j].clone()];
        for child in &child_clusters {
            ctx.db
                .community_hierarchy()
                .insert(CommunityHierarchy {
                    id: uuid_v4(ctx),
                    workspace_id: workspace_id.clone(),
                    parent_cluster_id: parent_id.clone(),
                    child_cluster_id: child.id.clone(),
                    similarity: best_sim,
                    depth,
                });
        }

        // Remove the two old clusters and add the new parent
        if best_j > best_i {
            clusters.remove(best_j);
            clusters.remove(best_i);
        } else {
            clusters.remove(best_i);
            clusters.remove(best_j);
        }

        clusters.push(Cluster {
            id: parent_id,
            depth,
            community_set: parent_set,
        });
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Citation tracking — trace every graph entity to its source memory
// ---------------------------------------------------------------------------

/// A citation linking a KG entity (node or edge) to a source memory.
#[table(accessor = citation)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Citation {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub entity_id: String,
    pub entity_type: String,  // "node" or "edge"
    pub source_memory_id: String,
    pub description: String,
    pub created_at: i64,
}

/// Result table for get_citations queries.
#[table(accessor = citation_result, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CitationResult {
    #[primary_key]
    pub id: String,
    pub entity_id: String,
    pub entity_type: String,
    pub source_memory_id: String,
    pub description: String,
    pub created_at: i64,
}

#[reducer]
pub fn add_node_citation(
    ctx: &ReducerContext,
    workspace_id: String,
    node_id: String,
    memory_id: String,
    description: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);

    ctx.db.citation().insert(Citation {
        id: uuid_v4(ctx),
        workspace_id,
        entity_id: node_id,
        entity_type: "node".to_string(),
        source_memory_id: memory_id,
        description,
        created_at: now,
    });
    Ok(())
}

#[reducer]
pub fn add_edge_citation(
    ctx: &ReducerContext,
    workspace_id: String,
    edge_id: String,
    memory_id: String,
    description: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);

    ctx.db.citation().insert(Citation {
        id: uuid_v4(ctx),
        workspace_id,
        entity_id: edge_id,
        entity_type: "edge".to_string(),
        source_memory_id: memory_id,
        description,
        created_at: now,
    });
    Ok(())
}

#[reducer]
pub fn get_citations(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_id: String,
    entity_type: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "reader")?;
    let qid = uuid_v4(ctx);

    for c in ctx.db.citation().iter().take(crate::MAX_RESULTS) {
        if c.entity_id == entity_id && c.entity_type == entity_type && c.workspace_id == workspace_id {
            ctx.db.citation_result().insert(CitationResult {
                id: qid.clone(),
                entity_id: c.entity_id.clone(),
                entity_type: c.entity_type.clone(),
                source_memory_id: c.source_memory_id.clone(),
                description: c.description.clone(),
                created_at: c.created_at,
            });
        }
    }
    Ok(())
}
