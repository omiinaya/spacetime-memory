use spacetimedb::*;

use crate::{now_micros, uuid_v4};
use crate::auth;

/// A workspace representing a project, agent-world, or sandbox.
#[table(accessor = workspace, public)]
#[derive(Debug, Clone)]
pub struct Workspace {
    #[primary_key]
    pub id: String,
    pub name: String,
    pub description: String,
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
#[table(accessor = space_permission, public)]
#[derive(Debug, Clone)]
pub struct SpacePermission {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub peer_id: String,      // who has access
    pub permission: String,   // "owner", "editor", "viewer"
    pub granted_by: String,   // peer_id who granted access
    pub created_at: i64,
}

// ── Workspace reducers ────────────────────────────────────────────────

#[reducer]
pub fn create_workspace(ctx: &ReducerContext, name: String, description: String, id: String) -> Result<(), String> {
    let now = now_micros(ctx);
    let workspace_id = if id.is_empty() { uuid_v4(ctx) } else { id };
    let caller = ctx.sender().to_hex();

    ctx.db.workspace().insert(Workspace {
        id: workspace_id.clone(),
        name,
        description,
        created_at: now,
        updated_at: now,
        is_public: false,
    });

    // Auto-grant owner access to the workspace creator
    ctx.db.space_permission().insert(SpacePermission {
        id: uuid_v4(ctx),
        workspace_id: workspace_id.clone(),
        peer_id: caller.to_string(),
        permission: "owner".to_string(),
        granted_by: caller.to_string(),
        created_at: now,
    });

    Ok(())
}

#[reducer]
pub fn update_workspace(ctx: &ReducerContext, id: String, name: String, description: String) -> Result<(), String> {
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
        created_at: existing.created_at,
        updated_at: now_micros(ctx),
        is_public: existing.is_public,
    });
    Ok(())
}

#[reducer]
pub fn delete_workspace(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let caller = ctx.sender().to_hex().to_string();

    ctx.db
        .workspace()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Workspace '{}' not found", id))?;

    // Only owner or admin can delete a workspace
    check_space_access(ctx, &id, &caller, "owner")?;

    let permissions: Vec<SpacePermission> = ctx
        .db
        .space_permission()
        .iter()
        .filter(|sp: &SpacePermission| sp.workspace_id == id)
        .collect();
    for perm in permissions {
        ctx.db.space_permission().id().delete(&perm.id);
    }

    ctx.db.workspace().id().delete(&id);
    Ok(())
}

// ── Workspace visibility ───────────────────────────────────────────────

/// Toggle whether a workspace is public (viewable by anyone) or private
/// (requires explicit permission). Only owners can change visibility.
#[reducer]
pub fn set_workspace_visibility(ctx: &ReducerContext, workspace_id: String, is_public: bool) -> Result<(), String> {
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
    let direct = ctx.db.space_permission().iter().find(
        |sp: &SpacePermission| sp.workspace_id == workspace_id && sp.peer_id == peer_id,
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
        || ctx.db.space_permission().iter().any(|sp: SpacePermission| {
            sp.workspace_id == workspace_id && sp.peer_id == caller && sp.permission == "owner"
        });

    if !is_admin_or_owner {
        return Err("Only an owner or admin can grant access".to_string());
    }

    // Check for existing permission — update or insert
    let now = now_micros(ctx);
    let existing = ctx
        .db
        .space_permission()
        .iter()
        .find(|sp: &SpacePermission| sp.workspace_id == workspace_id && sp.peer_id == peer_id);

    if let Some(existing) = existing {
        // Update existing permission
        let updated = SpacePermission {
            permission: permission.clone(),
            granted_by: caller.clone(),
            ..existing
        };
        ctx.db.space_permission().id().update(updated);
    } else {
        // Insert new permission
        ctx.db.space_permission().insert(SpacePermission {
            id: uuid_v4(ctx),
            workspace_id: workspace_id.clone(),
            peer_id: peer_id.clone(),
            permission: permission.clone(),
            granted_by: caller.clone(),
            created_at: now,
        });
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
    let caller = ctx.sender().to_hex().to_string();

    // Verify the workspace exists
    ctx.db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    // Only an existing owner or admin can revoke access
    let is_admin_or_owner = auth::is_admin(&caller, ctx)
        || ctx.db.space_permission().iter().any(|sp: SpacePermission| {
            sp.workspace_id == workspace_id && sp.peer_id == caller && sp.permission == "owner"
        });

    if !is_admin_or_owner {
        return Err("Only an owner or admin can revoke access".to_string());
    }

    // Cannot revoke your own access (unless admin revoking a non-self peer)
    if caller == peer_id {
        return Err("Cannot revoke your own access. Have another owner do it.".to_string());
    }

    // Find and delete the permission record
    let existing = ctx.db.space_permission().iter()
        .find(|sp: &SpacePermission| sp.workspace_id == workspace_id && sp.peer_id == peer_id)
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
    let caller = ctx.sender().to_hex().to_string();

    // Verify the workspace exists
    ctx.db
        .workspace()
        .id()
        .find(&workspace_id)
        .ok_or_else(|| format!("Workspace '{}' not found", workspace_id))?;

    // Check the caller has at least viewer access
    let has_access = ctx
        .db
        .space_permission()
        .iter()
        .any(|sp: SpacePermission| sp.workspace_id == workspace_id && sp.peer_id == caller);

    if !has_access {
        return Err(format!(
            "Access denied: you do not have access to workspace '{}'",
            workspace_id
        ));
    }

    // Gather all members
    let members: Vec<SpacePermission> = ctx
        .db
        .space_permission()
        .iter()
        .filter(|sp: &SpacePermission| sp.workspace_id == workspace_id)
        .collect();

    // Store results in a result table for SQL querying
    let now = now_micros(ctx);
    for member in &members {
        ctx.db.space_member_result().insert(SpaceMemberResult {
            id: uuid_v4(ctx),
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

/// Result table for `list_space_members`. Each row represents one member.
#[table(accessor = space_member_result, public)]
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
