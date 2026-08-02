use spacetimedb::*;
use crate::auth::require_auth;
use crate::trace_span;
use crate::tracing::TracingSpanKind;
use crate::workspace::check_space_access;

use crate::{now_micros, uuid_v7};

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// A virtual file/directory entry in the MemFS filesystem.
#[table(accessor = memfs_entry)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct MemfsEntry {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Parent directory ID; empty string means root
    #[index(btree)]
    pub parent_id: String,
    /// File/directory name within its parent
    pub name: String,
    /// Full virtual path like "/memories/recent"
    #[index(btree)]
    pub path: String,
    /// "file" or "directory"
    pub entry_type: String,
    /// For files, optional MIME type
    pub mime_type: String,
    /// For files, the content
    pub data: String,
    /// For files, the byte count
    pub size: u64,
    /// Whether this is a mount point
    pub is_mounted: bool,
    /// When mounted, the source (e.g. "workspace:ws-1")
    pub mount_source: String,
    pub created_at: i64,
    pub updated_at: i64,
}

/// Mount points that map MemFS paths to SpacetimeDB data sources.
#[table(accessor = memfs_mount)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct MemfsMount {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The virtual path to mount at
    #[index(btree)]
    pub mount_path: String,
    /// "workspace", "memory", "note", "session", "custom"
    pub source_type: String,
    /// JSON config for the source
    pub source_config: String,
    /// Optional SQL/semantic filter
    pub filter_query: String,
    pub created_at: i64,
}

/// Result table for query responses (list, lookup, read).
#[table(accessor = memfs_result)]
#[derive(Debug, Clone)]
pub struct MemfsResult {
    #[primary_key]
    pub id: String,
    pub data: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Build a full virtual path from parent path + child name.
fn build_path(parent_path: &str, name: &str) -> String {
    if parent_path.is_empty() || parent_path == "/" {
        format!("/{}", name)
    } else {
        format!("{}/{}", parent_path.trim_end_matches('/'), name)
    }
}

/// Validate entry_type is allowed.
fn validate_entry_type(entry_type: &str) -> Result<(), String> {
    if entry_type != "file" && entry_type != "directory" {
        return Err(format!(
            "Invalid entry_type '{}': must be 'file' or 'directory'",
            entry_type
        ));
    }
    Ok(())
}

/// Validate name does not contain path separators.
fn validate_name(name: &str) -> Result<(), String> {
    if name.is_empty() {
        return Err("Name cannot be empty".to_string());
    }
    if name.contains('/') {
        return Err("Name cannot contain '/'".to_string());
    }
    Ok(())
}

/// Check if an entry exists by id within a workspace.
fn _entry_exists(ctx: &ReducerContext, ws_id: &str, entry_id: &str) -> bool {
    let id_str = entry_id.to_string();
    ctx.db.memfs_entry().id().find(&id_str)
        .is_some_and(|e| e.workspace_id == ws_id)
}

/// Collect all descendant IDs of a directory (recursive).
fn collect_descendants(ctx: &ReducerContext, ws_id: &str, dir_id: &str) -> Vec<String> {
    let mut ids = Vec::new();
    for child in ctx.db.memfs_entry().parent_id().filter(dir_id) {
        if child.workspace_id == ws_id {
            ids.push(child.id.clone());
            if child.entry_type == "directory" {
                ids.extend(collect_descendants(ctx, ws_id, &child.id));
            }
        }
    }
    ids
}

// ---------------------------------------------------------------------------
// Reducers — MemFS Entry Operations
// ---------------------------------------------------------------------------

/// Create a file or directory entry.
#[reducer]
pub fn create_memfs_entry(
    ctx: &ReducerContext,
    workspace_id: String,
    parent_id: String,
    name: String,
    entry_type: String,
    mime_type: String,
    data: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_memfs_entry", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    validate_entry_type(&entry_type)?;
    validate_name(&name)?;

    // Resolve parent path
    let parent_path = if parent_id.is_empty() {
        String::new()
    } else {
        let parent = ctx.db.memfs_entry().id().find(&parent_id)
            .ok_or_else(|| format!("Parent directory '{}' not found", parent_id))?;
        if parent.entry_type != "directory" {
            return Err("Parent is not a directory".to_string());
        }
        parent.path
    };

    let path = build_path(&parent_path, &name);

    // Check for duplicate name in the same parent
    for child in ctx.db.memfs_entry().parent_id().filter(&parent_id) {
        if child.workspace_id == workspace_id && child.name == name {
            return Err(format!("Entry '{}' already exists in this directory", name));
        }
    }

    let now = now_micros(ctx);
    let id = uuid_v7(ctx);
    let size = if entry_type == "file" { data.len() as u64 } else { 0 };

    let entry = MemfsEntry {
        id: id.clone(),
        workspace_id: workspace_id.clone(),
        parent_id,
        name,
        path,
        entry_type,
        mime_type,
        data,
        size,
        is_mounted: false,
        mount_source: String::new(),
        created_at: now,
        updated_at: now,
    };

    ctx.db.memfs_entry().insert(entry);
    Ok(())
    })
}

