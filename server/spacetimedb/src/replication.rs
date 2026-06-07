use spacetimedb::*;

use crate::{now_micros, uuid_v4};

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// A replication peer — another SpacetimeDB instance to sync with.
#[table(accessor = replication_peer, public)]
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
#[table(accessor = replication_log, public)]
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
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

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
    let now = now_micros(ctx);
    let result_id = uuid_v4(ctx);

    // Query peers for this workspace
    let peers: Vec<_> = ctx
        .db
        .replication_peer()
        .iter()
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
        .iter()
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
    let now = now_micros(ctx);
    let result_id = uuid_v4(ctx);

    let entries: Vec<_> = ctx
        .db
        .replication_log()
        .iter()
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
        .iter()
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
    let now = now_micros(ctx);
    let result_id = uuid_v4(ctx);

    let total_peers = ctx
        .db
        .replication_peer()
        .iter()
        .filter(|p| p.workspace_id == workspace_id)
        .count();

    let active_peers = ctx
        .db
        .replication_peer()
        .iter()
        .filter(|p| p.workspace_id == workspace_id && p.is_active)
        .count();

    let unsynced_count = ctx
        .db
        .replication_log()
        .iter()
        .filter(|e| e.workspace_id == workspace_id && !e.synced)
        .count();

    let total_log_entries = ctx
        .db
        .replication_log()
        .iter()
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
        .iter()
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
    let now = now_micros(ctx);
    let seven_days_ago = now - 7 * 86_400_000_000; // 7 days in microseconds

    let old: Vec<_> = ctx
        .db
        .replication_log()
        .iter()
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
