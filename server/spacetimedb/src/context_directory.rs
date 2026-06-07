use spacetimedb::*;

use crate::{memory::memory, now_micros, uuid_v4};

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// A hierarchical context directory (OpenViking concept).
/// Directories form a tree structure via `parent_id`.
#[table(accessor = context_directory, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
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

/// Stores results from directory queries (children, traversal, lookup).
/// Clients read this table after calling directory reducers, keyed by `query_hash`.
#[table(accessor = directory_result, public)]
#[derive(Debug, Clone)]
pub struct DirectoryResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Groups results for a single query; typically the directory_id or root_id
    pub query_hash: String,
    /// "directory" | "memory"
    pub entity_type: String,
    pub entity_id: String,
    pub name: String,
    pub path: String,
    pub depth: i64,
    pub parent_id: String,
    pub description: String,
}

/// Links memories to directories for hierarchical organisation.
#[table(accessor = directory_memory_link, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DirectoryMemoryLink {
    #[primary_key]
    pub id: String,
    pub directory_id: String,
    pub memory_id: String,
    pub workspace_id: String,
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_directory(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    path: String,
    parent_id: String,
    description: String,
) -> Result<(), String> {
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

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

/// Get immediate children of a directory. If `include_memories` is true,
/// also returns memories linked to this directory via `DirectoryMemoryLink`.
#[reducer]
pub fn get_children(
    ctx: &ReducerContext,
    directory_id: String,
    include_memories: bool,
) -> Result<(), String> {
    // Verify directory exists
    let dir = ctx
        .db
        .context_directory()
        .id()
        .find(&directory_id)
        .ok_or_else(|| format!("ContextDirectory '{}' not found", directory_id))?;

    let workspace_id = dir.workspace_id;

    // Emit child directories
    for child in ctx
        .db
        .context_directory()
        .iter()
        .filter(|d| d.parent_id == directory_id)
    {
        let id = uuid_v4(ctx);
        ctx.db.directory_result().insert(DirectoryResult {
            id,
            workspace_id: workspace_id.clone(),
            query_hash: directory_id.clone(),
            entity_type: "directory".to_string(),
            entity_id: child.id.clone(),
            name: child.name.clone(),
            path: child.path.clone(),
            depth: 1,
            parent_id: child.parent_id.clone(),
            description: child.description.clone(),
        });
    }

    // Optionally emit linked memories
    if include_memories {
        for link in ctx
            .db
            .directory_memory_link()
            .iter()
            .filter(|l| l.directory_id == directory_id)
        {
            if let Some(mem) = ctx.db.memory().id().find(&link.memory_id) {
                let id = uuid_v4(ctx);
                ctx.db.directory_result().insert(DirectoryResult {
                    id,
                    workspace_id: workspace_id.clone(),
                    query_hash: directory_id.clone(),
                    entity_type: "memory".to_string(),
                    entity_id: mem.id.clone(),
                    name: mem.summary.clone(),
                    path: String::new(),
                    depth: 1,
                    parent_id: directory_id.clone(),
                    description: mem.memory_type.clone(),
                });
            }
        }
    }

    Ok(())
}

/// BFS traversal to get all descendants of `root_directory_id`.
/// Stores results in `directory_result` keyed by root_directory_id.
/// Max depth is 10 to prevent runaway recursion.
#[reducer]
pub fn traverse_recursive(
    ctx: &ReducerContext,
    workspace_id: String,
    root_directory_id: String,
) -> Result<(), String> {
    // Verify root directory exists
    let _root = ctx
        .db
        .context_directory()
        .id()
        .find(&root_directory_id)
        .ok_or_else(|| format!("Root ContextDirectory '{}' not found", root_directory_id))?;

    let max_depth: i64 = 10;
    let mut queue: Vec<(String, i64)> = vec![(root_directory_id.clone(), 0)];
    let mut visited = std::collections::HashSet::new();
    visited.insert(root_directory_id.clone());

    while let Some((current_id, depth)) = queue.pop() {
        if depth >= max_depth {
            continue;
        }

        let next_depth = depth + 1;

        for child in ctx
            .db
            .context_directory()
            .iter()
            .filter(|d| d.parent_id == current_id)
        {
            if !visited.contains(&child.id) {
                visited.insert(child.id.clone());

                let id = uuid_v4(ctx);
                ctx.db.directory_result().insert(DirectoryResult {
                    id,
                    workspace_id: workspace_id.clone(),
                    query_hash: root_directory_id.clone(),
                    entity_type: "directory".to_string(),
                    entity_id: child.id.clone(),
                    name: child.name.clone(),
                    path: child.path.clone(),
                    depth: next_depth,
                    parent_id: child.parent_id.clone(),
                    description: child.description.clone(),
                });

                queue.push((child.id.clone(), next_depth));
            }
        }
    }

    Ok(())
}

/// Get a directory by either its id or its path (scoped to workspace_id).
/// Stores the result in `directory_result` with depth 0.
#[reducer]
pub fn get_directory(
    ctx: &ReducerContext,
    workspace_id: String,
    path_or_id: String,
) -> Result<(), String> {
    // Try lookup by id first
    if let Some(dir) = ctx.db.context_directory().id().find(&path_or_id) {
        let id = uuid_v4(ctx);
        ctx.db.directory_result().insert(DirectoryResult {
            id,
            workspace_id,
            query_hash: path_or_id,
            entity_type: "directory".to_string(),
            entity_id: dir.id.clone(),
            name: dir.name.clone(),
            path: dir.path.clone(),
            depth: 0,
            parent_id: dir.parent_id.clone(),
            description: dir.description.clone(),
        });
        return Ok(());
    }

    // Fallback: lookup by path scoped to workspace
    if let Some(dir) = ctx
        .db
        .context_directory()
        .iter()
        .find(|d| d.path == path_or_id && d.workspace_id == workspace_id)
    {
        let id = uuid_v4(ctx);
        ctx.db.directory_result().insert(DirectoryResult {
            id,
            workspace_id,
            query_hash: dir.id.clone(),
            entity_type: "directory".to_string(),
            entity_id: dir.id.clone(),
            name: dir.name.clone(),
            path: dir.path.clone(),
            depth: 0,
            parent_id: dir.parent_id.clone(),
            description: dir.description.clone(),
        });
        return Ok(());
    }

    Err(format!(
        "ContextDirectory not found for id or path: '{}'",
        path_or_id
    ))
}

/// Link a memory to a directory.
#[reducer]
pub fn link_memory_to_directory(
    ctx: &ReducerContext,
    directory_id: String,
    memory_id: String,
    workspace_id: String,
) -> Result<(), String> {
    // Verify directory exists
    ctx.db
        .context_directory()
        .id()
        .find(&directory_id)
        .ok_or_else(|| format!("ContextDirectory '{}' not found", directory_id))?;

    // Verify memory exists
    ctx.db
        .memory()
        .id()
        .find(&memory_id)
        .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;

    // Check for duplicate link
    if ctx
        .db
        .directory_memory_link()
        .iter()
        .any(|l| l.directory_id == directory_id && l.memory_id == memory_id)
    {
        return Err(format!(
            "Memory '{}' is already linked to directory '{}'",
            memory_id, directory_id
        ));
    }

    let id = uuid_v4(ctx);
    ctx.db.directory_memory_link().insert(DirectoryMemoryLink {
        id,
        directory_id,
        memory_id,
        workspace_id,
    });

    Ok(())
}

/// Unlink a memory from a directory.
#[reducer]
pub fn unlink_memory_from_directory(
    ctx: &ReducerContext,
    directory_id: String,
    memory_id: String,
) -> Result<(), String> {
    // Find the link row
    let link = ctx
        .db
        .directory_memory_link()
        .iter()
        .find(|l| l.directory_id == directory_id && l.memory_id == memory_id)
        .ok_or_else(|| {
            format!(
                "No link found between directory '{}' and memory '{}'",
                directory_id, memory_id
            )
        })?;

    ctx.db.directory_memory_link().id().delete(&link.id);
    Ok(())
}
