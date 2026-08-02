use spacetimedb::*;
use crate::memory::memory;
use crate::auth::require_auth;
use crate::trace_span;
use crate::tracing::TracingSpanKind;
use crate::workspace::check_space_access;

use crate::{now_micros, uuid_v7};

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// A hierarchical context directory (OpenViking concept).
/// Directories form a tree structure via `parent_id`.
#[table(accessor = context_directory)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ContextDirectory {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub name: String,
    /// e.g. "/user/preferences"
    pub path: String,
    /// Parent directory id; "" if root
    #[index(btree)]
    pub parent_id: String,
    pub description: String,
    pub created_at: i64,
    pub updated_at: i64,
}

/// Stores results from directory queries (children, traversal, lookup).
/// Clients read this table after calling directory reducers, keyed by `query_hash`.
#[table(accessor = directory_result)]
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
#[table(accessor = directory_memory_link)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DirectoryMemoryLink {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub directory_id: String,
    pub memory_id: String,
    #[index(btree)]
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
    trace_span!(ctx, "create_directory", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let dir = ContextDirectory {
        id: id.clone(),
        workspace_id: workspace_id.clone(),
        name,
        path,
        parent_id,
        description,
        created_at: now,
        updated_at: now,
    };

    ctx.db.context_directory().insert(dir);
    Ok(())
    })
}

#[reducer]
pub fn delete_directory(ctx: &ReducerContext, id: String) -> Result<(), String> {
    trace_span!(ctx, "delete_directory", TracingSpanKind::Write, "", {
    let _account = require_auth(ctx)?;
    // Check it exists
    let _dir = ctx
        .db
        .context_directory()
        .id()
        .find(&id)
        .ok_or_else(|| format!("ContextDirectory '{}' not found", id))?;

    ctx.db.context_directory().id().delete(&id);
    Ok(())
    })
}

