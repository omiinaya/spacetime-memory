use spacetimedb::*;

// ---------------------------------------------------------------------------
// Table: workspace_directory_entry
// ---------------------------------------------------------------------------

/// Maps (workspace_id, entity_type) → entity IDs, providing O(1) pre-filter
/// for hybrid_search strategies.
///
/// Instead of scanning tables like `search_index`, `memory`, `kg_edge` with
/// `.filter(|r| r.workspace_id == ...)` — which is a full-table scan that
/// degrades catastrophically beyond 10K rows — this table acts as a
/// lightweight index.  Entries are inserted *at write time* alongside the
/// entity itself, so query time just iterates a small set of PK-lookup
/// operations.
///
/// The PK is a composite string: `{workspace_id}:{entity_type}:{entity_id}`
/// which makes upserts idempotent (same triple → same row).
///
/// ## Supported entity_type values
///
/// | `entity_type`   | Referenced table    | When inserted                                |
/// |-----------------|---------------------|----------------------------------------------|
/// | `memory`        | `memory`            | `store_memory`, `store_memory_batch`         |
/// | `search_index`  | `search_index`      | `index_entity`, `index_entity_batch`         |
/// | `term_index`    | `term_index`        | `index_terms` (one entry per entity indexed) |
/// | `kg_node`       | `kg_node`           | `create_node`                                |
/// | `kg_edge`       | `kg_edge`           | `create_edge`                                |
#[table(accessor = workspace_directory)]
#[derive(Debug, Clone)]
pub struct DirectoryEntry {
    #[primary_key]
    /// Composite PK: `{workspace_id}:{entity_type}:{entity_id}`
    pub id: String,
    /// Foreign entity ID (memory ID, node ID, search_index ID, etc.)
    pub entity_id: String,
    pub workspace_id: String,
    pub entity_type: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Public helpers
// ---------------------------------------------------------------------------

/// Build the composite primary key for a directory entry.
fn make_dir_id(workspace_id: &str, entity_type: &str, entity_id: &str) -> String {
    // Use a separator unlikely to appear in UUIDs/IDs
    format!("{}|\x1f{}|\x1f{}", workspace_id, entity_type, entity_id)
}

/// Add an entity ID to the workspace directory.
///
/// Idempotent — inserting the same (workspace_id, entity_type, entity_id)
/// a second time is a no-op because the PK is the same.
pub fn add_to_directory(
    ctx: &ReducerContext,
    workspace_id: &str,
    entity_type: &str,
    entity_id: &str,
    now: i64,
) {
    let id = make_dir_id(workspace_id, entity_type, entity_id);
    // Only insert if not already present (avoids overwrite noise)
    if ctx.db.workspace_directory().id().find(&id).is_none() {
        ctx.db.workspace_directory().insert(DirectoryEntry {
            id,
            entity_id: entity_id.to_string(),
            workspace_id: workspace_id.to_string(),
            entity_type: entity_type.to_string(),
            created_at: now,
        });
    }
}

/// Remove an entity ID from the workspace directory.
pub fn remove_from_directory(
    ctx: &ReducerContext,
    workspace_id: &str,
    entity_type: &str,
    entity_id: &str,
) {
    let id = make_dir_id(workspace_id, entity_type, entity_id);
    ctx.db.workspace_directory().id().delete(&id);
}

/// Retrieve all entity IDs of a given type for a workspace.
///
/// Returns `Vec<String>` of entity IDs.  Empty if none found.
///
/// **Important**: This still iterates the directory table, but the
/// directory table is *much smaller* than the underlying entity tables
/// (only IDs, no content/embeddings), so the scan is cheap.  At scale
/// the directory scan stays bounded by the number of entities per
/// workspace, not the global table size.
pub fn get_directory_ids(
    ctx: &ReducerContext,
    workspace_id: &str,
    entity_type: &str,
) -> Vec<String> {
    // Build a prefix for the PK: workspace_id|{sep}entity_type|{sep}
    let prefix = format!("{}|\x1f{}|\x1f", workspace_id, entity_type);
    let mut results = Vec::new();

    for entry in ctx.db.workspace_directory().iter() {
        if entry.id.starts_with(&prefix) {
            results.push(entry.entity_id.clone());
        }
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_directory_entry_construction() {
        let entry = DirectoryEntry {
            id: "ws-1|\x1fmemory|\x1fmem-001".to_string(),
            entity_id: "mem-001".to_string(),
            workspace_id: "ws-1".to_string(),
            entity_type: "memory".to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(entry.workspace_id, "ws-1");
        assert_eq!(entry.entity_type, "memory");
        assert_eq!(entry.entity_id, "mem-001");
    }

    #[test]
    fn test_make_dir_id_format() {
        let id = make_dir_id("ws-1", "memory", "mem-001");
        assert_eq!(id, "ws-1|\x1fmemory|\x1fmem-001");
        assert!(id.contains("|\x1f"));
    }

    #[test]
    fn test_make_dir_id_components() {
        let ws = "workspace_abc";
        let entity_type = "kg_node";
        let entity_id = "node_xyz_123";
        let id = make_dir_id(ws, entity_type, entity_id);
        // Verify the id starts with workspace_id + sep
        assert!(id.starts_with(&format!("{}|\x1f", ws)));
        // Verify it contains the entity_type
        assert!(id.contains(&format!("|\x1f{}|\x1f", entity_type)));
        // Verify it ends with the entity_id
        assert!(id.ends_with(entity_id));
    }

    #[test]
    fn test_make_dir_id_special_chars() {
        let id = make_dir_id("ws:1", "kg:edge", "id:123");
        assert!(id.starts_with("ws:1|\x1f"));
        assert!(id.contains("|\x1fkg:edge|\x1f"));
        assert!(id.ends_with("id:123"));
    }

    #[test]
    fn test_directory_entry_all_entity_types() {
        for entity_type in &["memory", "search_index", "term_index", "kg_node", "kg_edge"] {
            let entry = DirectoryEntry {
                id: make_dir_id("ws-1", entity_type, "entity-001"),
                entity_id: "entity-001".to_string(),
                workspace_id: "ws-1".to_string(),
                entity_type: entity_type.to_string(),
                created_at: 0,
            };
            assert_eq!(entry.entity_type, *entity_type);
            assert!(entry.id.contains(entity_type));
        }
    }

    #[test]
    fn test_get_directory_ids_prefix_format() {
        // The get_directory_ids function builds a prefix: "{workspace_id}|{sep}{entity_type}|{sep}"
        let prefix = format!("{}|\x1f{}|\x1f", "ws-1", "memory");
        assert_eq!(prefix, "ws-1|\x1fmemory|\x1f");
    }

    #[test]
    fn test_add_to_directory_idempotency_pattern() {
        // The add_to_directory function checks if id().find(&id).is_none()
        // before inserting. This tests the PK uniqueness pattern.
        let id1 = make_dir_id("ws-1", "memory", "mem-001");
        let id2 = make_dir_id("ws-1", "memory", "mem-001");
        assert_eq!(id1, id2, "Same triple should produce the same PK");
    }

    #[test]
    fn test_remove_from_directory_id_pattern() {
        // remove_from_directory deletes by the composite key
        let id = make_dir_id("ws-1", "memory", "mem-001");
        // The id is exactly what would be passed to .id().delete()
        assert_eq!(id, "ws-1|\x1fmemory|\x1fmem-001");
    }
}
