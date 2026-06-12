use spacetimedb::*;
use crate::auth::require_auth;

use crate::context_directory::context_directory;
use crate::insight::insight;
use crate::memory::memory;
use crate::profile::profile;
use crate::session::session_participant;
use crate::{now_micros, uuid_v4, MAX_RESULTS};

// ---------------------------------------------------------------------------
// Result tables (client reads these after a reducer call)
// ---------------------------------------------------------------------------

/// Holds the result of a profile context query.
#[table(accessor = profile_context_result, public)]
#[derive(Debug, Clone)]
pub struct ProfileContextResult {
    #[primary_key]
    pub id: String,
    pub peer_id: String,
    pub static_facts_json: String,
    pub dynamic_context_json: String,
    pub preferences_json: String,
    pub tags_json: String,
    /// The query text that produced this result (empty for direct lookups).
    pub query_text: String,
    pub created_at: i64,
}

/// Holds a peer's aggregated memory/insight/session summary.
#[table(accessor = peer_summary_result, public)]
#[derive(Debug, Clone)]
pub struct PeerSummaryResult {
    #[primary_key]
    pub id: String,
    pub peer_id: String,
    pub memory_count: u64,
    pub insight_count: u64,
    pub session_count: u64,
    pub latest_activity: i64,
}

/// Holds a recursive directory content listing result.
#[table(accessor = directory_content_result, public)]
#[derive(Debug, Clone)]
pub struct DirectoryContentResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub directory_path: String,
    /// The matched root directory id.
    pub directory_id: String,
    /// JSON array of subdirectory ids discovered recursively.
    pub subdirectory_ids_json: String,
    /// JSON array of memory ids under any directory in the tree.
    pub memory_ids_json: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

/// Retrieve the full context profile for a given peer and store it in
/// `ProfileContextResult` so the client can read it back.
#[reducer]
pub fn get_profile_context(ctx: &ReducerContext, peer_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let profile = ctx
        .db
        .profile()
        .iter().take(crate::MAX_RESULTS)
        .find(|p| p.peer_id == peer_id)
        .ok_or_else(|| format!("Profile for peer '{}' not found", peer_id))?;

    let result = ProfileContextResult {
        id: uuid_v4(ctx),
        peer_id: profile.peer_id.clone(),
        static_facts_json: profile.static_facts_json.clone(),
        dynamic_context_json: profile.dynamic_context_json.clone(),
        preferences_json: profile.preferences_json.clone(),
        tags_json: profile.tags_json.clone(),
        query_text: String::new(),
        created_at: now_micros(ctx),
    };

    ctx.db.profile_context_result().insert(result);
    Ok(())
}

/// Search profiles whose static facts or dynamic context contain the query
/// text, and store all matches in `ProfileContextResult`.
#[reducer]
pub fn search_profiles(
    ctx: &ReducerContext,
    _workspace_id: String,
    query_text: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let query_lower = query_text.to_lowercase();

    let matches: Vec<_> = ctx
        .db
        .profile()
        .iter().take(crate::MAX_RESULTS)
        .filter(|p| {
            p.static_facts_json.to_lowercase().contains(&query_lower)
                || p.dynamic_context_json.to_lowercase().contains(&query_lower)
        })
        .collect();

    for p in &matches {
        let result = ProfileContextResult {
            id: uuid_v4(ctx),
            peer_id: p.peer_id.clone(),
            static_facts_json: p.static_facts_json.clone(),
            dynamic_context_json: p.dynamic_context_json.clone(),
            preferences_json: p.preferences_json.clone(),
            tags_json: p.tags_json.clone(),
            query_text: query_text.clone(),
            created_at: now,
        };
        ctx.db.profile_context_result().insert(result);
    }

    Ok(())
}

