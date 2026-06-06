use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// A hierarchical context directory (OpenViking concept).
/// Directories form a tree structure via `parent_id`.
#[table(accessor = context_directory, public)]
#[derive(Debug, Clone)]
pub struct ContextDirectory {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    /// e.g. "/user/preferences"
    pub path: String,
    /// Parent directory id; "" if root
    pub parent_id: String,
    pub description: String,
    pub created_at: i64,
    pub updated_at: i64,
}

#[reducer]
pub fn create_directory(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    path: String,
    parent_id: String,
    description: String,
) -> Result<(), String> {
    let now = now_micros();
    let id = uuid_v4();

    let dir = ContextDirectory {
        id: id.clone(),
        workspace_id,
        name,
        path,
        parent_id,
        description,
        created_at: now,
        updated_at: now,
    };

    ctx.db.context_directory().insert(dir);
    Ok(())
}

#[reducer]
pub fn delete_directory(ctx: &ReducerContext, id: String) -> Result<(), String> {
    // Check it exists
    let _dir = ctx
        .db
        .context_directory()
        .id()
        .find(&id)
        .ok_or_else(|| format!("ContextDirectory '{}' not found", id))?;

    ctx.db.context_directory().id().delete(&id);
    Ok(())
}
