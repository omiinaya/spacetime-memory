use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};
use crate::trace_span;
use crate::tracing::TracingSpanKind;

/// A tag that can be attached to memories and other entities.
#[table(accessor = tag)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Tag {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub name: String,
    pub color: String,
    pub created_at: i64,
}

/// Associates a tag with a memory.
/// Both fields together act as the logical composite key.
#[table(accessor = memory_tag)]
#[derive(Debug, Clone)]
pub struct MemoryTag {
    #[index(btree)]
    pub workspace_id: String,
    #[index(btree)]
    pub memory_id: String,
    #[index(btree)]
    pub tag_id: String,
}

// ---------------------------------------------------------------------------
// Tag reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_tag(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    color: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_tag", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);
        let id = uuid_v7(ctx);

        let tag = Tag {
            id: id.clone(),
            workspace_id: workspace_id.clone(),
            name,
            color,
            created_at: now,
        };

        ctx.db.tag().insert(tag);
        Ok(())
    })
}

#[reducer]
pub fn tag_memory(
    ctx: &ReducerContext,
    workspace_id: String,
    memory_id: String,
    tag_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "tag_memory", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let mt = MemoryTag {
            workspace_id: workspace_id.clone(),
            memory_id,
            tag_id,
        };

        ctx.db.memory_tag().insert(mt);
        Ok(())
    })
}

#[reducer]
pub fn untag_memory(
    ctx: &ReducerContext,
    memory_id: String,
    tag_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "untag_memory", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        // Delete matching rows (table has no PK, so iterate and delete each row)
        let to_delete: Vec<_> = ctx
            .db
            .memory_tag()
            .memory_id().filter(&memory_id)
            .take(crate::MAX_RESULTS)
            .filter(|mt| mt.tag_id == tag_id)
            .collect();
        if to_delete.is_empty() {
            return Err(format!(
                "Tag association not found for memory '{}' with tag '{}'",
                memory_id, tag_id
            ));
        }
        for mt in to_delete {
            ctx.db.memory_tag().delete(mt);
        }

        Ok(())
    })
}

#[reducer]
pub fn list_tags(
    ctx: &ReducerContext,
    _workspace_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "list_tags", TracingSpanKind::Read, &_workspace_id, {
        let _account = require_auth(ctx)?;
        // Note: list_tags was previously a value-returning reducer. STDB v2.6
        // doesn't support reducer return values. The SDK now queries the `tag`
        // table directly via `_query(\"tag\", workspace_id=ws, columns=[...])`.
        // This reducer still exists for auth-gated identity verification.
        Ok(())
    })
}

/// Batch-attach a tag to multiple memories in a single reducer call.
/// Accepts a workspace_id, tag_id, and a JSON array of memory ID strings.
/// Idempotent per-memory (skips already-tagged memories — no-op).
#[reducer]
pub fn batch_tag_memories(ctx: &ReducerContext, workspace_id: String, tag_id: String, memory_ids_json: String) -> Result<(), String> {
    trace_span!(ctx, "batch_tag_memories", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let memory_ids: Vec<String> = serde_json::from_str(&memory_ids_json)
            .map_err(|e| format!("Invalid batch-tag memory IDs JSON: {}", e))?;

        // Build a set of existing taggings to avoid duplicates
        let existing: std::collections::HashSet<(String, String)> = ctx
            .db
            .memory_tag()
            .tag_id().filter(&tag_id)
            .take(crate::MAX_RESULTS)
            .map(|mt| (mt.memory_id.clone(), mt.tag_id.clone()))
            .collect();

        for mid in &memory_ids {
            if existing.contains(&(mid.clone(), tag_id.clone())) {
                continue; // Idempotent — skip already-tagged
            }
            let mt = MemoryTag {
                workspace_id: workspace_id.clone(),
                memory_id: mid.clone(),
                tag_id: tag_id.clone(),
            };
            ctx.db.memory_tag().insert(mt);
        }

        Ok(())
    })
}

/// Batch-remove a tag from multiple memories in a single reducer call.
/// Accepts a tag_id and a JSON array of memory ID strings.
/// Idempotent per-memory (skips missing associations).
#[reducer]
pub fn batch_untag_memories(ctx: &ReducerContext, tag_id: String, memory_ids_json: String) -> Result<(), String> {
    trace_span!(ctx, "batch_untag_memories", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let memory_ids: Vec<String> = serde_json::from_str(&memory_ids_json)
            .map_err(|e| format!("Invalid batch-untag memory IDs JSON: {}", e))?;

        // Collect rows to delete
        let to_delete: Vec<_> = ctx
            .db
            .memory_tag()
            .tag_id().filter(&tag_id)
            .take(crate::MAX_RESULTS)
            .filter(|mt| memory_ids.contains(&mt.memory_id))
            .collect();

        for mt in to_delete {
            ctx.db.memory_tag().delete(mt);
        }

        Ok(())
    })
}

