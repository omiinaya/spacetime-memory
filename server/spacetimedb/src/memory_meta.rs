use spacetimedb::*;

use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::{now_micros, uuid_v4_uniq};

// ---------------------------------------------------------------------------
// MemoryMeta — extensible metadata for memories (avoids schema migration)
// ---------------------------------------------------------------------------

/// Supplementary metadata for memories: category, immutable flag, etc.
/// Stored in a separate table so we don't need schema migrations on the
/// core Memory table.
#[table(accessor = memory_meta)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct MemoryMeta {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The memory this metadata belongs to
    #[index(btree)]
    pub memory_id: String,
    /// User-defined category label (e.g. "preferences", "facts", "history")
    #[serde(default)]
    pub category: String,
    /// If true, this memory cannot be modified or deleted
    #[serde(default)]
    pub immutable: bool,
    /// JSON blob for arbitrary future extensions
    #[serde(default)]
    pub extra_json: String,
    pub created_at: i64,
    pub updated_at: i64,
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn set_memory_meta(
    ctx: &ReducerContext,
    workspace_id: String,
    memory_id: String,
    category: String,
    immutable: bool,
    extra_json: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "set_memory_meta", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        // Upsert: find existing meta for this memory or create new
        let existing = ctx.db.memory_meta().memory_id().filter(&memory_id).next();
        let (meta_id, created) = if let Some(meta) = existing {
            (meta.id.clone(), false)
        } else {
            (uuid_v4_uniq(ctx, |id| ctx.db.memory_meta().id().find(id).is_none(), 3), true)
        };

        let meta = MemoryMeta {
            id: meta_id.clone(),
            workspace_id: workspace_id.clone(),
            memory_id,
            category,
            immutable,
            extra_json,
            created_at: if created { now } else {
                ctx.db.memory_meta().id().find(&meta_id).map(|m| m.created_at).unwrap_or(now)
            },
            updated_at: now,
        };

        let meta_json = change_event::record_to_json(&meta);
        if created {
            ctx.db.memory_meta().insert(meta);
            change_event::log_change(ctx, &ws_id, "memory_meta", "insert", &meta_id, &meta_json);
        } else {
            ctx.db.memory_meta().id().update(meta);
            change_event::log_change(ctx, &ws_id, "memory_meta", "update", &meta_id, &meta_json);
        }
        Ok(())
    })
}

#[reducer]
pub fn get_memory_meta(ctx: &ReducerContext, memory_id: String) -> Result<(), String> {
    trace_span!(ctx, "get_memory_meta", TracingSpanKind::Read, "", {
        let _account = require_auth(ctx)?;
        if let Some(meta) = ctx.db.memory_meta().memory_id().filter(&memory_id).next() {
            let caller = ctx.sender().to_hex();
            check_space_access(ctx, &meta.workspace_id, &caller, "viewer")?;
        }
        Ok(())
    })
}

#[reducer]
pub fn batch_set_memory_meta(
    ctx: &ReducerContext,
    workspace_id: String,
    ids_json: String,
    category: String,
    immutable: bool,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "batch_set_memory_meta", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        let ids: Vec<String> = serde_json::from_str(&ids_json)
            .map_err(|e| format!("Invalid ids_json: {}", e))?;

        for memory_id in ids {
            let existing = ctx.db.memory_meta().memory_id().filter(&memory_id).next();
            if let Some(mut meta) = existing {
                if !category.is_empty() {
                    meta.category = category.clone();
                }
                meta.immutable = immutable;
                meta.updated_at = now;
                ctx.db.memory_meta().id().update(meta);
            } else {
                let meta_id = uuid_v4_uniq(
                    ctx,
                    |id| ctx.db.memory_meta().id().find(id).is_none(),
                    3,
                );
                let meta = MemoryMeta {
                    id: meta_id,
                    workspace_id: workspace_id.clone(),
                    memory_id,
                    category: category.clone(),
                    immutable,
                    extra_json: String::new(),
                    created_at: now,
                    updated_at: now,
                };
                ctx.db.memory_meta().insert(meta);
            }
        }
        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_memory_meta_initialization() {
        let meta = MemoryMeta {
            id: "mm_001".to_string(),
            workspace_id: "ws_001".to_string(),
            memory_id: "mem_001".to_string(),
            category: "preferences".to_string(),
            immutable: true,
            extra_json: r#"{"source":"user"}"#.to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(meta.category, "preferences");
        assert!(meta.immutable);
        assert_eq!(meta.memory_id, "mem_001");
    }

    #[test]
    fn test_memory_meta_default_immutable() {
        let meta = MemoryMeta {
            id: "mm_002".to_string(),
            workspace_id: "ws".to_string(),
            memory_id: "mem_002".to_string(),
            category: String::new(),
            extra_json: String::new(),
            immutable: false,
            created_at: 0,
            updated_at: 0,
        };
        assert!(!meta.immutable);
        assert!(meta.category.is_empty());
    }

    #[test]
    fn test_memory_meta_serde_roundtrip() {
        let meta = MemoryMeta {
            id: "mm_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            memory_id: "mem_serde".to_string(),
            category: "facts".to_string(),
            immutable: false,
            extra_json: "{}".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        let json = serde_json::to_string(&meta).expect("serialize");
        let deserialized: MemoryMeta = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.category, "facts");
        assert!(!deserialized.immutable);
    }

    #[test]
    fn test_memory_meta_category_variants() {
        for cat in &["", "preferences", "facts", "history", "work", "personal"] {
            let meta = MemoryMeta {
                id: format!("mm_cat_{}", cat),
                workspace_id: "ws".to_string(),
                memory_id: "mem".to_string(),
                category: cat.to_string(),
                immutable: false,
                extra_json: String::new(),
                created_at: 0,
                updated_at: 0,
            };
            assert_eq!(meta.category, *cat);
        }
    }
}
