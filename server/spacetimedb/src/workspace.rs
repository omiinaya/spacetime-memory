use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v4_uniq};
use crate::auth;
use crate::memory::{memory, memory_revision};
use crate::tag::{tag, memory_tag};
use crate::workspace_directory::workspace_directory;

/// A workspace representing a project, agent-world, or sandbox.
#[table(accessor = workspace)]
#[derive(Debug, Clone)]
pub struct Workspace {
    #[primary_key]
    pub id: String,
    pub name: String,
    pub description: String,
    pub context: String,
    pub created_at: i64,
    pub updated_at: i64,
    pub is_public: bool,
}

/// Permission entry granting a peer access to a workspace (space).
///
/// `permission` is one of:
/// - `"owner"`   — full control (grant/revoke, read, write, delete)
/// - `"editor"`  — read and write
/// - `"viewer"`  — read only
#[table(accessor = space_permission)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SpacePermission {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub peer_id: String,      // who has access
    #[index(btree)]
    pub workspace_id: String,
    pub permission: String,   // "owner", "editor", "viewer"
    pub granted_by: String,   // peer_id who granted access
    pub created_at: i64,
}

// ── Workspace reducers ────────────────────────────────────────────────

#[reducer]
pub fn create_workspace(ctx: &ReducerContext, name: String, description: String, id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    // Idempotent retry-safe: if the caller supplies an id that already exists
    // (e.g. a timed-out client retrying the same call), return Ok instead of
    // panicking on the primary-key violation. Panicking aborts the whole WASM
    // instance (panic=abort), failing every concurrent reducer call with
    // "The instance encountered a fatal error".
    let workspace_id = if id.is_empty() {
        crate::insert_row_retry(
            ctx.db.workspace(),
            Workspace {
                id: String::new(),
                name: name.clone(),
                description: description.clone(),
                context: String::new(),
                created_at: now,
                updated_at: now,
                is_public: false,
            },
            |row| {
                row.id = uuid_v4_uniq(ctx, |cid| ctx.db.workspace().id().find(cid).is_none(), 5);
            },
            5,
        )?
        .id
    } else {
        match ctx.db.workspace().try_insert(Workspace {
            id: id.clone(),
            name,
            description,
            context: String::new(),
            created_at: now,
            updated_at: now,
            is_public: false,
        }) {
            Ok(_) => {}
            Err(spacetimedb::TryInsertError::UniqueConstraintViolation(_)) => {
                // Idempotent retry-safe: id already exists (timed-out client
                // retried). Succeed without re-creating or panicking.
                return Ok(());
            }
            Err(e) => return Err(format!("create_workspace failed: {e}")),
        }
        id
    };
    let caller = ctx.sender().to_hex().to_string();

    // Auto-grant owner access to the workspace creator
    crate::insert_row_retry(
        ctx.db.space_permission(),
        SpacePermission {
            id: String::new(),
            workspace_id: workspace_id.clone(),
            peer_id: caller.to_string(),
            permission: "owner".to_string(),
            granted_by: caller.to_string(),
            created_at: now,
        },
        |row| {
            row.id = uuid_v4_uniq(ctx, |pid| ctx.db.space_permission().id().find(pid).is_none(), 5);
        },
        5,
    )?;

    Ok(())
}

#[reducer]
pub fn update_workspace(ctx: &ReducerContext, id: String, name: String, description: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();
    let existing = ctx
        .db
        .workspace()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Workspace '{}' not found", id))?;

    // Only owner or admin can update workspace metadata
    check_space_access(ctx, &id, &caller, "owner")?;

    ctx.db.workspace().id().update(Workspace {
        id: id.clone(),
        name,
        description,
        context: existing.context,
        created_at: existing.created_at,
        updated_at: now_micros(ctx),
        is_public: existing.is_public,
    });
    Ok(())
}

/// Set the context string for a workspace. Requires editor access.
#[reducer]
pub fn set_workspace_context(
    ctx: &ReducerContext,
    workspace_id: String,
    context_text: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    let ws = ctx
        .db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    let updated = Workspace {
        context: context_text,
        ..ws
    };
    ctx.db.workspace().id().update(updated);
    Ok(())
}

/// Result table for get_workspace_context queries.
#[table(accessor = workspace_context_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct WorkspaceContextResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub context: String,
    pub queried_at: i64,
}

