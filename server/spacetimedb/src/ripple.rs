use spacetimedb::*;
use crate::auth::require_auth;

use crate::knowledge_graph::{kg_node, KgNode};
use crate::{now_micros, uuid_v7};

// ---------------------------------------------------------------------------
// RippleImpact — tracks which KG nodes are impacted by a source change
// ---------------------------------------------------------------------------
//
// When a source (document, memory, or note) is updated, any KG node that was
// *informed by* that source may need re-summarization. This table captures
// those detected impacts so a curator or automated pipeline can process them.
// ---------------------------------------------------------------------------

/// A detected ripple impact: one KG node that needs re-summarization because
/// one of its informing sources changed.
#[table(accessor = ripple_impact)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct RippleImpact {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The type of source that was updated: "document", "memory", "note"
    pub source_type: String,
    /// The ID of the source that was updated (document_id, memory_id, note_id)
    pub source_id: String,
    /// The ID of the KG node that was informed by this source
    pub node_id: String,
    /// The label of the affected KG node (denormalized for query convenience)
    pub node_label: String,
    /// Status: "pending" | "resolved" | "dismissed"
    pub status: String,
    /// When this impact was first detected (micros)
    pub discovered_at: i64,
    /// When this impact was resolved/dismissed (micros; 0 = not yet)
    pub resolved_at: i64,
}

/// Result table for `get_ripple_impacts`.
#[table(accessor = ripple_impact_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct RippleImpactResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// JSON array of RippleImpact objects
    pub impacts_json: String,
    pub total_count: u64,
    pub pending_count: u64,
    pub queried_at: i64,
}

// ---------------------------------------------------------------------------
// Helpers (pure, testable)
// ---------------------------------------------------------------------------

/// Find all KG nodes in a workspace that reference a given source document.
///
/// Scans `KgNode.source_document_id` for exact match.
/// Pure function — no STDB dependency beyond iterating the table.
fn find_nodes_by_document<'a>(
    nodes: impl Iterator<Item = &'a KgNode>,
    workspace_id: &str,
    document_id: &str,
) -> Vec<&'a KgNode> {
    nodes
        .filter(|n| n.workspace_id == workspace_id && n.source_document_id == document_id)
        .collect()
}

/// Find all KG nodes in a workspace that reference a given memory.
///
/// Scans `KgNode.source_memory_id` for exact match.
fn find_nodes_by_memory<'a>(
    nodes: impl Iterator<Item = &'a KgNode>,
    workspace_id: &str,
    memory_id: &str,
) -> Vec<&'a KgNode> {
    nodes
        .filter(|n| n.workspace_id == workspace_id && n.source_memory_id == memory_id)
        .collect()
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

/// Detect ripple impact when a source is updated.
///
/// Scans all KG nodes in the workspace and finds those whose
/// `source_document_id` or `source_memory_id` matches the given source.
/// Creates a `RippleImpact` record for each match if one does not already
/// exist with status "pending".
///
/// Arguments:
/// - `workspace_id` — target workspace
/// - `source_type` — "document" | "memory" | "note"
/// - `source_id` — the ID of the source that was updated
#[reducer]
pub fn detect_ripple_impact(
    ctx: &ReducerContext,
    workspace_id: String,
    source_type: String,
    source_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    // Validate source_type
    match source_type.as_str() {
        "document" | "memory" | "note" => {}
        _ => {
            return Err(format!(
                "Invalid source_type '{}': must be 'document', 'memory', or 'note'",
                source_type
            ));
        }
    }

    // Build the node pool once — it must outlive the borrows below
    let node_pool: Vec<KgNode> = ctx.db.kg_node().workspace_id().filter(&workspace_id).take(crate::MAX_RESULTS).collect();

    // Find matching nodes based on source_type
    let affected_nodes: Vec<&KgNode> = match source_type.as_str() {
        "document" => {
            find_nodes_by_document(node_pool.iter(), &workspace_id, &source_id)
        }
        "memory" => {
            find_nodes_by_memory(node_pool.iter(), &workspace_id, &source_id)
        }
        _ => return Ok(()),
    };

    if affected_nodes.is_empty() {
        log::info!(
            "detect_ripple_impact: no nodes affected by {} {} in workspace {}",
            source_type,
            &source_id[..16.min(source_id.len())],
            &workspace_id[..16.min(workspace_id.len())],
        );
        return Ok(());
    }

    // Pre-collect existing pending ripple IDs to avoid duplicates
    let existing_pending: std::collections::HashSet<String> = ctx
        .db
        .ripple_impact()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
        .filter(|r: &RippleImpact| {
            r.source_id == source_id
                && r.status == "pending"
        })
        .map(|r| r.node_id.clone())
        .collect();

    let mut created_count: u64 = 0;
    for node in &affected_nodes {
        if existing_pending.contains(&node.id) {
            continue; // skip duplicate
        }

        // Mark the node as stale
        if node.stale_since == 0 {
            // Only update if it wasn't already stale
            let mut updatable = (*node).clone();
            updatable.stale_since = now;
            ctx.db.kg_node().id().update(updatable.clone());
        }

        let impact = RippleImpact {
            id: uuid_v7(ctx),
            workspace_id: workspace_id.clone(),
            source_type: source_type.clone(),
            source_id: source_id.clone(),
            node_id: node.id.clone(),
            node_label: node.label.clone(),
            status: String::from("pending"),
            discovered_at: now,
            resolved_at: 0,
        };
        ctx.db.ripple_impact().insert(impact);
        created_count += 1;
    }

    log::info!(
        "detect_ripple_impact: created {} new impacts for {} {} in workspace {}",
        created_count,
        source_type,
        &source_id[..16.min(source_id.len())],
        &workspace_id[..16.min(workspace_id.len())],
    );

    Ok(())
}