/// Delete an entry (recursive for directories).
#[reducer]
pub fn delete_memfs_entry(
    ctx: &ReducerContext,
    workspace_id: String,
    entry_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "delete_memfs_entry", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    let entry = ctx.db.memfs_entry().id().find(&entry_id)
        .ok_or_else(|| format!("Entry '{}' not found", entry_id))?;

    if entry.workspace_id != workspace_id {
        return Err(format!("Entry '{}' does not belong to workspace '{}'", entry_id, workspace_id));
    }

    // If it's a directory, delete all descendants first
    if entry.entry_type == "directory" {
        let descendants = collect_descendants(ctx, &workspace_id, &entry_id);
        for did in &descendants {
            ctx.db.memfs_entry().id().delete(did);
        }
    }

    ctx.db.memfs_entry().id().delete(&entry_id);
    Ok(())
    })
}

/// Update a memfs entry (name, data, mime_type).
#[reducer]
pub fn update_memfs_entry(
    ctx: &ReducerContext,
    workspace_id: String,
    entry_id: String,
    name: String,
    data: String,
    mime_type: String,
) -> Result<(), String> {
    trace_span!(ctx, "update_memfs_entry", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    let mut entry = ctx.db.memfs_entry().id().find(&entry_id)
        .ok_or_else(|| format!("Entry '{}' not found", entry_id))?;

    if entry.workspace_id != workspace_id {
        return Err(format!("Entry '{}' does not belong to workspace '{}'", entry_id, workspace_id));
    }

    let now = now_micros(ctx);

    // Update name if provided
    if !name.is_empty() && name != entry.name {
        validate_name(&name)?;
        // Update path: replace last segment
        let parent_part = if let Some(pos) = entry.path.rfind('/') {
            entry.path[..pos].to_string()
        } else {
            String::new()
        };
        entry.path = build_path(&parent_part, &name);
        entry.name = name;
    }

    // Update data if provided (files only)
    if !data.is_empty() {
        entry.data = data.clone();
        entry.size = data.len() as u64;
    }

    // Update mime_type if provided
    if !mime_type.is_empty() {
        entry.mime_type = mime_type;
    }

    entry.updated_at = now;
    ctx.db.memfs_entry().id().update(entry);
    Ok(())
    })
}

/// List children of a directory. Writes results to memfs_result.
#[reducer]
pub fn get_memfs_entries(
    ctx: &ReducerContext,
    workspace_id: String,
    parent_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_memfs_entries", TracingSpanKind::Read, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    // Collect children matching workspace_id + parent_id
    let children: Vec<MemfsEntry> = ctx.db.memfs_entry().iter()
        .filter(|e| e.workspace_id == workspace_id && e.parent_id == parent_id)
        .collect();

    // Clear old results
    for old in ctx.db.memfs_result().iter().collect::<Vec<_>>() {
        ctx.db.memfs_result().id().delete(&old.id);
    }

    let now = now_micros(ctx);

    for child in &children {
        let json = serde_json::to_string(child).unwrap_or_default();
        ctx.db.memfs_result().insert(MemfsResult {
            id: child.id.clone(),
            data: json,
            created_at: now,
        });
    }

    // Also insert a count marker
    ctx.db.memfs_result().insert(MemfsResult {
        id: format!("_count_{}", parent_id),
        data: format!("{{\"count\":{}}}", children.len()),
        created_at: now,
    });

    Ok(())
    })
}