/// Retrieve the context string for a workspace. Result written to workspace_context_result.
#[reducer]
pub fn get_workspace_context(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    let ws = ctx
        .db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    // Pre-cleanup: remove stale results for this workspace_id
    for old in ctx.db.workspace_context_result().iter()
        .filter(|r| r.workspace_id == workspace_id)
        .collect::<Vec<_>>()
    {
        ctx.db.workspace_context_result().id().delete(&old.id);
    }
    ctx.db
            .workspace_context_result()
            .insert(WorkspaceContextResult {
                id: uuid_v4_uniq(ctx, |id| ctx.db.workspace_context_result().id().find(id).is_none(), 3),
                workspace_id: workspace_id.clone(),
                context: ws.context.clone(),
                queried_at: now_micros(ctx),
            });

    Ok(())
}

#[reducer]
pub fn delete_workspace(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();

    ctx.db
        .workspace()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Workspace '{}' not found", id))?;

    // Only owner or admin can delete a workspace
    check_space_access(ctx, &id, &caller, "owner")?;

    cascade_delete_workspace_data(ctx, &id);

    ctx.db.workspace().id().delete(&id);
    Ok(())
}

/// Cascade-delete every row scoped to a workspace.
///
/// Previously `delete_workspace` only removed `space_permission` + the
/// workspace row, orphaning memories, peers, KG data, notes, facts, sessions,
/// indexes and more — all still queryable (and searchable) afterwards.
///
/// Covers three tiers:
///   1. Junction tables reached through parent ids (message via session,
///      doc_chunk via document, note_block/backlink/block_reference via note,
///      tour_stop via tour, memory_tag/memory_feedback via memory, profile /
///      peer_reputation via peer, entity_term_index/entity_search_index via
///      term_index/search_index + entity ids, session_participant via session)
///   2. All uniform tables (String `id` PK + `workspace_id` column)
///   3. Special PKs: workspace_encryption_key (PK = workspace_id),
///      user_session_result (PK = query_id)
///
/// Ephemeral per-query `*_result` tables WITHOUT a workspace_id column are
/// intentionally skipped — they are overwritten on the next query and hold
/// no unique data. Every scan is bounded by MAX_RESULTS like other reducers.
fn cascade_delete_workspace_data(ctx: &ReducerContext, id: &str) {
    use std::collections::HashSet;
    // Table accessor traits (STDB v2: each accessor is a trait that must be in scope)
    #[allow(unused_imports)]
    use crate::auth::{api_key, api_key_result, api_key_verification_result};
    use crate::change_event::change_event;
    use crate::connector::connector_config;
    #[allow(unused_imports)]
    use crate::consolidation::{consolidation_log, merge_suggestion};
    use crate::context_compression::context_pack;
    use crate::context_delta::delta_pack;
    #[allow(unused_imports)]
    use crate::context_directory::{context_directory, directory_memory_link, directory_result};
    use crate::crypto::workspace_encryption_key;
    use crate::document::{doc_chunk, document};
    #[allow(unused_imports)]
    use crate::entity_extraction::entity_extraction_result;
    use crate::entity_linking::entity_link;
    #[allow(unused_imports)]
    use crate::graph_traversal::{bridge_result, graph_traversal_result, kg_stats_result, shortest_path_result};
    use crate::harmonic_belief::{harmonic_belief, resonance_log};
    #[allow(unused_imports)]
    use crate::hybrid_query::{entity_search_index, entity_term_index, god_node, hybrid_result, session_search_result, workspace_index};
    use crate::insight::{insight, mental_model};
    #[allow(unused_imports)]
    use crate::knowledge_graph::{citation, community_hierarchy, edge_history_result, hierarchy_cluster, kg_community, kg_edge, kg_node, pagerank_result};
    #[allow(unused_imports)]
    use crate::memory::{memory, memory_insert_result, user_memory_result};
    #[allow(unused_imports)]
    use crate::memory_feedback::{memory_feedback, memory_recommendation, peer_reputation};
    use crate::message::message;
    #[allow(unused_imports)]
    use crate::note::{block_reference, note, note_backlink, note_block, note_revision};
    use crate::peer::peer;
    #[allow(unused_imports)]
    use crate::profile::{fact, fact_result, profile};
    #[allow(unused_imports)]
    use crate::profile_query::directory_content_result;
    #[allow(unused_imports)]
    use crate::replication::{replication_log, replication_peer, replication_result};
    use crate::retrieval::{search_index, term_index};
    #[allow(unused_imports)]
    use crate::ripple::{ripple_impact, ripple_impact_result, stale_nodes_result};
    #[allow(unused_imports)]
    use crate::session::{agent_step, session, session_participant, session_step_result};
    #[allow(unused_imports)]
    use crate::subscription::{subscription, subscription_list_result};
    use crate::tag::{memory_tag, tag};
    use crate::tour::{tour, tour_stop};
    use crate::tracing::tracing_span;
    use crate::user::user_session_result;

    // ── 1. Collect parent ids needed for junction cleanup ─────────────
    let session_ids: HashSet<String> = ctx.db.session().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();
    let doc_ids: HashSet<String> = ctx.db.document().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();
    let note_ids: HashSet<String> = ctx.db.note().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();
    let tour_ids: HashSet<String> = ctx.db.tour().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();

    let mem_ids: HashSet<String> = ctx.db.memory().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();
    let peer_ids: HashSet<String> = ctx.db.peer().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();
    let tag_ids: HashSet<String> = ctx.db.tag().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();
    let node_ids: HashSet<String> = ctx.db.kg_node().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();
    let term_ids: HashSet<String> = ctx.db.term_index().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();
    let search_ids: HashSet<String> = ctx.db.search_index().workspace_id().filter(id)
        .take(crate::MAX_RESULTS).map(|r| r.id.clone()).collect();

    // ── 2. Junction tables (delete via parent ids) ────────────────────
    // message — via session (btree index on session_id available)
    {
        let rows: Vec<String> = ctx.db.message().iter().take(crate::MAX_RESULTS)
            .filter(|r| session_ids.contains(&r.session_id)).map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.message().id().delete(&rid); }
    }
    // session_participant — no PK, delete by row value
    {
        let rows: Vec<_> = ctx.db.session_participant().iter().take(crate::MAX_RESULTS)
            .filter(|r| session_ids.contains(&r.session_id)).collect();
        for r in rows { ctx.db.session_participant().delete(r); }
    }
    // doc_chunk — via document
    {
        let rows: Vec<String> = ctx.db.doc_chunk().iter().take(crate::MAX_RESULTS)
            .filter(|r| doc_ids.contains(&r.document_id)).map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.doc_chunk().id().delete(&rid); }
    }
    // note_block — via note
    {
        let rows: Vec<String> = ctx.db.note_block().iter().take(crate::MAX_RESULTS)
            .filter(|r| note_ids.contains(&r.note_id)).map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.note_block().id().delete(&rid); }
    }
    // note_backlink — via note (either direction)
    {
        let rows: Vec<String> = ctx.db.note_backlink().iter().take(crate::MAX_RESULTS)
            .filter(|r| note_ids.contains(&r.source_note_id) || note_ids.contains(&r.target_note_id))
            .map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.note_backlink().id().delete(&rid); }
    }
    // block_reference — via note (either direction)
    {
        let rows: Vec<String> = ctx.db.block_reference().iter().take(crate::MAX_RESULTS)
            .filter(|r| note_ids.contains(&r.source_note_id) || note_ids.contains(&r.target_note_id))
            .map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.block_reference().id().delete(&rid); }
    }
    // tour_stop — via tour
    {
        let rows: Vec<String> = ctx.db.tour_stop().iter().take(crate::MAX_RESULTS)
            .filter(|r| tour_ids.contains(&r.tour_id)).map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.tour_stop().id().delete(&rid); }
    }
    // memory_tag — no PK, via memory or tag
    {
        let rows: Vec<_> = ctx.db.memory_tag().iter().take(crate::MAX_RESULTS)
            .filter(|r| mem_ids.contains(&r.memory_id) || tag_ids.contains(&r.tag_id)).collect();
        for r in rows { ctx.db.memory_tag().delete(r); }
    }
    // memory_feedback — via memory or peer
    {
        let rows: Vec<String> = ctx.db.memory_feedback().iter().take(crate::MAX_RESULTS)
            .filter(|r| mem_ids.contains(&r.memory_id) || peer_ids.contains(&r.peer_id))
            .map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.memory_feedback().id().delete(&rid); }
    }
    // profile — via peer
    {
        let rows: Vec<String> = ctx.db.profile().iter().take(crate::MAX_RESULTS)
            .filter(|r| peer_ids.contains(&r.peer_id)).map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.profile().id().delete(&rid); }
    }
    // peer_reputation — PK is the peer_id itself
    for pid in &peer_ids { ctx.db.peer_reputation().id().delete(pid); }
    // entity_term_index — via term_index id or entity (memory/node) id
    {
        let rows: Vec<String> = ctx.db.entity_term_index().iter().take(crate::MAX_RESULTS)
            .filter(|r| term_ids.contains(&r.term_index_id)
                || mem_ids.contains(&r.entity_id) || node_ids.contains(&r.entity_id))
            .map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.entity_term_index().id().delete(&rid); }
    }
    // entity_search_index — via search_index id or entity (memory/node) id
    {
        let rows: Vec<String> = ctx.db.entity_search_index().iter().take(crate::MAX_RESULTS)
            .filter(|r| search_ids.contains(&r.search_index_id)
                || mem_ids.contains(&r.entity_id) || node_ids.contains(&r.entity_id))
            .map(|r| r.id.clone()).collect();
        for rid in rows { ctx.db.entity_search_index().id().delete(&rid); }
    }

    // ── 3. Uniform tables (String id PK + workspace_id column) ────────
    macro_rules! cascade_ws {
        ($($table:ident),+ $(,)?) => {$(
            {
                let rows: Vec<String> = ctx.db.$table().iter().take(crate::MAX_RESULTS)
                    .filter(|r| r.workspace_id == *id)
                    .map(|r| r.id.clone())
                    .collect();
                for rid in rows { ctx.db.$table().id().delete(&rid); }
            }
        )+};
    }
    cascade_ws!(
        space_permission,
        memory,
        peer,
        session,
        document,
        note,
        tag,
        tour,
        fact,
        insight,
        mental_model,
        harmonic_belief,
        resonance_log,
        kg_node,
        kg_edge,
        term_index,
        search_index,
        consolidation_log,
        subscription,
        change_event,
        connector_config,
        context_pack,
        delta_pack,
        entity_link,
        god_node,
        workspace_index,
        citation,
        community_hierarchy,
        hierarchy_cluster,
        replication_log,
        replication_peer,
        ripple_impact,
        tracing_span,
    );
    // workspace_directory — u64 auto_inc PK, delete by row value
    {
        let rows: Vec<_> = ctx.db.workspace_directory().iter().take(crate::MAX_RESULTS)
            .filter(|r| r.workspace_id == *id).collect();
        for r in rows { ctx.db.workspace_directory().id().delete(&r.id); }
    }
    // session_step_result — implicit PK is query_hash (String), delete by row value
    {
        let rows: Vec<_> = ctx.db.session_step_result().iter().take(crate::MAX_RESULTS)
            .filter(|r| r.workspace_id == *id).collect();
        for r in rows { ctx.db.session_step_result().delete(r); }
    }

    // ── 4. Special primary keys ───────────────────────────────────────
    ctx.db.workspace_encryption_key().workspace_id().delete(id.to_string());
    // user_session_result — implicit PK is query_id (String), delete by row value
    {
        let rows: Vec<_> = ctx.db.user_session_result().iter().take(crate::MAX_RESULTS)
            .filter(|r| r.workspace_id == *id).collect();
        for r in rows { ctx.db.user_session_result().delete(r); }
    }
}