/// Aggregate a summary of memories, insights, and sessions for a given peer
/// and store the result in `PeerSummaryResult`.
#[reducer]
pub fn get_peer_memory_summary(ctx: &ReducerContext, peer_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let _now = now_micros(ctx);

    // Count active memories for this peer
    let memory_count = ctx
        .db
        .memory()
        .iter().take(crate::MAX_RESULTS)
        .filter(|m| m.peer_id == peer_id && m.is_active)
        .count() as u64;

    // Count insights for this peer
    let insight_count = ctx
        .db
        .insight()
        .iter().take(crate::MAX_RESULTS)
        .filter(|i| i.peer_id == peer_id)
        .count() as u64;

    // Count sessions this peer participates in
    let session_count = ctx
        .db
        .session_participant()
        .iter().take(crate::MAX_RESULTS)
        .filter(|sp| sp.peer_id == peer_id)
        .count() as u64;

    // Find the latest activity timestamp across memories, insights, and sessions
    let latest_memory = ctx
        .db
        .memory()
        .iter().take(crate::MAX_RESULTS)
        .filter(|m| m.peer_id == peer_id)
        .map(|m| m.created_at)
        .max()
        .unwrap_or(0);

    let latest_insight = ctx
        .db
        .insight()
        .iter().take(crate::MAX_RESULTS)
        .filter(|i| i.peer_id == peer_id)
        .map(|i| i.created_at)
        .max()
        .unwrap_or(0);

    let latest_session = ctx
        .db
        .session_participant()
        .iter().take(crate::MAX_RESULTS)
        .filter(|sp| sp.peer_id == peer_id)
        .map(|sp| sp.joined_at)
        .max()
        .unwrap_or(0);

    let latest_activity = latest_memory.max(latest_insight).max(latest_session);

    let summary = PeerSummaryResult {
        id: uuid_v4(ctx),
        peer_id,
        memory_count,
        insight_count,
        session_count,
        latest_activity,
    };

    ctx.db.peer_summary_result().insert(summary);
    Ok(())
}

/// Recursively discover all content under a directory path (OpenViking parity).
///
/// 1. Find the `ContextDirectory` whose `path` matches `directory_path`.
/// 2. Recursively collect all subdirectories via `parent_id`.
/// 3. Collect all `Memory` entries whose `parent_directory_id` is any
///    directory in the tree.
/// 4. Store the complete listing in `DirectoryContentResult`.
#[reducer]
pub fn search_directory_contents(
    ctx: &ReducerContext,
    workspace_id: String,
    directory_path: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    // 1. Find the root directory by path
    let root_dir = ctx
        .db
        .context_directory()
        .iter().take(crate::MAX_RESULTS)
        .find(|d| d.path == directory_path)
        .ok_or_else(|| format!("ContextDirectory with path '{}' not found", directory_path))?;

    // 2. Recursively collect all subdirectory ids (BFS)
    let root_id = root_dir.id.clone();
    let mut all_dir_ids: Vec<String> = Vec::new();
    let mut queue: Vec<String> = vec![root_id.clone()];

    while let Some(did) = queue.pop() {
        all_dir_ids.push(did.clone());

        // Find immediate children whose parent_id == did
        let children: Vec<_> = ctx
            .db
            .context_directory()
            .iter().take(crate::MAX_RESULTS)
            .filter(|d| d.parent_id == did)
            .collect();

        for child in &children {
            queue.push(child.id.clone());
        }
    }

    // 3. Collect all Memory entries whose parent_directory_id is in the set
    let memory_ids: Vec<String> = ctx
        .db
        .memory()
        .iter().take(crate::MAX_RESULTS)
        .filter(|m| !m.parent_directory_id.is_empty() && all_dir_ids.contains(&m.parent_directory_id))
        .map(|m| m.id.clone())
        .collect();

    // 4. Store the result
    let subdirectory_ids = if all_dir_ids.len() <= 1 {
        // No subdirectories beyond the root
        "[]".to_string()
    } else {
        // Skip the root itself in the subdirectory listing
        let subs: Vec<&str> = all_dir_ids[1..].iter().map(|s| s.as_str()).collect();
        format!(
            "[{}]",
            subs.iter()
                .map(|s| format!("\"{}\"", s))
                .collect::<Vec<_>>()
                .join(",")
        )
    };

    let memory_ids_json = if memory_ids.is_empty() {
        "[]".to_string()
    } else {
        format!(
            "[{}]",
            memory_ids
                .iter()
                .map(|s| format!("\"{}\"", s))
                .collect::<Vec<_>>()
                .join(",")
        )
    };

    let result = DirectoryContentResult {
        id: uuid_v4(ctx),
        workspace_id,
        directory_path,
        directory_id: root_id,
        subdirectory_ids_json: subdirectory_ids,
        memory_ids_json,
        created_at: now,
    };

    ctx.db.directory_content_result().insert(result);
    Ok(())
}