/// Query all ripple impacts for a given workspace and optional source.
///
/// If `source_id` is non-empty, filters to impacts for that specific source.
/// Results are stored in `ripple_impact_result` for the caller to read via SQL.
#[reducer]
pub fn get_ripple_impacts(
    ctx: &ReducerContext,
    workspace_id: String,
    source_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    let impacts: Vec<RippleImpact> = ctx
        .db
        .ripple_impact()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS * 5)
        .filter(|r: &RippleImpact| {
            source_id.is_empty() || r.source_id == source_id
        })
        .collect();

    let total = impacts.len() as u64;
    let pending = impacts.iter().filter(|r| r.status == "pending").count() as u64;
    let now = now_micros(ctx);

    // Pre-cleanup: remove stale results for this workspace_id
    for old in ctx.db.ripple_impact_result().iter()
        .filter(|r| r.workspace_id == workspace_id)
        .collect::<Vec<_>>()
    {
        ctx.db.ripple_impact_result().id().delete(&old.id);
    }
    let result = RippleImpactResult {
        id: uuid_v7(ctx),
        workspace_id,
        impacts_json: serde_json::to_string(&impacts).unwrap_or_else(|_| "[]".to_string()),
        total_count: total,
        pending_count: pending,
        queried_at: now,
    };

    ctx.db.ripple_impact_result().insert(result);
    Ok(())
}

/// Resolve a ripple impact (mark as resolved — node has been re-summarized).
#[reducer]
pub fn resolve_ripple_impact(
    ctx: &ReducerContext,
    impact_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let mut impact = ctx
        .db
        .ripple_impact()
        .id()
        .find(&impact_id)
        .ok_or_else(|| format!("RippleImpact '{}' not found", impact_id))?;

    if impact.status != "pending" {
        return Err(format!(
            "RippleImpact '{}' is not pending (current status: {})",
            impact_id, impact.status
        ));
    }

    impact.status = String::from("resolved");
    impact.resolved_at = now;
    ctx.db.ripple_impact().id().update(impact.clone());

    // Also clear the stale flag on the node if it's still marked
    if let Some(mut node) = ctx.db.kg_node().id().find(&impact.node_id) {
        if node.stale_since > 0 {
            node.stale_since = 0;
            ctx.db.kg_node().id().update(node);
        }
    }

    Ok(())
}

/// Dismiss a ripple impact (mark as dismissed — no re-summarization needed).
#[reducer]
pub fn dismiss_ripple_impact(
    ctx: &ReducerContext,
    impact_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let mut impact = ctx
        .db
        .ripple_impact()
        .id()
        .find(&impact_id)
        .ok_or_else(|| format!("RippleImpact '{}' not found", impact_id))?;

    if impact.status != "pending" {
        return Err(format!(
            "RippleImpact '{}' is not pending (current status: {})",
            impact_id, impact.status
        ));
    }

    impact.status = String::from("dismissed");
    impact.resolved_at = now;
    ctx.db.ripple_impact().id().update(impact);

    // Dismissal does NOT clear the stale flag — the curator must intentionally
    // call resolve (which implies content was updated) or re-mark as stale later.

    Ok(())
}