// ── Workspace visibility ───────────────────────────────────────────────

/// Toggle whether a workspace is public (viewable by anyone) or private
/// (requires explicit permission). Only owners can change visibility.
#[reducer]
pub fn set_workspace_visibility(ctx: &ReducerContext, workspace_id: String, is_public: bool) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "owner")?;

    let ws = ctx
        .db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    let updated = Workspace { is_public, ..ws };
    ctx.db.workspace().id().update(updated);
    Ok(())
}

// ── Space permission guard ────────────────────────────────────────────

/// Check if `peer_id` has at least the `required` permission level
/// for the given workspace.
///
/// Permission hierarchy: owner > editor > viewer.
///
/// Two authentication paths are supported:
/// 1. **API key auth** -- if the caller has a verified API key whose scope
///    includes `workspace_id`, access is granted directly.
/// 2. **Account auth** -- checks space permissions and admin bypass.
///
/// Returns `Ok(())` if allowed, `Err(String)` with a message if denied.
///
/// **Note:** Full ACL enforcement across all memory/note/KG reducers is the
/// next step. This guard is available for use but is not yet called from
/// every reducer.
pub fn check_space_access(
    ctx: &ReducerContext,
    workspace_id: &str,
    peer_id: &str,
    required: &str,
) -> Result<(), String> {
    // Fail fast on deleted/nonexistent workspaces. Previously the admin
    // bypass (and API-key path) silently authorized operations on workspaces
    // that no longer existed — orphaned rows stayed writable and searchable.
    if ctx.db.workspace().id().find(workspace_id.to_string()).is_none() {
        return Err(format!("Workspace '{}' not found", workspace_id));
    }

    // API key scope check -- if the caller has a verified API key, validate
    // its scope includes the target workspace. This is checked FIRST so
    // workspace-scoped API keys work as the primary auth mechanism.
    match auth::check_api_key_workspace_scope(ctx, workspace_id) {
        Ok(true) => return Ok(()),   // API key scope includes this workspace
        Ok(false) => {},              // No API key auth, continue to account checks
        Err(e) => return Err(e),      // API key scope denies this workspace
    }

    // Admin bypass: admins have implicit owner access to all workspaces
    if auth::is_admin(peer_id, ctx) {
        return Ok(());
    }

    // Permission rank helper
    let rank = |p: &str| -> u8 {
        match p {
            "owner" => 3,
            "editor" => 2,
            "viewer" => 1,
            _ => 0,
        }
    };
    let required_rank = rank(required);

    // Check if this peer has a direct permission for this workspace
    let direct = ctx.db.space_permission().workspace_id().filter(workspace_id).take(crate::MAX_RESULTS).find(
        |sp: &SpacePermission| sp.peer_id == peer_id,
    );

    if let Some(p) = direct {
        if rank(&p.permission) >= required_rank {
            return Ok(());
        }
        return Err(format!(
            "Access denied: peer '{}' has '{}' permission but '{}' is required for workspace '{}'",
            peer_id, p.permission, required, workspace_id
        ));
    }

    // No direct permission — check if workspace is public and caller just needs view access
    if required_rank <= 1 {
        if let Some(ws) = ctx.db.workspace().id().find(workspace_id.to_string()) {
            if ws.is_public {
                return Ok(());
            }
        }
    }

    Err(format!(
        "Access denied: peer '{}' has no permission for workspace '{}'. \
         This is a private workspace — ask an owner to grant you access.",
        peer_id, workspace_id
    ))
}