// ── Result table for list_tags_by_memory ────────────────────────────────────

/// Stores tags for a specific memory query.
#[table(accessor = memory_tag_result)]
#[derive(Debug, Clone, serde::Serialize)]
pub struct MemoryTagResult {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub memory_id: String,
    pub tag_id: String,
    pub tag_name: String,
    pub tag_color: String,
}

/// List all tags attached to a specific memory.
/// Writes results to ``memory_tag_result`` table, keyed by memory_id.
#[reducer]
pub fn list_tags_by_memory(
    ctx: &ReducerContext,
    memory_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "list_tags_by_memory", TracingSpanKind::Read, "", {
        let _account = require_auth(ctx)?;

        // Clear previous results for this memory
        let old: Vec<_> = ctx
            .db
            .memory_tag_result()
            .memory_id().filter(&memory_id)
            .take(crate::MAX_RESULTS)
            .collect();
        for r in old {
            ctx.db.memory_tag_result().id().delete(r.id);
        }

        // Find all MemoryTag rows for this memory
        let tag_ids: Vec<String> = ctx
            .db
            .memory_tag()
            .memory_id().filter(&memory_id)
            .take(crate::MAX_RESULTS)
            .map(|mt| mt.tag_id.clone())
            .collect();

        // Resolve tag details and insert results
        for tid in &tag_ids {
            if let Some(tag) = ctx.db.tag().id().find(tid) {
                ctx.db.memory_tag_result().insert(MemoryTagResult {
                    id: crate::uuid_v7(ctx),
                    memory_id: memory_id.clone(),
                    tag_id: tid.clone(),
                    tag_name: tag.name,
                    tag_color: tag.color,
                });
            }
        }

        Ok(())
    })
}

// ── Update tag ──────────────────────────────────────────────────────────────

/// Update a tag's name and/or color.
#[reducer]
pub fn update_tag(
    ctx: &ReducerContext,
    tag_id: String,
    name: String,
    color: String,
) -> Result<(), String> {
    trace_span!(ctx, "update_tag", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let tag = ctx.db.tag().id().find(&tag_id)
            .ok_or_else(|| format!("Tag not found: {}", tag_id))?;

        let updated = Tag {
            name: if name.is_empty() { tag.name } else { name },
            color,
            ..tag
        };
        ctx.db.tag().id().update(updated);
        Ok(())
    })
}