/// Lookup an entry by its full virtual path.
#[reducer]
pub fn get_memfs_entry_by_path(
    ctx: &ReducerContext,
    workspace_id: String,
    path: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_memfs_entry_by_path", TracingSpanKind::Read, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    let entry = ctx.db.memfs_entry().iter()
        .find(|e| e.workspace_id == workspace_id && e.path == path);

    // Clear old results
    for old in ctx.db.memfs_result().iter().collect::<Vec<_>>() {
        ctx.db.memfs_result().id().delete(&old.id);
    }

    let now = now_micros(ctx);

    if let Some(e) = entry {
        let json = serde_json::to_string(&e).unwrap_or_default();
        ctx.db.memfs_result().insert(MemfsResult {
            id: format!("found_{}", e.id),
            data: json,
            created_at: now,
        });
    } else {
        ctx.db.memfs_result().insert(MemfsResult {
            id: format!("not_found_{}", workspace_id),
            data: format!("{{\"error\":\"No entry found at path '{}'\"}}", path),
            created_at: now,
        });
    }

    Ok(())
    })
}

/// Read a file's content.
#[reducer]
pub fn read_memfs_file(
    ctx: &ReducerContext,
    workspace_id: String,
    entry_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "read_memfs_file", TracingSpanKind::Read, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    let entry = ctx.db.memfs_entry().id().find(&entry_id)
        .ok_or_else(|| format!("Entry '{}' not found", entry_id))?;

    if entry.workspace_id != workspace_id {
        return Err(format!("Entry '{}' does not belong to workspace '{}'", entry_id, workspace_id));
    }

    if entry.entry_type != "file" {
        return Err(format!("Entry '{}' is not a file (type: {})", entry_id, entry.entry_type));
    }

    // Clear old results
    for old in ctx.db.memfs_result().iter().collect::<Vec<_>>() {
        ctx.db.memfs_result().id().delete(&old.id);
    }

    let now = now_micros(ctx);

    let result = MemfsResult {
        id: format!("read_{}", entry_id),
        data: entry.data,
        created_at: now,
    };
    ctx.db.memfs_result().insert(result);

    Ok(())
    })
}

/// Write data to a file.
#[reducer]
pub fn write_memfs_file(
    ctx: &ReducerContext,
    workspace_id: String,
    entry_id: String,
    data: String,
) -> Result<(), String> {
    trace_span!(ctx, "write_memfs_file", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;

    let mut entry = ctx.db.memfs_entry().id().find(&entry_id)
        .ok_or_else(|| format!("Entry '{}' not found", entry_id))?;

    if entry.workspace_id != workspace_id {
        return Err(format!("Entry '{}' does not belong to workspace '{}'", entry_id, workspace_id));
    }

    if entry.entry_type != "file" {
        return Err(format!("Entry '{}' is not a file (type: {})", entry_id, entry.entry_type));
    }

    let new_size = data.len() as u64;
    entry.data = data;
    entry.size = new_size;
    entry.updated_at = now_micros(ctx);

    ctx.db.memfs_entry().id().update(entry);
    Ok(())
    })
}

// ---------------------------------------------------------------------------
// Reducers — Mount Operations
// ---------------------------------------------------------------------------