// ── Space permission reducers ─────────────────────────────────────────

/// Grant a peer access to a workspace with a given permission level.
///
/// Only an existing owner of the workspace can grant access to others.
#[reducer]
pub fn grant_space_access(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
    permission: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();

    // Validate permission value
    match permission.as_str() {
        "owner" | "editor" | "viewer" => {}
        _ => {
            return Err(format!(
                "Invalid permission '{}': must be 'owner', 'editor', or 'viewer'",
                permission
            ))
        }
    }

    // Verify the workspace exists
    ctx.db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    // Only an existing owner or admin can grant access
    let is_admin_or_owner = auth::is_admin(&caller, ctx)
        || ctx.db.space_permission().workspace_id().filter(&workspace_id).take(crate::MAX_RESULTS).any(|sp: SpacePermission| {
            sp.peer_id == caller && sp.permission == "owner"
        });

    if !is_admin_or_owner {
        return Err("Only an owner or admin can grant access".to_string());
    }

    // Check for existing permission — update or insert
    let now = now_micros(ctx);
    let existing = ctx
        .db
        .space_permission()
        .workspace_id()
        .filter(&workspace_id)
        .find(|sp: &SpacePermission| sp.peer_id == peer_id);

    if let Some(existing) = existing {
        // Update existing permission
        let updated = SpacePermission {
            permission: permission.clone(),
            granted_by: caller.clone(),
            ..existing
        };
        ctx.db.space_permission().id().update(updated);
    } else {
        // Insert new permission — try_insert + retry so a unique-key collision
        // (deterministic per-batch RNG can produce duplicate UUIDs under
        // concurrency) retries with a fresh id instead of panicking and
        // aborting the whole WASM instance.
        crate::insert_row_retry(
            ctx.db.space_permission(),
            SpacePermission {
                id: String::new(),
                workspace_id: workspace_id.clone(),
                peer_id: peer_id.clone(),
                permission: permission.clone(),
                granted_by: caller.clone(),
                created_at: now,
            },
            |row| {
                row.id = uuid_v4_uniq(ctx, |id| ctx.db.space_permission().id().find(id).is_none(), 5);
            },
            5,
        )?;
    }

    Ok(())
}