#[reducer]
pub fn delete_tag(
    ctx: &ReducerContext,
    tag_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "delete_tag", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        // Find the tag and delete it
        let tag = ctx.db.tag().id().find(&tag_id);
        match tag {
            Some(t) => {
                ctx.db.tag().delete(t);
                // Also delete all associations
                let to_delete: Vec<_> = ctx
                    .db
                    .memory_tag()
                    .tag_id().filter(&tag_id)
                    .take(crate::MAX_RESULTS)
                    .collect();
                for mt in to_delete {
                    ctx.db.memory_tag().delete(mt);
                }
                Ok(())
            }
            None => Err(format!("Tag not found: {}", tag_id)),
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── Existing tests (kept) ──
    

    #[test]
    fn test_tag_serialize() {
        let tag = Tag {
            id: "t1".to_string(),
            workspace_id: "ws-1".to_string(),
            name: "important".to_string(),
            color: "#ff0000".to_string(),
            created_at: 1_700_000_000_000,
        };
        let json = serde_json::to_string(&tag).unwrap();
        assert!(json.contains("\"t1\""));
        assert!(json.contains("\"important\""));
        assert!(json.contains("\"#ff0000\""));
        assert!(json.contains("\"ws-1\""));
    }

    #[test]
    fn test_tag_deserialize() {
        let json = r##"{
            "id": "t1",
            "workspace_id": "ws-1",
            "name": "important",
            "color": "#ff0000",
            "created_at": 1700000000000
        }"##;
        let tag: Tag = serde_json::from_str(json).unwrap();
        assert_eq!(tag.id, "t1");
        assert_eq!(tag.workspace_id, "ws-1");
        assert_eq!(tag.name, "important");
        assert_eq!(tag.color, "#ff0000");
        assert_eq!(tag.created_at, 1_700_000_000_000);
    }

    #[test]
    fn test_tag_all_fields_deserialize() {
        let json = r##"{
            "id": "all-fields-id",
            "workspace_id": "all-fields-ws",
            "name": "all-fields-tag",
            "color": "#00ff00",
            "created_at": 1800000000000
        }"##;
        let tag: Tag = serde_json::from_str(json).unwrap();
        assert_eq!(tag.id, "all-fields-id");
        assert_eq!(tag.workspace_id, "all-fields-ws");
        assert_eq!(tag.name, "all-fields-tag");
        assert_eq!(tag.color, "#00ff00");
        assert_eq!(tag.created_at, 1_800_000_000_000);
    }

    #[test]
    fn test_memory_tag_creation() {
        let mt = MemoryTag {
            memory_id: "mem-1".to_string(),
            tag_id: "tag-1".to_string(),
            workspace_id: "ws-1".to_string(),
        };
        assert_eq!(mt.memory_id, "mem-1");
        assert_eq!(mt.tag_id, "tag-1");
    }

    #[test]
    fn test_memory_tag_result_serialize() {
        let mtr = MemoryTagResult {
            id: "r1".to_string(),
            memory_id: "mem-1".to_string(),
            tag_id: "tag-1".to_string(),
            tag_name: "important".to_string(),
            tag_color: "#ff0000".to_string(),
        };
        let json = serde_json::to_string(&mtr).unwrap();
        assert!(json.contains("\"r1\""));
        assert!(json.contains("\"mem-1\""));
        assert!(json.contains("\"important\""));
    }

    // ── Edge case tests ────────────────────────────────────────────

    #[test]
    fn test_tag_empty_name() {
        let tag = Tag {
            id: "t_empty".to_string(),
            workspace_id: "ws".to_string(),
            name: String::new(),
            color: "#000000".to_string(),
            created_at: 0,
        };
        assert!(tag.name.is_empty());
        assert_eq!(tag.color, "#000000");
    }
    
    #[test]
    fn test_tag_special_characters_in_name() {
        let name = "tag!@#$%^&*()_+-=[]{}|;':,./<>? 😈".to_string();
        let tag = Tag {
            id: "t_special".to_string(),
            workspace_id: "ws".to_string(),
            name: name.clone(),
            color: "#ff00ff".to_string(),
            created_at: 1000,
        };
        assert_eq!(tag.name, name);
        assert!(tag.name.contains('😈'));
    }
    
    #[test]
    fn test_tag_unicode_name() {
        let name = "タグ测试标签🌟".to_string();
        let tag = Tag {
            id: "t_unicode".to_string(),
            workspace_id: "ws".to_string(),
            name: name.clone(),
            color: "#00ffff".to_string(),
            created_at: 2000,
        };
        assert_eq!(tag.name, name);
        assert!(tag.name.contains('🌟'));
    }
    
    #[test]
    fn test_tag_very_long_name() {
        let long_name = "x".repeat(1000);
        let tag = Tag {
            id: "t_long".to_string(),
            workspace_id: "ws".to_string(),
            name: long_name.clone(),
            color: "#ffffff".to_string(),
            created_at: 3000,
        };
        assert_eq!(tag.name.len(), 1000);
        assert!(tag.name.chars().all(|c| c == 'x'));
    }
    
    #[test]
    fn test_tag_concurrent_creation_simulation() {
        let tags: Vec<Tag> = (0..10)
            .map(|i| Tag {
                id: format!("t_concurrent_{}", i),
                workspace_id: "ws_concurrent".to_string(),
                name: format!("Concurrent Tag {}", i),
                color: format!("#{:06x}", i * 0x111111 % 0x1000000),
                created_at: i as i64,
            })
            .collect();
        assert_eq!(tags.len(), 10);
        for (i, tag) in tags.iter().enumerate() {
            assert_eq!(tag.id, format!("t_concurrent_{}", i));
        }
    }
    
    #[test]
    fn test_tag_network_partition_simulation() {
        // Simulate partial data received during network partition
        let tag = Tag {
            id: "t_partition".to_string(),
            workspace_id: String::new(),  // missing workspace ID
            name: "orphan-tag".to_string(),
            color: String::new(),  // missing color
            created_at: 0,
        };
        assert!(tag.workspace_id.is_empty());
        assert!(tag.color.is_empty());
        assert_eq!(tag.name, "orphan-tag");
    }
}