/// Query all stale KG nodes in a workspace (nodes with `stale_since > 0`).
///
/// Results are stored in `stale_nodes_result` for SQL query.
#[reducer]
pub fn get_stale_nodes(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    let stale_nodes: Vec<KgNode> = ctx
        .db
        .kg_node()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|n: &KgNode| n.workspace_id == workspace_id && n.stale_since > 0)
        .collect();

    let result_id = uuid_v7(ctx);
    // Pre-cleanup: remove stale results for this workspace_id
    for old in ctx.db.stale_nodes_result().iter()
        .filter(|r| r.workspace_id == workspace_id)
        .collect::<Vec<_>>()
    {
        ctx.db.stale_nodes_result().id().delete(&old.id);
    }
    let result = StaleNodesResult {
        id: result_id,
        workspace_id: workspace_id.clone(),
        nodes_json: serde_json::to_string(&stale_nodes).unwrap_or_else(|_| "[]".to_string()),
        total_count: stale_nodes.len() as u64,
        queried_at: now,
    };
    ctx.db.stale_nodes_result().insert(result);
    Ok(())
}

/// Mark a KG node as stale (or clear the stale flag) directly.
///
/// Used by SDK compounder workflows (`mark_stale_for_source`,
/// `clear_stale_flag`) that compute ripple sets client-side and then
/// set per-node stale state. When `stale` is true and the node is not
/// already stale, `stale_since` is set to now; when false, it is reset to 0.
#[reducer]
pub fn set_node_stale(ctx: &ReducerContext, node_id: String, stale: bool) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let mut node = ctx
        .db
        .kg_node()
        .id()
        .find(&node_id)
        .ok_or_else(|| format!("set_node_stale: node '{}' not found", node_id))?;
    if stale {
        if node.stale_since == 0 {
            node.stale_since = now;
        }
    } else {
        node.stale_since = 0;
    }
    ctx.db.kg_node().id().update(node);
    Ok(())
}

/// Result table for `get_stale_nodes`.
#[table(accessor = stale_nodes_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct StaleNodesResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// JSON array of KgNode objects
    pub nodes_json: String,
    pub total_count: u64,
    pub queried_at: i64,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ---- find_nodes_by_document ----

    #[test]
    fn test_find_nodes_by_document_matches() {
        let nodes = vec![
            KgNode {
                id: "n1".into(),
                workspace_id: "ws-1".into(),
                label: "EntityA".into(),
                node_type: "entity".into(),
                summary: "".into(),
                metadata_json: "{}".into(),
                source_memory_id: "".into(),
                community_id: 0,
                embedding_json: "[]".into(),
                created_at: 1000,
                source_document_id: "doc-1".into(),
                stale_since: 0,
            },
            KgNode {
                id: "n2".into(),
                workspace_id: "ws-1".into(),
                label: "EntityB".into(),
                node_type: "entity".into(),
                summary: "".into(),
                metadata_json: "{}".into(),
                source_memory_id: "".into(),
                community_id: 0,
                embedding_json: "[]".into(),
                created_at: 1001,
                source_document_id: "doc-2".into(),
                stale_since: 0,
            },
        ];

        let found = find_nodes_by_document(nodes.iter(), "ws-1", "doc-1");
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].id, "n1");
    }

    #[test]
    fn test_find_nodes_by_document_no_match() {
        let nodes = vec![];
        let found = find_nodes_by_document(nodes.iter(), "ws-1", "nonexistent");
        assert!(found.is_empty());
    }

    #[test]
    fn test_find_nodes_by_document_wrong_workspace() {
        let nodes = vec![
            KgNode {
                id: "n1".into(),
                workspace_id: "ws-2".into(),
                label: "Entity".into(),
                node_type: "entity".into(),
                summary: "".into(),
                metadata_json: "{}".into(),
                source_memory_id: "".into(),
                community_id: 0,
                embedding_json: "[]".into(),
                created_at: 1000,
                source_document_id: "doc-1".into(),
                stale_since: 0,
            },
        ];
        let found = find_nodes_by_document(nodes.iter(), "ws-1", "doc-1");
        assert!(found.is_empty(), "different workspace should not match");
    }

    // ---- find_nodes_by_memory ----

    #[test]
    fn test_find_nodes_by_memory_matches() {
        let nodes = vec![
            KgNode {
                id: "n1".into(),
                workspace_id: "ws-1".into(),
                label: "EntityA".into(),
                node_type: "entity".into(),
                summary: "".into(),
                metadata_json: "{}".into(),
                source_memory_id: "mem-1".into(),
                community_id: 0,
                embedding_json: "[]".into(),
                created_at: 1000,
                source_document_id: "".into(),
                stale_since: 0,
            },
        ];
        let found = find_nodes_by_memory(nodes.iter(), "ws-1", "mem-1");
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].id, "n1");
    }

    #[test]
    fn test_find_nodes_by_memory_empty() {
        let nodes = vec![];
        let found = find_nodes_by_memory(nodes.iter(), "ws-1", "mem-1");
        assert!(found.is_empty());
    }
}
