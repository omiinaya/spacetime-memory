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
    let now = now_micros();
    let id = uuid_v4();

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
    let now = now_micros();
    let id = uuid_v4();

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
    let now = now_micros();

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