/// Get immediate children of a directory. If `include_memories` is true,
/// also returns memories linked to this directory via `DirectoryMemoryLink`.
#[reducer]
pub fn get_children(
    ctx: &ReducerContext,
    directory_id: String,
    include_memories: bool,
) -> Result<(), String> {
    trace_span!(ctx, "get_children", TracingSpanKind::Read, "", {
    let _account = require_auth(ctx)?;
    // Verify directory exists
    let dir = ctx
        .db
        .context_directory()
        .id()
        .find(&directory_id)
        .ok_or_else(|| format!("ContextDirectory '{}' not found", directory_id))?;

    let workspace_id = dir.workspace_id;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    // Pre-cleanup: remove stale results for this workspace_id + query_hash
    for old in ctx.db.directory_result().iter()
        .filter(|r| r.workspace_id == workspace_id && r.query_hash == directory_id)
        .collect::<Vec<_>>()
    {
        ctx.db.directory_result().id().delete(&old.id);
    }

    // Emit child directories
    for child in ctx
        .db
        .context_directory()
        .parent_id().filter(&directory_id)
    {
        let id = uuid_v7(ctx);
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
            .directory_id().filter(&directory_id)
            .take(crate::MAX_RESULTS)
        {
            if let Some(mem) = ctx.db.memory().id().find(&link.memory_id) {
                let id = uuid_v7(ctx);
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
    })
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
    trace_span!(ctx, "traverse_recursive", TracingSpanKind::Read, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;
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

    // Pre-cleanup: remove stale results for this workspace_id + query_hash
    for old in ctx.db.directory_result().iter()
        .filter(|r| r.workspace_id == workspace_id && r.query_hash == root_directory_id)
        .collect::<Vec<_>>()
    {
        ctx.db.directory_result().id().delete(&old.id);
    }

    while let Some((current_id, depth)) = queue.pop() {
        if depth >= max_depth {
            continue;
        }

        let next_depth = depth + 1;

        for child in ctx
            .db
            .context_directory()
            .parent_id().filter(&current_id)
        {
            if !visited.contains(&child.id) {
                visited.insert(child.id.clone());

                let id = uuid_v7(ctx);
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
    })
}

/// Get a directory by either its id or its path (scoped to workspace_id).
/// Stores the result in `directory_result` with depth 0.
#[reducer]
pub fn get_directory(
    ctx: &ReducerContext,
    workspace_id: String,
    path_or_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_directory", TracingSpanKind::Read, &workspace_id.clone(), {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;
    // Try lookup by id first
    if let Some(dir) = ctx.db.context_directory().id().find(&path_or_id) {
        // Pre-cleanup: remove stale results for this workspace_id + query_hash
        for old in ctx.db.directory_result().iter()
            .filter(|r| r.workspace_id == workspace_id && r.query_hash == path_or_id)
            .collect::<Vec<_>>()
        {
            ctx.db.directory_result().id().delete(&old.id);
        }
        let id = uuid_v7(ctx);
        ctx.db.directory_result().insert(DirectoryResult {
            id,
            workspace_id: workspace_id.clone(),
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
        .iter().take(crate::MAX_RESULTS)
        .find(|d| d.path == path_or_id && d.workspace_id == workspace_id)
    {
        // Pre-cleanup: remove stale results for this workspace_id + query_hash
        for old in ctx.db.directory_result().iter()
            .filter(|r| r.workspace_id == workspace_id && r.query_hash == dir.id)
            .collect::<Vec<_>>()
        {
            ctx.db.directory_result().id().delete(&old.id);
        }
        let id = uuid_v7(ctx);
        ctx.db.directory_result().insert(DirectoryResult {
            id,
            workspace_id: workspace_id.clone(),
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
    })
}

/// Link a memory to a directory.
#[reducer]
pub fn link_memory_to_directory(
    ctx: &ReducerContext,
    directory_id: String,
    memory_id: String,
    workspace_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "link_memory_to_directory", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
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
        .directory_id().filter(&directory_id)
        .take(crate::MAX_RESULTS)
        .any(|l| l.memory_id == memory_id)
    {
        return Err(format!(
            "Memory '{}' is already linked to directory '{}'",
            memory_id, directory_id
        ));
    }

    let id = uuid_v7(ctx);
    ctx.db.directory_memory_link().insert(DirectoryMemoryLink {
        id,
        directory_id,
        memory_id,
        workspace_id: workspace_id.clone(),
    });

    Ok(())
    })
}

/// Unlink a memory from a directory.
#[reducer]
pub fn unlink_memory_from_directory(
    ctx: &ReducerContext,
    directory_id: String,
    memory_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "unlink_memory_from_directory", TracingSpanKind::Write, "", {
    let _account = require_auth(ctx)?;
    // Find the link row
    let link = ctx
        .db
        .directory_memory_link()
        .directory_id().filter(&directory_id)
        .take(crate::MAX_RESULTS)
        .find(|l| l.memory_id == memory_id)
        .ok_or_else(|| {
            format!(
                "No link found between directory '{}' and memory '{}'",
                directory_id, memory_id
            )
        })?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &link.workspace_id, &caller, "editor")?;

    ctx.db.directory_memory_link().id().delete(&link.id);
    Ok(())
    })
}
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_context_directory_initialization() {
        let dir = ContextDirectory {
            id: "dir_001".to_string(),
            workspace_id: "ws_001".to_string(),
            name: "User Preferences".to_string(),
            path: "/user/preferences".to_string(),
            parent_id: String::new(),
            description: "User preference settings".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(dir.id, "dir_001");
        assert_eq!(dir.name, "User Preferences");
        assert_eq!(dir.path, "/user/preferences");
        assert!(dir.parent_id.is_empty());
        assert_eq!(dir.created_at, 1_000_000);
    }

    #[test]
    fn test_context_directory_serde_roundtrip() {
        let dir = ContextDirectory {
            id: "dir_002".to_string(),
            workspace_id: "ws_002".to_string(),
            name: "Agent Memory".to_string(),
            path: "/agent/memory".to_string(),
            parent_id: "dir_root".to_string(),
            description: "Agent's persistent memory store".to_string(),
            created_at: 2_000_000,
            updated_at: 3_000_000,
        };
        let json = serde_json::to_string(&dir).expect("serialize");
        let deserialized: ContextDirectory = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, dir.id);
        assert_eq!(deserialized.name, dir.name);
        assert_eq!(deserialized.path, dir.path);
        assert_eq!(deserialized.parent_id, dir.parent_id);
        assert_eq!(deserialized.description, dir.description);
    }

    #[test]
    fn test_context_directory_nested_hierarchy() {
        let root = ContextDirectory {
            id: "root".to_string(),
            workspace_id: "ws_003".to_string(),
            name: "Root".to_string(),
            path: "/".to_string(),
            parent_id: String::new(),
            description: "Root directory".to_string(),
            created_at: 0,
            updated_at: 0,
        };
        let child = ContextDirectory {
            id: "child_001".to_string(),
            workspace_id: "ws_003".to_string(),
            name: "Child".to_string(),
            path: "/child".to_string(),
            parent_id: root.id.clone(),
            description: "Child of root".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(child.parent_id, root.id);
        assert_eq!(root.workspace_id, child.workspace_id);
    }

    #[test]
    fn test_directory_result_initialization() {
        let result = DirectoryResult {
            id: "dr_001".to_string(),
            workspace_id: "ws_001".to_string(),
            query_hash: "dir_001".to_string(),
            entity_type: "directory".to_string(),
            entity_id: "sub_001".to_string(),
            name: "Subdir".to_string(),
            path: "/parent/subdir".to_string(),
            depth: 2,
            parent_id: "dir_001".to_string(),
            description: "A subdirectory".to_string(),
        };
        assert_eq!(result.entity_type, "directory");
        assert_eq!(result.depth, 2);
        assert_eq!(result.path, "/parent/subdir");
    }

    #[test]
    fn test_directory_result_memory_type() {
        let result = DirectoryResult {
            id: "dr_002".to_string(),
            workspace_id: "ws_002".to_string(),
            query_hash: "dir_002".to_string(),
            entity_type: "memory".to_string(),
            entity_id: "mem_001".to_string(),
            name: "Important memory".to_string(),
            path: String::new(),
            depth: 0,
            parent_id: String::new(),
            description: "experience".to_string(),
        };
        assert_eq!(result.entity_type, "memory");
        assert!(result.path.is_empty());
        assert_eq!(result.depth, 0);
    }

    #[test]
    fn test_directory_memory_link_initialization() {
        let link = DirectoryMemoryLink {
            id: "link_001".to_string(),
            directory_id: "dir_001".to_string(),
            memory_id: "mem_001".to_string(),
            workspace_id: "ws_001".to_string(),
        };
        assert_eq!(link.directory_id, "dir_001");
        assert_eq!(link.memory_id, "mem_001");
    }

    #[test]
    fn test_directory_memory_link_serde() {
        let link = DirectoryMemoryLink {
            id: "link_serde".to_string(),
            directory_id: "dir_serde".to_string(),
            memory_id: "mem_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
        };
        let json = serde_json::to_string(&link).expect("serialize");
        let deserialized: DirectoryMemoryLink = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, link.id);
        assert_eq!(deserialized.directory_id, link.directory_id);
        assert_eq!(deserialized.memory_id, link.memory_id);
    }
}