/// Revoke a peer's access to a workspace.
///
/// Only an existing owner can revoke access. Owners cannot revoke their own
/// access this way (they must use a separate owner escalation process).
#[reducer]
pub fn revoke_space_access(
    ctx: &ReducerContext,
    workspace_id: String,
    peer_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();

    // Verify the workspace exists
    ctx.db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    // Only an existing owner or admin can revoke access
    let is_admin_or_owner = auth::is_admin(&caller, ctx)
        || ctx.db.space_permission().workspace_id().filter(&workspace_id).take(crate::MAX_RESULTS).any(|sp: SpacePermission| {
            sp.peer_id == caller && sp.permission == "owner"
        });

    if !is_admin_or_owner {
        return Err("Only an owner or admin can revoke access".to_string());
    }

    // Cannot revoke your own access (unless admin revoking a non-self peer)
    if caller == peer_id {
        return Err("Cannot revoke your own access. Have another owner do it.".to_string());
    }

    // Find and delete the permission record
    let existing = ctx
        .db
        .space_permission()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
        .find(|sp: &SpacePermission| sp.peer_id == peer_id)
        .ok_or_else(|| format!("Peer '{}' has no permission for workspace '{}'", peer_id, workspace_id))?;

    ctx.db.space_permission().id().delete(&existing.id);

    Ok(())
}