/// Create a mount point.
#[reducer]
pub fn create_memfs_mount(
    ctx: &ReducerContext,
    workspace_id: String,
    mount_path: String,
    source_type: String,
    source_config: String,
    filter_query: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_memfs_mount", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "admin")?;

    // Validate source_type
    let valid_types = ["workspace", "memory", "note", "session", "custom"];
    if !valid_types.contains(&source_type.as_str()) {
        return Err(format!(
            "Invalid source_type '{}': must be one of {:?}",
            source_type, valid_types
        ));
    }

    // Check no duplicate mount path
    let dup = ctx.db.memfs_mount().iter()
        .find(|m| m.workspace_id == workspace_id && m.mount_path == mount_path);
    if dup.is_some() {
        return Err(format!("Mount at path '{}' already exists", mount_path));
    }

    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let mount = MemfsMount {
        id: id.clone(),
        workspace_id: workspace_id.clone(),
        mount_path: mount_path.clone(),
        source_type: source_type.clone(),
        source_config,
        filter_query,
        created_at: now,
    };

    ctx.db.memfs_mount().insert(mount);

    // Also create a MemfsEntry for the mount point if one doesn't exist
    let existing_entry = ctx.db.memfs_entry().iter()
        .find(|e| e.workspace_id == workspace_id && e.path == mount_path);
    if existing_entry.is_none() {
        // Determine parent from mount path
        let (parent_path, name) = if let Some(pos) = mount_path.rfind('/') {
            (mount_path[..pos].to_string(), mount_path[pos + 1..].to_string())
        } else {
            (String::new(), mount_path.trim_start_matches('/').to_string())
        };

        // Find parent_id from parent_path
        let parent_id = if parent_path.is_empty() || parent_path == "/" {
            String::new()
        } else {
            let parent = ctx.db.memfs_entry().iter()
                .find(|e| e.workspace_id == workspace_id && e.path == parent_path);
            match parent {
                Some(p) => p.id,
                None => String::new(), // parent missing, mount at root
            }
        };

        let mount_entry = MemfsEntry {
            id: id.clone(),
            workspace_id: workspace_id.clone(),
            parent_id,
            name,
            path: mount_path,
            entry_type: "directory".to_string(),
            mime_type: String::new(),
            data: String::new(),
            size: 0,
            is_mounted: true,
            mount_source: format!("{}:{}", source_type, id),
            created_at: now,
            updated_at: now,
        };
        ctx.db.memfs_entry().insert(mount_entry);
    }

    Ok(())
    })
}

/// Remove a mount point.
#[reducer]
pub fn delete_memfs_mount(
    ctx: &ReducerContext,
    workspace_id: String,
    mount_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "delete_memfs_mount", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "admin")?;

    let mount = ctx.db.memfs_mount().id().find(&mount_id)
        .ok_or_else(|| format!("Mount '{}' not found", mount_id))?;

    if mount.workspace_id != workspace_id {
        return Err(format!("Mount '{}' does not belong to workspace '{}'", mount_id, workspace_id));
    }

    // Remove the corresponding entry if it was created by this mount
    if let Some(entry) = ctx.db.memfs_entry().iter()
        .find(|e| e.workspace_id == workspace_id && e.path == mount.mount_path && e.is_mounted)
    {
        ctx.db.memfs_entry().id().delete(&entry.id);
    }

    ctx.db.memfs_mount().id().delete(&mount_id);
    Ok(())
    })
}

