use spacetimedb::*;
use crate::auth::require_admin;

use crate::{now_micros, uuid_v4_uniq};

// Re-import table structs for direct manipulation in replicate_incoming
use crate::memory::{memory, Memory};
use crate::knowledge_graph::{kg_edge, kg_node, KgEdge, KgNode};
use crate::note::{note, Note};
use crate::profile::{profile, Profile};

/// Structure for incoming replication entries parsed from JSON.
#[derive(serde::Deserialize)]
struct IncomingEntry {
    id: String,
    table_name: String,
    operation: String,
    record_id: String,
    data_json: String,
    created_at: i64,
}

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// A replication peer — another SpacetimeDB instance to sync with.
#[table(accessor = replication_peer)]
#[derive(Debug, Clone, serde::Serialize)]
pub struct ReplicationPeer {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    /// Remote instance URL, e.g. "http://127.0.0.10:3001"
    pub remote_url: String,
    /// Remote database identity
    pub remote_db: String,
    /// Auth token for remote (if any)
    pub auth_token: String,
    pub is_active: bool,
    pub last_sync_at: i64,
    pub created_at: i64,
}

/// A log entry recording a mutation for replication.
#[table(accessor = replication_log)]
#[derive(Debug, Clone, serde::Serialize)]
pub struct ReplicationLog {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// The table that changed: "memory", "kg_node", "kg_edge", "note", "profile"
    pub table_name: String,
    /// The operation: "insert", "update", "delete"
    pub operation: String,
    /// Primary key of the changed record
    pub record_id: String,
    /// JSON-encoded snapshot of the record after the operation
    pub data_json: String,
    pub created_at: i64,
    pub synced: bool,
}

/// Result table for replication queries.
#[table(accessor = replication_result, public)]
#[derive(Debug, Clone, serde::Serialize)]
pub struct ReplicationResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub query_type: String, // "peers", "unsynced", "status"
    pub json_data: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

/// Add a new replication peer.
#[reducer]
pub fn add_replication_peer(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    remote_url: String,
    remote_db: String,
    auth_token: String,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v4_uniq(ctx, |id| ctx.db.replication_peer().id().find(id).is_none(), 3);

    let peer = ReplicationPeer {
        id: id.clone(),
        workspace_id,
        name,
        remote_url,
        remote_db,
        auth_token,
        is_active: true,
        last_sync_at: 0,
        created_at: now,
    };

    ctx.db.replication_peer().insert(peer);
    Ok(())
}

/// Remove a replication peer.
#[reducer]
pub fn remove_replication_peer(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let peer = ctx
        .db
        .replication_peer()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Replication peer '{}' not found", id))?;

    ctx.db.replication_peer().id().delete(&peer.id);
    Ok(())
}

/// List replication peers — stores result in the `replication_result` table.
#[reducer]
pub fn list_replication_peers(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let result_id = uuid_v4_uniq(ctx, |id| ctx.db.replication_result().id().find(id).is_none(), 3);

    // Query peers for this workspace
    let peers: Vec<_> = ctx
        .db
        .replication_peer()
        .iter().take(crate::MAX_RESULTS)
        .filter(|p| p.workspace_id == workspace_id)
        .collect();

    let json_data = serde_json::to_string(&peers).unwrap_or_else(|_| "[]".to_string());

    let result = ReplicationResult {
        id: result_id.clone(),
        workspace_id: workspace_id.clone(),
        query_type: "peers".to_string(),
        json_data,
        created_at: now,
    };

    ctx.db.replication_result().insert(result);

    // Clean up old results for the same workspace + query_type
    let old: Vec<_> = ctx
        .db
        .replication_result()
        .iter().take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id && r.query_type == "peers" && r.id != result_id)
        .collect();
    for r in old {
        ctx.db.replication_result().id().delete(&r.id);
    }

    Ok(())
}

/// Mark a range of log entries as synced.
/// `log_ids_json` — JSON array of log entry IDs to mark synced.
#[reducer]
pub fn mark_log_synced(ctx: &ReducerContext, log_ids_json: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let ids: Vec<String> = serde_json::from_str(&log_ids_json)
        .map_err(|e| format!("Invalid log_ids_json: {}", e))?;

    for id in &ids {
        if let Some(mut entry) = ctx.db.replication_log().id().find(id) {
            entry.synced = true;
            ctx.db.replication_log().id().update(entry);
        }
    }

    Ok(())
}