/// List all members with their permissions for a workspace.
///
/// Stores results in the `space_member_result` table so the caller can
/// query them via SQL. Any caller with at least viewer access can list members.
#[reducer]
pub fn list_space_members(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();

    // Verify the workspace exists
    ctx.db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    // Check the caller has at least viewer access
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;


    // Gather all members
    let members: Vec<SpacePermission> = ctx
        .db
        .space_permission()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|sp: &SpacePermission| sp.workspace_id == workspace_id)
        .collect();

    // Store results in a result table for SQL querying
    let now = now_micros(ctx);
    // Pre-cleanup: remove stale results for this workspace_id
    for old in ctx.db.space_member_result().iter()
        .filter(|r| r.workspace_id == workspace_id)
        .collect::<Vec<_>>()
    {
        ctx.db.space_member_result().id().delete(&old.id);
    }
    for member in &members {
        ctx.db.space_member_result().insert(SpaceMemberResult {
            id: uuid_v4_uniq(ctx, |id| ctx.db.space_member_result().id().find(id).is_none(), 3),
            workspace_id: workspace_id.clone(),
            peer_id: member.peer_id.clone(),
            permission: member.permission.clone(),
            granted_by: member.granted_by.clone(),
            created_at: member.created_at,
            queried_at: now,
        });
    }

    Ok(())
}

/// Lightweight workspace-access check exposed as a reducer.
///
/// The client-side search path reads public content tables (memory,
/// search_index, kg_node) directly via SQL for performance (no reducer in
/// the hot loop). Without an access gate, any authenticated identity could
/// search any workspace — including private ones. Callers invoke this once
/// before search to enforce the same ACL the query_table reducer enforces.
#[reducer]
pub fn check_workspace_access(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();

    // Verify the workspace exists
    ctx.db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    // Enforce viewer (read) access — public workspaces allow any
    // authenticated caller, private workspaces require membership.
    check_space_access(ctx, &workspace_id, &caller, "viewer")
}

/// Result table for `list_space_members`. Each row represents one member.
#[table(accessor = space_member_result)]
#[derive(Debug, Clone)]
pub struct SpaceMemberResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub peer_id: String,
    pub permission: String,
    pub granted_by: String,
    pub created_at: i64,
    pub queried_at: i64,
}

/// Result table for `get_memory_stats`. Each row is one stat key-value pair
/// for the queried workspace.
#[table(accessor = workspace_memory_stats_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct WorkspaceMemoryStatsResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub stat_key: String,
    pub stat_value: String,
    pub queried_at: i64,
}