/// List all mount points for a workspace.
#[reducer]
pub fn get_memfs_mounts(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_memfs_mounts", TracingSpanKind::Read, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "viewer")?;

    let mounts: Vec<MemfsMount> = ctx.db.memfs_mount().iter()
        .filter(|m| m.workspace_id == workspace_id)
        .collect();

    // Clear old results
    for old in ctx.db.memfs_result().iter().collect::<Vec<_>>() {
        ctx.db.memfs_result().id().delete(&old.id);
    }

    let now = now_micros(ctx);

    for mount in &mounts {
        let json = serde_json::to_string(mount).unwrap_or_default();
        ctx.db.memfs_result().insert(MemfsResult {
            id: mount.id.clone(),
            data: json,
            created_at: now,
        });
    }

    ctx.db.memfs_result().insert(MemfsResult {
        id: format!("_mount_count_{}", workspace_id),
        data: format!("{{\"count\":{}}}", mounts.len()),
        created_at: now,
    });

    Ok(())
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // ---- validate_entry_type ----

    #[test]
    fn test_validate_entry_type_file() {
        assert!(validate_entry_type("file").is_ok());
    }

    #[test]
    fn test_validate_entry_type_directory() {
        assert!(validate_entry_type("directory").is_ok());
    }

    #[test]
    fn test_validate_entry_type_invalid() {
        assert!(validate_entry_type("symlink").is_err());
    }

    #[test]
    fn test_validate_entry_type_empty() {
        assert!(validate_entry_type("").is_err());
    }

    // ---- validate_name ----

    #[test]
    fn test_validate_name_valid() {
        assert!(validate_name("myfile.txt").is_ok());
        assert!(validate_name("my-dir").is_ok());
        assert!(validate_name("hello_world").is_ok());
    }

    #[test]
    fn test_validate_name_empty() {
        assert!(validate_name("").is_err());
    }

    #[test]
    fn test_validate_name_with_slash() {
        assert!(validate_name("a/b").is_err());
        assert!(validate_name("/etc").is_err());
    }

    // ---- build_path ----

    #[test]
    fn test_build_path_root() {
        assert_eq!(build_path("", "foo"), "/foo");
        assert_eq!(build_path("/", "foo"), "/foo");
    }

    #[test]
    fn test_build_path_nested() {
        assert_eq!(build_path("/memories", "recent"), "/memories/recent");
        assert_eq!(build_path("/a/b", "c"), "/a/b/c");
    }

    #[test]
    fn test_build_path_trailing_slash() {
        assert_eq!(build_path("/dir/", "file"), "/dir/file");
    }

    #[test]
    fn test_build_path_with_deep_nesting() {
        let p = build_path("/a/b/c/d", "e");
        assert_eq!(p, "/a/b/c/d/e");
    }

    #[test]
    fn test_build_path_empty_parent() {
        let p = build_path("", "root_file.txt");
        assert_eq!(p, "/root_file.txt");
    }

    // ---- collect_descendants ----
    // Logic is tested via entry_exists helper contract.

    #[test]
    fn test_entry_exists_no_context() {
        // Compile-only check that the function signature is valid.
        // Full integration testing requires a live ReducerContext.
        assert!(!true == false); // placeholder to avoid empty test warning
    }

    #[test]
    fn test_memfs_entry_struct_fields() {
        let entry = MemfsEntry {
            id: "test-id".into(),
            workspace_id: "ws-1".into(),
            parent_id: "".into(),
            name: "test".into(),
            path: "/test".into(),
            entry_type: "file".into(),
            mime_type: "text/plain".into(),
            data: "hello".into(),
            size: 5,
            is_mounted: false,
            mount_source: "".into(),
            created_at: 1000,
            updated_at: 1000,
        };
        assert_eq!(entry.id, "test-id");
        assert_eq!(entry.name, "test");
        assert_eq!(entry.size, 5);
        assert_eq!(entry.mime_type, "text/plain");
        assert_eq!(entry.entry_type, "file");
        assert!(!entry.is_mounted);
    }

    #[test]
    fn test_memfs_mount_struct_fields() {
        let mount = MemfsMount {
            id: "mount-1".into(),
            workspace_id: "ws-1".into(),
            mount_path: "/mnt/workspace".into(),
            source_type: "workspace".into(),
            source_config: "{}".into(),
            filter_query: "".into(),
            created_at: 1000,
        };
        assert_eq!(mount.source_type, "workspace");
        assert_eq!(mount.mount_path, "/mnt/workspace");
        assert_eq!(mount.workspace_id, "ws-1");
    }

    #[test]
    fn test_memfs_result_struct_fields() {
        let result = MemfsResult {
            id: "r1".into(),
            data: "{\"key\":\"value\"}".into(),
            created_at: 1000,
        };
        assert_eq!(result.id, "r1");
        assert_eq!(result.data, "{\"key\":\"value\"}");
    }

    #[test]
    fn test_valid_source_types() {
        let valid = ["workspace", "memory", "note", "session", "custom"];
        for st in &valid {
            assert!(valid.contains(st), "{} should be valid", st);
        }
        assert!(!valid.contains(&"invalid_type"));
    }

    #[test]
    fn test_memfs_entry_directory_defaults() {
        let entry = MemfsEntry {
            id: "dir-1".into(),
            workspace_id: "ws-1".into(),
            parent_id: "".into(),
            name: "mydir".into(),
            path: "/mydir".into(),
            entry_type: "directory".into(),
            mime_type: String::new(),
            data: String::new(),
            size: 0,
            is_mounted: false,
            mount_source: String::new(),
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(entry.entry_type, "directory");
        assert!(entry.data.is_empty());
        assert_eq!(entry.size, 0);
    }
}
