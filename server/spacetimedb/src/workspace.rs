use spacetimedb::*;

use crate::{now_micros, uuid_v4};

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
}

#[reducer]
pub fn create_workspace(ctx: &ReducerContext, name: String, description: String) -> Result<(), String> {
    let now = now_micros();
    let id = uuid_v4();

    ctx.db.workspace().insert(Workspace {
        id: id.clone(),
        name,
        description,
        created_at: now,
        updated_at: now,
    });
    Ok(())
}

#[reducer]
pub fn update_workspace(ctx: &ReducerContext, id: String, name: String, description: String) -> Result<(), String> {
    let existing = ctx
        .db
        .workspace()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Workspace '{}' not found", id))?;

    ctx.db.workspace().id().update(Workspace {
        id: id.clone(),
        name,
        description,
        created_at: existing.created_at,
        updated_at: now_micros(),
    });
    Ok(())
}

#[reducer]
pub fn delete_workspace(ctx: &ReducerContext, id: String) -> Result<(), String> {
    ctx.db
        .workspace()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Workspace '{}' not found", id))?;

    ctx.db.workspace().id().delete(&id);
    Ok(())
}