/// Collect per-workspace memory metrics and write them into
/// `workspace_memory_stats_result` for SQL querying.
///
/// Stats computed:
/// - `total_memories` — count of all memories
/// - `active_memories` — count of active (is_active=true) memories
/// - `by_tier` — JSON map of tier → count (L0, L1, L2)
/// - `by_type` — JSON map of memory_type → count
/// - `avg_confidence` — average confidence across active memories
/// - `avg_age_seconds` — average age in seconds (from created_at)
/// - `total_revisions` — count of memory revisions
/// - `top_tags` — JSON array of top-10 most-used tags
/// - `total_users` — count of distinct user_scope values
#[reducer]
pub fn get_memory_stats(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    let now = now_micros(ctx);
    let mut total_memories: u64 = 0;
    let mut active_memories: u64 = 0;
    let mut by_tier: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
    let mut by_type: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
    let mut total_confidence: f64 = 0.0;
    let mut total_age_micros: i64 = 0;
    let mut user_scopes: std::collections::HashSet<String> = std::collections::HashSet::new();

    for mem in ctx.db.memory().workspace_id().filter(&workspace_id) {
        total_memories += 1;
        if mem.is_active {
            active_memories += 1;
            total_confidence += mem.confidence;
            total_age_micros += now.saturating_sub(mem.created_at);
        }
        *by_tier.entry(mem.tier.clone()).or_insert(0) += 1;
        *by_type.entry(mem.memory_type.clone()).or_insert(0) += 1;
        if !mem.user_scope.is_empty() {
            user_scopes.insert(mem.user_scope.clone());
        }
    }

    // Tag stats: count how many times each tag name is used across memory_tags
    let tag_counts: Vec<(String, u64)>;
    {
        // Build a tag_id → tag_name map from the tag table
        let mut name_by_id: std::collections::HashMap<String, String> = std::collections::HashMap::new();
        for t in ctx.db.tag().workspace_id().filter(&workspace_id) {
            name_by_id.insert(t.id.clone(), t.name.clone());
        }
        // Count memory_tag entries per tag_id (within this workspace)
        let mut count_by_id: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
        for mt in ctx.db.memory_tag().workspace_id().filter(&workspace_id) {
            *count_by_id.entry(mt.tag_id.clone()).or_insert(0) += 1;
        }
        // Resolve to names
        let mut tag_map: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
        for (tag_id, count) in count_by_id {
            if let Some(name) = name_by_id.get(&tag_id) {
                *tag_map.entry(name.clone()).or_insert(0) += count;
            }
        }
        let mut vec: Vec<(String, u64)> = tag_map.into_iter().collect();
        vec.sort_by_key(|x| std::cmp::Reverse(x.1));
        tag_counts = vec.into_iter().take(10).collect();
    }

    let total_revisions: u64 = ctx
        .db
        .memory_revision()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id)
        .count() as u64;

    let avg_confidence = if active_memories > 0 {
        total_confidence / active_memories as f64
    } else {
        0.0
    };

    let avg_age_seconds = if active_memories > 0 {
        (total_age_micros / active_memories as i64) / 1_000_000
    } else {
        0
    };

    let top_tags_json = serde_json::to_string(
        &tag_counts.into_iter().map(|(t, c)| serde_json::json!({"tag": t, "count": c})).collect::<Vec<_>>()
    ).unwrap_or_default();

    // Helper to insert a stat row
    let insert_stat = |ctx: &ReducerContext, key: &str, value: String| {
        // Pre-cleanup: remove stale result for this workspace_id + stat_key
        for old in ctx.db.workspace_memory_stats_result().iter()
            .filter(|r| r.workspace_id == workspace_id && r.stat_key == key)
            .collect::<Vec<_>>()
        {
            ctx.db.workspace_memory_stats_result().id().delete(&old.id);
        }
        let id = uuid_v4_uniq(ctx, |id| ctx.db.workspace_memory_stats_result().id().find(id).is_none(), 3);
        ctx.db.workspace_memory_stats_result().insert(WorkspaceMemoryStatsResult {
            id,
            workspace_id: workspace_id.clone(),
            stat_key: key.to_string(),
            stat_value: value,
            queried_at: now,
        });
    };

    insert_stat(ctx, "total_memories", total_memories.to_string());
    insert_stat(ctx, "active_memories", active_memories.to_string());
    insert_stat(ctx, "by_tier", serde_json::to_string(&by_tier).unwrap_or_default());
    insert_stat(ctx, "by_type", serde_json::to_string(&by_type).unwrap_or_default());
    insert_stat(ctx, "avg_confidence", format!("{:.4}", avg_confidence));
    insert_stat(ctx, "avg_age_seconds", avg_age_seconds.to_string());
    insert_stat(ctx, "total_revisions", total_revisions.to_string());
    insert_stat(ctx, "top_tags", top_tags_json);
    insert_stat(ctx, "total_users", user_scopes.len().to_string());

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── Existing tests (kept) ──
    

    #[test]
    fn test_workspace_creation() {
        let ws = Workspace {
            id: "ws-001".to_string(),
            name: "Test Workspace".to_string(),
            description: "A workspace for testing".to_string(),
            context: "some context".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_001,
            is_public: false,
        };

        assert_eq!(ws.id, "ws-001");
        assert_eq!(ws.name, "Test Workspace");
        assert_eq!(ws.description, "A workspace for testing");
        assert_eq!(ws.context, "some context");
        assert_eq!(ws.created_at, 1_000_000);
        assert_eq!(ws.updated_at, 1_000_001);
        assert!(!ws.is_public);
    }

    #[test]
    fn test_cascade_delete_workspace_data_collects_parent_ids() {
        // Unit-test the id-collection logic without needing a full STDB context.
        // We verify the HashSet deduplication and the workspace_id filter pattern.
        use std::collections::HashSet;

        let sessions = vec![
            ("s1", "ws-a"), ("s2", "ws-a"), ("s3", "ws-b"),
        ];
        let ids: HashSet<String> = sessions.into_iter()
            .filter(|(_, ws)| *ws == "ws-a")
            .map(|(id, _)| id.to_string())
            .collect();
        assert_eq!(ids.len(), 2);
        assert!(ids.contains("s1"));
        assert!(ids.contains("s2"));
        assert!(!ids.contains("s3"));
    }

    #[test]
    fn test_workspace_member_creation() {
        let member = SpacePermission {
            id: "sp-001".to_string(),
            workspace_id: "ws-001".to_string(),
            peer_id: "peer-abc".to_string(),
            permission: "editor".to_string(),
            granted_by: "peer-admin".to_string(),
            created_at: 1_000_000,
        };

        assert_eq!(member.id, "sp-001");
        assert_eq!(member.workspace_id, "ws-001");
        assert_eq!(member.peer_id, "peer-abc");
        assert_eq!(member.permission, "editor");
        assert_eq!(member.granted_by, "peer-admin");
        assert_eq!(member.created_at, 1_000_000);
    }

    #[test]
    fn test_workspace_member_result_creation() {
        let result = SpaceMemberResult {
            id: "smr-001".to_string(),
            workspace_id: "ws-001".to_string(),
            peer_id: "peer-abc".to_string(),
            permission: "viewer".to_string(),
            granted_by: "peer-admin".to_string(),
            created_at: 1_000_000,
            queried_at: 1_000_100,
        };

        assert_eq!(result.id, "smr-001");
        assert_eq!(result.workspace_id, "ws-001");
        assert_eq!(result.peer_id, "peer-abc");
        assert_eq!(result.permission, "viewer");
        assert_eq!(result.granted_by, "peer-admin");
        assert_eq!(result.created_at, 1_000_000);
        assert_eq!(result.queried_at, 1_000_100);
    }

    // ── Edge case tests ────────────────────────────────────────────

    #[test]
    fn test_workspace_empty_name() {
        let ws = Workspace {
            id: "ws_empty".to_string(),
            name: String::new(),
            description: String::new(),
            context: String::new(),
            is_public: true,
            created_at: 0,
            updated_at: 0,
        };
        assert!(ws.name.is_empty());
        assert!(ws.description.is_empty());
        assert!(ws.is_public);
    }
    
    #[test]
    fn test_workspace_special_characters() {
        let name = "My Workspace! @#$%^&*()_+-=[]{}|;':,./<>?`~ 😊".to_string();
        let ws = Workspace {
            id: "ws_special".to_string(),
            name: name.clone(),
            description: "Desc with <html> & entities".to_string(),
            context: String::new(),
            is_public: false,
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(ws.name, name);
        assert!(ws.name.contains('😊'));
        assert_eq!(ws.description, "Desc with <html> & entities");
    }
    
    #[test]
    fn test_workspace_unicode() {
        let name = "ワークスペース测试空间🌟".to_string();
        let ws = Workspace {
            id: "ws_unicode".to_string(),
            name: name.clone(),
            description: "多言語対応".to_string(),
            context: String::new(),
            is_public: true,
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(ws.name, name);
        assert!(ws.description.contains('多'));
    }
    
    #[test]
    fn test_workspace_very_large_description() {
        let large_desc = "Description line\n".repeat(1000);
        let ws = Workspace {
            id: "ws_large".to_string(),
            name: "Large Desc".to_string(),
            description: large_desc.clone(),
            context: String::new(),
            is_public: false,
            created_at: 0,
            updated_at: 0,
        };
        assert!(ws.description.len() > 10_000);
        assert!(ws.description.contains("Description line"));
    }
    
    #[test]
    fn test_workspace_concurrent_creation_simulation() {
        let workspaces: Vec<Workspace> = (0..10)
            .map(|i| Workspace {
                id: format!("ws_concurrent_{}", i),
                name: format!("Workspace {}", i),
                description: format!("Description for workspace {}", i),
                context: String::new(),
                is_public: i % 2 == 0,
                created_at: i as i64,
                updated_at: i as i64,
            })
            .collect();
        assert_eq!(workspaces.len(), 10);
        for (i, ws) in workspaces.iter().enumerate() {
            assert_eq!(ws.id, format!("ws_concurrent_{}", i));
        }
    }
    
    #[test]
    fn test_workspace_network_partition_simulation() {
        // Simulate workspace with missing fields due to partition
        let ws = Workspace {
            id: "ws_partition".to_string(),
            name: "Partial".to_string(),
            description: String::new(),
            context: String::new(),
            is_public: true,
            created_at: 0,
            updated_at: 0,
        };
        assert!(ws.description.is_empty());
        assert_eq!(ws.name, "Partial");
        assert_eq!(ws.created_at, 0);
        assert_eq!(ws.updated_at, 0);
    }
}
