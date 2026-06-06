use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// A node in the knowledge graph, representing a concept, entity, or document.
#[table(accessor = kg_node, public)]
#[derive(Debug, Clone)]
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
    /// Community membership (0 = unassigned)
    pub community_id: u64,
    /// JSON array of f64 embeddings
    pub embedding_json: String,
    pub created_at: i64,
}

/// A directed, typed edge between two knowledge graph nodes.
#[table(accessor = kg_edge, public)]
#[derive(Debug, Clone)]
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
    pub created_at: i64,
}

/// A community (cluster) grouping related nodes in the knowledge graph.
/// Uses u64 auto-increment primary key.
#[table(accessor = kg_community, public)]
#[derive(Debug, Clone)]
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
) -> Result<(), String> {
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
        community_id: 0,
        embedding_json: String::from("[]"),
        created_at: now,
    };

    ctx.db.kg_node().insert(node);
    Ok(())
}

#[reducer]
pub fn delete_node(ctx: &ReducerContext, id: String) -> Result<(), String> {
    ctx.db
        .kg_node()
        .id()
        .find(&id)
        .ok_or_else(|| format!("KgNode '{}' not found", id))?;

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
) -> Result<(), String> {
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
        created_at: now,
    };

    ctx.db.kg_edge().insert(edge);
    Ok(())
}

#[reducer]
pub fn delete_edge(ctx: &ReducerContext, id: String) -> Result<(), String> {
    ctx.db
        .kg_edge()
        .id()
        .find(&id)
        .ok_or_else(|| format!("KgEdge '{}' not found", id))?;

    ctx.db.kg_edge().id().delete(&id);
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
    let now = now_micros(ctx);
    let node_ids: Vec<(String, bool)> = ctx
        .db
        .kg_node()
        .iter()
        .filter(|n| n.workspace_id == workspace_id && n.community_id == 0)
        .map(|n| {
            let has_edge = ctx.db.kg_edge().iter().any(|e| {
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