/// Get unsynced log entries — stores result in `replication_result` table.
#[reducer]
pub fn get_unsynced_entries(ctx: &ReducerContext, workspace_id: String, limit: i64) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let result_id = uuid_v4_uniq(ctx, |id| ctx.db.replication_result().id().find(id).is_none(), 3);

    let entries: Vec<_> = ctx
        .db
        .replication_log()
        .iter().take(crate::MAX_RESULTS)
        .filter(|e| e.workspace_id == workspace_id && !e.synced)
        .take(limit as usize)
        .collect();

    let json_data = serde_json::to_string(&entries).unwrap_or_else(|_| "[]".to_string());

    let result = ReplicationResult {
        id: result_id.clone(),
        workspace_id: workspace_id.clone(),
        query_type: "unsynced".to_string(),
        json_data,
        created_at: now,
    };

    ctx.db.replication_result().insert(result);

    // Clean up old unsynced results
    let old: Vec<_> = ctx
        .db
        .replication_result()
        .iter().take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id && r.query_type == "unsynced" && r.id != result_id)
        .collect();
    for r in old {
        ctx.db.replication_result().id().delete(&r.id);
    }

    Ok(())
}

/// Get replication status — stores result in `replication_result` table.
#[reducer]
pub fn get_replication_status(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let result_id = uuid_v4_uniq(ctx, |id| ctx.db.replication_result().id().find(id).is_none(), 3);

    let total_peers = ctx
        .db
        .replication_peer()
        .iter().take(crate::MAX_RESULTS)
        .filter(|p| p.workspace_id == workspace_id)
        .count();

    let active_peers = ctx
        .db
        .replication_peer()
        .iter().take(crate::MAX_RESULTS)
        .filter(|p| p.workspace_id == workspace_id && p.is_active)
        .count();

    let unsynced_count = ctx
        .db
        .replication_log()
        .iter().take(crate::MAX_RESULTS)
        .filter(|e| e.workspace_id == workspace_id && !e.synced)
        .count();

    let total_log_entries = ctx
        .db
        .replication_log()
        .iter().take(crate::MAX_RESULTS)
        .filter(|e| e.workspace_id == workspace_id)
        .count();

    let status = serde_json::json!({
        "workspace_id": workspace_id,
        "total_peers": total_peers,
        "active_peers": active_peers,
        "unsynced_count": unsynced_count,
        "total_log_entries": total_log_entries,
    });

    let json_data = serde_json::to_string(&status).unwrap_or_else(|_| "{}".to_string());

    let result = ReplicationResult {
        id: result_id.clone(),
        workspace_id: workspace_id.clone(),
        query_type: "status".to_string(),
        json_data,
        created_at: now,
    };

    ctx.db.replication_result().insert(result);

    // Clean up old status results
    let old: Vec<_> = ctx
        .db
        .replication_result()
        .iter().take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id && r.query_type == "status" && r.id != result_id)
        .collect();
    for r in old {
        ctx.db.replication_result().id().delete(&r.id);
    }

    Ok(())
}

/// Clean up old synced log entries (older than 7 days).
#[reducer]
pub fn cleanup_replication_log(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let seven_days_ago = now - 7 * 86_400_000_000; // 7 days in microseconds

    let old: Vec<_> = ctx
        .db
        .replication_log()
        .iter().take(crate::MAX_RESULTS)
        .filter(|e| {
            e.workspace_id == workspace_id && e.synced && e.created_at < seven_days_ago
        })
        .collect();

    let _count = old.len();
    for entry in old {
        ctx.db.replication_log().id().delete(&entry.id);
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Bi-directional replication reducers
// ---------------------------------------------------------------------------

/// Accept incoming replication data from a remote peer.
/// Parses `entries_json` as a JSON array of replication entries and applies
/// each mutation to the local database with conflict resolution.
#[reducer]
pub fn replicate_incoming(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
    entries_json: String,
) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let entries: Vec<IncomingEntry> = serde_json::from_str(&entries_json)
        .map_err(|e| format!("Invalid entries_json: {}", e))?;

    let now = now_micros(ctx);
    let mut synced_ids: Vec<String> = Vec::new();

    for entry in &entries {
        let result = apply_incoming_entry(ctx, &workspace_id, entry, now);
        match result {
            Ok(()) => {
                synced_ids.push(entry.id.clone());
            }
            Err(e) => {
                // Store a replication_result so the daemon can read errors
                let err_id = uuid_v4_uniq(ctx, |id| ctx.db.replication_result().id().find(id).is_none(), 3);
                let err_result = ReplicationResult {
                    id: err_id.clone(),
                    workspace_id: workspace_id.clone(),
                    query_type: format!("replication_error_{}", peer_id),
                    json_data: serde_json::json!({
                        "entry_id": entry.id,
                        "table_name": entry.table_name,
                        "operation": entry.operation,
                        "record_id": entry.record_id,
                        "error": e,
                    }).to_string(),
                    created_at: now,
                };
                ctx.db.replication_result().insert(err_result);
            }
        }
    }

    // Mark entries as synced in our local log if they were received by us
    if !synced_ids.is_empty() {
        for id in &synced_ids {
            if let Some(mut log_entry) = ctx.db.replication_log().id().find(id) {
                log_entry.synced = true;
                ctx.db.replication_log().id().update(log_entry);
            }
        }
    }

    // Store a sync receipt for this peer
    let receipt = ReplicationLog {
        id: uuid_v4_uniq(ctx, |id| ctx.db.replication_log().id().find(id).is_none(), 3),
        workspace_id: workspace_id.clone(),
        table_name: "__sync_receipt__".to_string(),
        operation: "received".to_string(),
        record_id: peer_id.clone(),
        data_json: serde_json::json!({
            "peer_id": peer_id,
            "entries_received": synced_ids.len(),
            "total_entries": entries.len(),
        }).to_string(),
        created_at: now,
        synced: true,
    };
    ctx.db.replication_log().insert(receipt);

    Ok(())
}

/// Helper: apply a single incoming entry to the local database with
/// conflict resolution.
fn apply_incoming_entry(
    ctx: &ReducerContext,
    workspace_id: &str,
    entry: &IncomingEntry,
    now: i64,
) -> Result<(), String> {
    let data: serde_json::Value = serde_json::from_str(&entry.data_json)
        .map_err(|e| format!("Invalid data_json: {}", e))?;

    match entry.operation.as_str() {
        "insert" => apply_incoming_insert(ctx, workspace_id, entry, &data, now),
        "update" => apply_incoming_update(ctx, workspace_id, entry, &data, now),
        "delete" => apply_incoming_delete(ctx, workspace_id, entry),
        op => Err(format!("Unknown operation '{}'", op)),
    }
}

/// Apply an incoming insert with conflict resolution.
/// If the record already exists locally, skip it (last-write-wins on insert).
fn apply_incoming_insert(
    ctx: &ReducerContext,
    workspace_id: &str,
    entry: &IncomingEntry,
    data: &serde_json::Value,
    now: i64,
) -> Result<(), String> {
    match entry.table_name.as_str() {
        "memory" => {
            let record_id = &entry.record_id;
            if ctx.db.memory().id().find(record_id).is_some() {
                return Ok(()); // Already exists, skip (last-write-wins)
            }
            let memory = Memory {
                id: record_id.clone(),
                workspace_id: workspace_id.to_string(),
                peer_id: data.get("peer_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                observer_id: data.get("observer_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                memory_type: data.get("memory_type").and_then(|v| v.as_str()).unwrap_or("experience").to_string(),
                content: data.get("content").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                summary: data.get("summary").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                context: data.get("context").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                entities_json: data.get("entities_json").and_then(|v| v.as_str()).unwrap_or("[]").to_string(),
                confidence: data.get("confidence").and_then(|v| v.as_f64()).unwrap_or(0.8),
                source_session_id: data.get("source_session_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                source_message_id: data.get("source_message_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                is_active: data.get("is_active").and_then(|v| v.as_bool()).unwrap_or(true),
                created_at: data.get("created_at").and_then(|v| v.as_i64()).unwrap_or(now),
                expires_at: data.get("expires_at").and_then(|v| v.as_i64()).unwrap_or(0),
                updated_at: data.get("updated_at").and_then(|v| v.as_i64()).unwrap_or(now),
                tier: data.get("tier").and_then(|v| v.as_str()).unwrap_or("L1").to_string(),
                access_count: data.get("access_count").and_then(|v| v.as_u64()).unwrap_or(0),
                strength: data.get("strength").and_then(|v| v.as_f64()).unwrap_or(0.5),
                version: data.get("version").and_then(|v| v.as_u64()).map(|v| v as u32).unwrap_or(0),
                valid_from: data.get("valid_from").and_then(|v| v.as_i64()).unwrap_or(0),
                parent_directory_id: data.get("parent_directory_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                consolidated_to: data.get("consolidated_to").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                trust_score: data.get("trust_score").and_then(|v| v.as_f64()).unwrap_or(0.5),
                feedback_count: data.get("feedback_count").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
                user_scope: data.get("user_scope").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            };
            ctx.db.memory().insert(memory);
            Ok(())
        }
        "kg_node" => {
            let record_id = &entry.record_id;
            if ctx.db.kg_node().id().find(record_id).is_some() {
                return Ok(());
            }
            let node = KgNode {
                id: record_id.clone(),
                workspace_id: workspace_id.to_string(),
                label: data.get("label").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                node_type: data.get("node_type").and_then(|v| v.as_str()).unwrap_or("concept").to_string(),
                summary: data.get("summary").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                metadata_json: data.get("metadata_json").and_then(|v| v.as_str()).unwrap_or("{}").to_string(),
                source_memory_id: data.get("source_memory_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                community_id: data.get("community_id").and_then(|v| v.as_u64()).unwrap_or(0),
                embedding_json: data.get("embedding_json").and_then(|v| v.as_str()).unwrap_or("[]").to_string(),
                created_at: data.get("created_at").and_then(|v| v.as_i64()).unwrap_or(now),
            };
            ctx.db.kg_node().insert(node);
            Ok(())
        }
        "kg_edge" => {
            let record_id = &entry.record_id;
            if ctx.db.kg_edge().id().find(record_id).is_some() {
                return Ok(());
            }
            let edge = KgEdge {
                id: record_id.clone(),
                workspace_id: workspace_id.to_string(),
                source_node_id: data.get("source_node_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                target_node_id: data.get("target_node_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                relation: data.get("relation").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                weight: data.get("weight").and_then(|v| v.as_f64()).unwrap_or(1.0),
                confidence: data.get("confidence").and_then(|v| v.as_str()).unwrap_or("EXTRACTED").to_string(),
                metadata_json: data.get("metadata_json").and_then(|v| v.as_str()).unwrap_or("{}").to_string(),
                source_memory_id: data.get("source_memory_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                created_at: data.get("created_at").and_then(|v| v.as_i64()).unwrap_or(now),
                valid_at: data.get("valid_at").and_then(|v| v.as_i64()).unwrap_or(now),
                invalid_at: data.get("invalid_at").and_then(|v| v.as_i64()).unwrap_or(0),
                version: data.get("version").and_then(|v| v.as_u64()).map(|v| v as u32).unwrap_or(1),
                edge_group_id: data.get("edge_group_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            };
            ctx.db.kg_edge().insert(edge);
            Ok(())
        }
        "note" => {
            let record_id = &entry.record_id;
            if ctx.db.note().id().find(record_id).is_some() {
                return Ok(());
            }
            let note = Note {
                id: record_id.clone(),
                workspace_id: workspace_id.to_string(),
                title: data.get("title").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                content: data.get("content").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                note_date: data.get("note_date").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                embedding_json: data.get("embedding_json").and_then(|v| v.as_str()).unwrap_or("[]").to_string(),
                backlink_count: data.get("backlink_count").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
                block_ref_count: data.get("block_ref_count").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
                created_at: data.get("created_at").and_then(|v| v.as_i64()).unwrap_or(now),
                updated_at: data.get("updated_at").and_then(|v| v.as_i64()).unwrap_or(now),
                is_active: data.get("is_active").and_then(|v| v.as_bool()).unwrap_or(true),
                version: Some(data.get("version").and_then(|v| v.as_u64()).unwrap_or(0) as u32),
            };
            ctx.db.note().insert(note);
            Ok(())
        }
        "profile" => {
            let record_id = &entry.record_id;
            if ctx.db.profile().id().find(record_id).is_some() {
                return Ok(());
            }
            let profile = Profile {
                id: record_id.clone(),
                peer_id: data.get("peer_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                static_facts_json: data.get("static_facts_json").and_then(|v| v.as_str()).unwrap_or("[]").to_string(),
                dynamic_context_json: data.get("dynamic_context_json").and_then(|v| v.as_str()).unwrap_or("[]").to_string(),
                preferences_json: data.get("preferences_json").and_then(|v| v.as_str()).unwrap_or("{}").to_string(),
                tags_json: data.get("tags_json").and_then(|v| v.as_str()).unwrap_or("[]").to_string(),
                updated_at: data.get("updated_at").and_then(|v| v.as_i64()).unwrap_or(now),
            };
            ctx.db.profile().insert(profile);
            Ok(())
        }
        tn => Err(format!("No insert handler for table '{}'", tn)),
    }
}

/// Apply an incoming update with conflict resolution.
/// Uses timestamp comparison: if the incoming entry is newer, apply it.
fn apply_incoming_update(
    ctx: &ReducerContext,
    workspace_id: &str,
    entry: &IncomingEntry,
    data: &serde_json::Value,
    now: i64,
) -> Result<(), String> {
    match entry.table_name.as_str() {
        "memory" => {
            let record_id = &entry.record_id;
            match ctx.db.memory().id().find(record_id) {
                Some(mut mem) => {
                    let incoming_updated = data.get("updated_at").and_then(|v| v.as_i64()).unwrap_or(entry.created_at);
                    if incoming_updated <= mem.updated_at {
                        return Ok(()); // Local is newer or same age, skip
                    }
                    mem.content = data.get("content").and_then(|v| v.as_str()).unwrap_or(&mem.content).to_string();
                    mem.summary = data.get("summary").and_then(|v| v.as_str()).unwrap_or(&mem.summary).to_string();
                    mem.confidence = data.get("confidence").and_then(|v| v.as_f64()).unwrap_or(mem.confidence);
                    mem.updated_at = incoming_updated;
                    if let Some(v) = data.get("tier").and_then(|v| v.as_str()) {
                        mem.tier = v.to_string();
                    }
                    ctx.db.memory().id().update(mem);
                    Ok(())
                }
                None => {
                    apply_incoming_insert(ctx, workspace_id, entry, data, now)
                }
            }
        }
        "kg_node" => {
            let record_id = &entry.record_id;
            match ctx.db.kg_node().id().find(record_id) {
                Some(mut node) => {
                    let incoming_created = data.get("created_at").and_then(|v| v.as_i64()).unwrap_or(entry.created_at);
                    if incoming_created <= node.created_at {
                        return Ok(());
                    }
                    node.label = data.get("label").and_then(|v| v.as_str()).unwrap_or(&node.label).to_string();
                    node.summary = data.get("summary").and_then(|v| v.as_str()).unwrap_or(&node.summary).to_string();
                    if let Some(v) = data.get("node_type").and_then(|v| v.as_str()) {
                        node.node_type = v.to_string();
                    }
                    ctx.db.kg_node().id().update(node);
                    Ok(())
                }
                None => apply_incoming_insert(ctx, workspace_id, entry, data, now),
            }
        }
        "kg_edge" => {
            let record_id = &entry.record_id;
            match ctx.db.kg_edge().id().find(record_id) {
                Some(mut edge) => {
                    let incoming_created = data.get("created_at").and_then(|v| v.as_i64()).unwrap_or(entry.created_at);
                    if incoming_created <= edge.created_at {
                        return Ok(());
                    }
                    edge.relation = data.get("relation").and_then(|v| v.as_str()).unwrap_or(&edge.relation).to_string();
                    edge.weight = data.get("weight").and_then(|v| v.as_f64()).unwrap_or(edge.weight);
                    ctx.db.kg_edge().id().update(edge);
                    Ok(())
                }
                None => apply_incoming_insert(ctx, workspace_id, entry, data, now),
            }
        }
        "note" => {
            let record_id = &entry.record_id;
            match ctx.db.note().id().find(record_id) {
                Some(mut note) => {
                    let incoming_updated = data.get("updated_at").and_then(|v| v.as_i64()).unwrap_or(entry.created_at);
                    if incoming_updated <= note.updated_at {
                        return Ok(());
                    }
                    note.title = data.get("title").and_then(|v| v.as_str()).unwrap_or(&note.title).to_string();
                    note.content = data.get("content").and_then(|v| v.as_str()).unwrap_or(&note.content).to_string();
                    note.note_date = data.get("note_date").and_then(|v| v.as_str()).unwrap_or(&note.note_date).to_string();
                    note.updated_at = incoming_updated;
                    ctx.db.note().id().update(note);
                    Ok(())
                }
                None => apply_incoming_insert(ctx, workspace_id, entry, data, now),
            }
        }
        "profile" => {
            let record_id = &entry.record_id;
            match ctx.db.profile().id().find(record_id) {
                Some(mut profile) => {
                    let incoming_updated = data.get("updated_at").and_then(|v| v.as_i64()).unwrap_or(entry.created_at);
                    if incoming_updated <= profile.updated_at {
                        return Ok(());
                    }
                    if let Some(v) = data.get("static_facts_json").and_then(|v| v.as_str()) {
                        profile.static_facts_json = v.to_string();
                    }
                    if let Some(v) = data.get("dynamic_context_json").and_then(|v| v.as_str()) {
                        profile.dynamic_context_json = v.to_string();
                    }
                    if let Some(v) = data.get("preferences_json").and_then(|v| v.as_str()) {
                        profile.preferences_json = v.to_string();
                    }
                    if let Some(v) = data.get("tags_json").and_then(|v| v.as_str()) {
                        profile.tags_json = v.to_string();
                    }
                    profile.updated_at = incoming_updated;
                    ctx.db.profile().id().update(profile);
                    Ok(())
                }
                None => apply_incoming_insert(ctx, workspace_id, entry, data, now),
            }
        }
        tn => Err(format!("No update handler for table '{}'", tn)),
    }
}

/// Apply an incoming delete.
fn apply_incoming_delete(
    ctx: &ReducerContext,
    _workspace_id: &str,
    entry: &IncomingEntry,
) -> Result<(), String> {
    let record_id = &entry.record_id;
    match entry.table_name.as_str() {
        "memory" => {
            if ctx.db.memory().id().find(record_id).is_some() {
                ctx.db.memory().id().delete(record_id);
            }
            Ok(())
        }
        "kg_node" => {
            if ctx.db.kg_node().id().find(record_id).is_some() {
                ctx.db.kg_node().id().delete(record_id);
            }
            Ok(())
        }
        "kg_edge" => {
            if ctx.db.kg_edge().id().find(record_id).is_some() {
                ctx.db.kg_edge().id().delete(record_id);
            }
            Ok(())
        }
        "note" => {
            if ctx.db.note().id().find(record_id).is_some() {
                ctx.db.note().id().delete(record_id);
            }
            Ok(())
        }
        "profile" => {
            if ctx.db.profile().id().find(record_id).is_some() {
                ctx.db.profile().id().delete(record_id);
            }
            Ok(())
        }
        tn => Err(format!("No delete handler for table '{}'", tn)),
    }
}

/// Store a single peer's details in the replication_result table (for daemon read).
#[reducer]
pub fn get_replication_peer_by_id(ctx: &ReducerContext, peer_id: String) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let now = now_micros(ctx);
    let peer = ctx
        .db
        .replication_peer()
        .id()
        .find(&peer_id)
        .ok_or_else(|| format!("Replication peer '{}' not found", peer_id))?;

    let result_id = uuid_v4_uniq(ctx, |id| ctx.db.replication_result().id().find(id).is_none(), 3);
    let json_data = serde_json::to_string(&peer).unwrap_or_else(|_| "{}".to_string());

    let result = ReplicationResult {
        id: result_id.clone(),
        workspace_id: peer.workspace_id.clone(),
        query_type: "peer_by_id".to_string(),
        json_data,
        created_at: now,
    };

    ctx.db.replication_result().insert(result);

    // Clean up old peer_by_id results
    let old: Vec<_> = ctx
        .db
        .replication_result()
        .iter().take(crate::MAX_RESULTS)
        .filter(|r| r.query_type == "peer_by_id" && r.id != result_id)
        .collect();
    for r in old {
        ctx.db.replication_result().id().delete(&r.id);
    }

    Ok(())
}

/// Update a peer's last_sync_at timestamp.
#[reducer]
pub fn mark_peer_synced(ctx: &ReducerContext, peer_id: String, last_sync_at: i64) -> Result<(), String> {
    let _admin = require_admin(ctx)?;
    let mut peer = ctx
        .db
        .replication_peer()
        .id()
        .find(&peer_id)
        .ok_or_else(|| format!("Replication peer '{}' not found", peer_id))?;

    peer.last_sync_at = last_sync_at;
    ctx.db.replication_peer().id().update(peer);
    Ok(())
}
