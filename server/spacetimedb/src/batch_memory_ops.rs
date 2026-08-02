use spacetimedb::*;

use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::{now_micros, uuid_v4_uniq};
use crate::memory::maintenance_slice;
use crate::memory::memory;
use crate::memory_meta::MemoryMeta;
use crate::memory_meta::memory_meta;

/// Maximum memories to batch-operate in a single reducer call
pub const MAX_BATCH_SIZE: usize = 100;

// ---------------------------------------------------------------------------
// Batch update
// ---------------------------------------------------------------------------

#[reducer]
pub fn batch_update_memories(
    ctx: &ReducerContext,
    workspace_id: String,
    ids_json: String,
    updates_json: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "batch_update_memories", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        // Parse IDs
        let ids: Vec<String> = serde_json::from_str(&ids_json)
            .map_err(|e| format!("Invalid ids_json: {}", e))?;

        if ids.len() > MAX_BATCH_SIZE {
            return Err(format!("Batch size {} exceeds maximum {}", ids.len(), MAX_BATCH_SIZE));
        }

        if ids.is_empty() {
            return Err("Empty batch: no IDs provided".to_string());
        }

        // Parse updates as a flat JSON map of field → value
        let updates: std::collections::HashMap<String, serde_json::Value> =
            serde_json::from_str(&updates_json)
                .map_err(|e| format!("Invalid updates_json: {}", e))?;

        if updates.is_empty() {
            return Err("Empty updates: no fields to update".to_string());
        }

        // Extract MemoryMeta updates if present
        let new_category: Option<String> = updates
            .get("category")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let new_immutable: Option<bool> = updates.get("immutable").and_then(|v| v.as_bool());

        let mut updated_count = 0u32;
        for id in &ids {
            if let Some(mut mem) = ctx.db.memory().id().find(id) {
                // Ensure memory belongs to this workspace
                if mem.workspace_id != ws_id {
                    continue;
                }

                // Apply Memory field updates
                if let Some(val) = updates.get("content") {
                    if let Some(s) = val.as_str() {
                        mem.content = s.to_string();
                    }
                }
                if let Some(val) = updates.get("summary") {
                    if let Some(s) = val.as_str() {
                        mem.summary = s.to_string();
                    }
                }
                if let Some(val) = updates.get("confidence") {
                    if let Some(n) = val.as_f64() {
                        mem.confidence = n;
                    }
                }
                if let Some(val) = updates.get("expires_at") {
                    if let Some(n) = val.as_i64() {
                        mem.expires_at = n;
                    }
                }
                if let Some(val) = updates.get("tier") {
                    if let Some(s) = val.as_str() {
                        mem.tier = s.to_string();
                    }
                }
                if let Some(val) = updates.get("is_active") {
                    if let Some(b) = val.as_bool() {
                        mem.is_active = b;
                    }
                }
                if let Some(val) = updates.get("strength") {
                    if let Some(n) = val.as_f64() {
                        mem.strength = n;
                    }
                }
                if let Some(val) = updates.get("trust_score") {
                    if let Some(n) = val.as_f64() {
                        mem.trust_score = n;
                    }
                }
                if let Some(val) = updates.get("user_scope") {
                    if let Some(s) = val.as_str() {
                        mem.user_scope = s.to_string();
                    }
                }
                if let Some(val) = updates.get("memory_type") {
                    if let Some(s) = val.as_str() {
                        mem.memory_type = s.to_string();
                    }
                }

                mem.version += 1;
                mem.updated_at = now;

                let mem_json = change_event::record_to_json(&mem);
                ctx.db.memory().id().update(mem);
                change_event::log_change(ctx, &ws_id, "memory", "update", id, &mem_json);

                // Update MemoryMeta if category or immutable were provided
                if new_category.is_some() || new_immutable.is_some() {
                    upsert_memory_meta(ctx, &ws_id, id, new_category.as_deref(), new_immutable, now);
                }

                updated_count += 1;
            }
        }

        // Amortized maintenance
        maintenance_slice(ctx, &ws_id, now);

        let _ = updated_count;
        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Batch delete
// ---------------------------------------------------------------------------

#[reducer]
pub fn batch_delete_memories(
    ctx: &ReducerContext,
    workspace_id: String,
    ids_json: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "batch_delete_memories", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;

        // Parse IDs
        let ids: Vec<String> = serde_json::from_str(&ids_json)
            .map_err(|e| format!("Invalid ids_json: {}", e))?;

        if ids.len() > MAX_BATCH_SIZE {
            return Err(format!("Batch size {} exceeds maximum {}", ids.len(), MAX_BATCH_SIZE));
        }

        if ids.is_empty() {
            return Err("Empty batch: no IDs provided".to_string());
        }

        let mut deleted_count = 0u32;
        let mut not_found_count = 0u32;
        for id in &ids {
            if let Some(mem) = ctx.db.memory().id().find(id) {
                if mem.workspace_id != ws_id {
                    // Not in our workspace — count as not found for caller's perspective
                    not_found_count += 1;
                    continue;
                }
                let mem_json = change_event::record_to_json(&mem);
                ctx.db.memory().id().delete(id);
                change_event::log_change(ctx, &ws_id, "memory", "delete", id, &mem_json);

                // Also clean up associated MemoryMeta
                if let Some(meta) = ctx.db.memory_meta().memory_id().filter(id).next() {
                    ctx.db.memory_meta().id().delete(&meta.id);
                }

                deleted_count += 1;
            } else {
                not_found_count += 1;
            }
        }

        // Amortized maintenance
        let now = now_micros(ctx);
        maintenance_slice(ctx, &ws_id, now);

        let _ = deleted_count;
        let _ = not_found_count;
        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Batch set category (convenience — operates on MemoryMeta)
// ---------------------------------------------------------------------------

#[reducer]
pub fn batch_set_category(
    ctx: &ReducerContext,
    workspace_id: String,
    ids_json: String,
    category: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "batch_set_category", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        let ids: Vec<String> = serde_json::from_str(&ids_json)
            .map_err(|e| format!("Invalid ids_json: {}", e))?;

        if ids.len() > MAX_BATCH_SIZE {
            return Err(format!("Batch size {} exceeds maximum {}", ids.len(), MAX_BATCH_SIZE));
        }

        if ids.is_empty() {
            return Err("Empty batch: no IDs provided".to_string());
        }

        let mut updated_count = 0u32;
        for memory_id in &ids {
            // Verify the memory exists and belongs to this workspace
            if let Some(mem) = ctx.db.memory().id().find(memory_id) {
                if mem.workspace_id != ws_id {
                    continue;
                }
            } else {
                continue;
            }

            upsert_memory_meta(ctx, &ws_id, memory_id, Some(&category), None, now);
            updated_count += 1;
        }

        // Amortized maintenance
        maintenance_slice(ctx, &ws_id, now);

        let _ = updated_count;
        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/// Upsert a MemoryMeta row for the given memory_id, setting category and/or
/// immutable as provided.
fn upsert_memory_meta(
    ctx: &ReducerContext,
    workspace_id: &str,
    memory_id: &str,
    category: Option<&str>,
    immutable: Option<bool>,
    now: i64,
) {
    let existing = ctx.db.memory_meta().memory_id().filter(memory_id).next();
    let (meta_id, created) = if let Some(meta) = existing {
        (meta.id.clone(), false)
    } else {
        let id = uuid_v4_uniq(ctx, |id| ctx.db.memory_meta().id().find(id).is_none(), 3);
        (id, true)
    };

    let old_meta = ctx.db.memory_meta().id().find(&meta_id);
    let new_meta = MemoryMeta {
        id: meta_id.clone(),
        workspace_id: workspace_id.to_string(),
        memory_id: memory_id.to_string(),
        category: category.unwrap_or_else(|| {
            old_meta.as_ref().map(|m| m.category.as_str()).unwrap_or("")
        }).to_string(),
        immutable: immutable.unwrap_or_else(|| {
            old_meta.as_ref().map(|m| m.immutable).unwrap_or(false)
        }),
        extra_json: old_meta.as_ref().map(|m| m.extra_json.clone()).unwrap_or_default(),
        created_at: if created { now } else {
            old_meta.as_ref().map(|m| m.created_at).unwrap_or(now)
        },
        updated_at: now,
    };

    let meta_json = change_event::record_to_json(&new_meta);
    if created {
        ctx.db.memory_meta().insert(new_meta);
        change_event::log_change(ctx, workspace_id, "memory_meta", "insert", &meta_id, &meta_json);
    } else {
        ctx.db.memory_meta().id().update(new_meta);
        change_event::log_change(ctx, workspace_id, "memory_meta", "update", &meta_id, &meta_json);
    }
}

// ── Test helpers (validation logic extracted for testing) ──────────────
// These replicate the validation in batch reducers so we can test paths
// that require `ReducerContext` in production. They are only used in tests.

#[allow(dead_code)]
/// Validate IDs array length and non-emptiness — mirrors logic in
/// `batch_update_memories`, `batch_delete_memories`, `batch_set_category`.
fn validate_ids(ids: &[String]) -> Result<(), String> {
    if ids.len() > MAX_BATCH_SIZE {
        return Err(format!("Batch size {} exceeds maximum {}", ids.len(), MAX_BATCH_SIZE));
    }
    if ids.is_empty() {
        return Err("Empty batch: no IDs provided".to_string());
    }
    Ok(())
}

#[allow(dead_code)]
/// Validate updates map non-emptiness — mirrors logic in `batch_update_memories`.
fn validate_updates(updates: &std::collections::HashMap<String, serde_json::Value>) -> Result<(), String> {
    if updates.is_empty() {
        return Err("Empty updates: no fields to update".to_string());
    }
    Ok(())
}

#[allow(dead_code)]
/// Extract a field from the updates map — mirrors the per-field extraction
/// logic in `batch_update_memories`.
fn extract_field_str(updates: &std::collections::HashMap<String, serde_json::Value>, key: &str) -> Option<String> {
    updates.get(key).and_then(|v| v.as_str()).map(|s| s.to_string())
}

#[allow(dead_code)]
fn extract_field_f64(updates: &std::collections::HashMap<String, serde_json::Value>, key: &str) -> Option<f64> {
    updates.get(key).and_then(|v| v.as_f64())
}

#[allow(dead_code)]
fn extract_field_i64(updates: &std::collections::HashMap<String, serde_json::Value>, key: &str) -> Option<i64> {
    updates.get(key).and_then(|v| v.as_i64())
}

#[allow(dead_code)]
fn extract_field_bool(updates: &std::collections::HashMap<String, serde_json::Value>, key: &str) -> Option<bool> {
    updates.get(key).and_then(|v| v.as_bool())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    // ── Constant tests ─────────────────────────────────────────────────

    #[test]
    fn test_max_batch_size_value() {
        assert_eq!(MAX_BATCH_SIZE, 100);
    }

    // ── Validation helper tests ────────────────────────────────────────

    #[test]
    fn test_validate_ids_empty() {
        let ids: Vec<String> = vec![];
        let result = validate_ids(&ids);
        assert!(result.is_err());
        assert_eq!(result.unwrap_err(), "Empty batch: no IDs provided");
    }

    #[test]
    fn test_validate_ids_exceeds_max() {
        let ids: Vec<String> = (0..=MAX_BATCH_SIZE).map(|i| format!("id-{}", i)).collect();
        let result = validate_ids(&ids);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("exceeds maximum"));
    }

    #[test]
    fn test_validate_ids_exactly_max() {
        let ids: Vec<String> = (0..MAX_BATCH_SIZE).map(|i| format!("id-{}", i)).collect();
        let result = validate_ids(&ids);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_ids_single() {
        let ids = vec!["single-id".to_string()];
        let result = validate_ids(&ids);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_updates_empty() {
        let updates: HashMap<String, serde_json::Value> = HashMap::new();
        let result = validate_updates(&updates);
        assert!(result.is_err());
        assert_eq!(result.unwrap_err(), "Empty updates: no fields to update");
    }

    #[test]
    fn test_validate_updates_non_empty() {
        let mut updates = HashMap::new();
        updates.insert("content".to_string(), serde_json::Value::String("hello".to_string()));
        let result = validate_updates(&updates);
        assert!(result.is_ok());
    }

    // ── Field extraction tests ─────────────────────────────────────────

    #[test]
    fn test_extract_field_content() {
        let mut updates = HashMap::new();
        updates.insert("content".to_string(), serde_json::json!("new content"));
        assert_eq!(extract_field_str(&updates, "content"), Some("new content".to_string()));
    }

    #[test]
    fn test_extract_field_summary() {
        let mut updates = HashMap::new();
        updates.insert("summary".to_string(), serde_json::json!("a summary"));
        assert_eq!(extract_field_str(&updates, "summary"), Some("a summary".to_string()));
    }

    #[test]
    fn test_extract_field_confidence() {
        let mut updates = HashMap::new();
        updates.insert("confidence".to_string(), serde_json::json!(0.95));
        let val = extract_field_f64(&updates, "confidence");
        assert!(val.is_some());
        assert!((val.unwrap() - 0.95).abs() < 1e-10);
    }

    #[test]
    fn test_extract_field_expires_at() {
        let mut updates = HashMap::new();
        updates.insert("expires_at".to_string(), serde_json::json!(1700000000));
        assert_eq!(extract_field_i64(&updates, "expires_at"), Some(1700000000));
    }

    #[test]
    fn test_extract_field_tier() {
        let mut updates = HashMap::new();
        updates.insert("tier".to_string(), serde_json::json!("gold"));
        assert_eq!(extract_field_str(&updates, "tier"), Some("gold".to_string()));
    }

    #[test]
    fn test_extract_field_is_active() {
        let mut updates = HashMap::new();
        updates.insert("is_active".to_string(), serde_json::json!(true));
        assert_eq!(extract_field_bool(&updates, "is_active"), Some(true));
    }

    #[test]
    fn test_extract_field_strength() {
        let mut updates = HashMap::new();
        updates.insert("strength".to_string(), serde_json::json!(0.5));
        let val = extract_field_f64(&updates, "strength");
        assert!(val.is_some());
        assert!((val.unwrap() - 0.5).abs() < 1e-10);
    }

    #[test]
    fn test_extract_field_trust_score() {
        let mut updates = HashMap::new();
        updates.insert("trust_score".to_string(), serde_json::json!(0.8));
        let val = extract_field_f64(&updates, "trust_score");
        assert!(val.is_some());
        assert!((val.unwrap() - 0.8).abs() < 1e-10);
    }

    #[test]
    fn test_extract_field_user_scope() {
        let mut updates = HashMap::new();
        updates.insert("user_scope".to_string(), serde_json::json!("public"));
        assert_eq!(extract_field_str(&updates, "user_scope"), Some("public".to_string()));
    }

    #[test]
    fn test_extract_field_memory_type() {
        let mut updates = HashMap::new();
        updates.insert("memory_type".to_string(), serde_json::json!("episodic"));
        assert_eq!(extract_field_str(&updates, "memory_type"), Some("episodic".to_string()));
    }

    #[test]
    fn test_extract_field_category() {
        let mut updates = HashMap::new();
        updates.insert("category".to_string(), serde_json::json!("facts"));
        assert_eq!(extract_field_str(&updates, "category"), Some("facts".to_string()));
    }

    #[test]
    fn test_extract_field_immutable() {
        let mut updates = HashMap::new();
        updates.insert("immutable".to_string(), serde_json::json!(true));
        assert_eq!(extract_field_bool(&updates, "immutable"), Some(true));
    }

    #[test]
    fn test_extract_field_missing() {
        let updates: HashMap<String, serde_json::Value> = HashMap::new();
        assert_eq!(extract_field_str(&updates, "content"), None);
        assert_eq!(extract_field_f64(&updates, "confidence"), None);
        assert_eq!(extract_field_bool(&updates, "immutable"), None);
    }

    #[test]
    fn test_extract_field_wrong_type() {
        let mut updates = HashMap::new();
        updates.insert("content".to_string(), serde_json::json!(42));
        // as_str on a number returns None
        assert_eq!(extract_field_str(&updates, "content"), None);
    }

    // ── JSON parsing pattern tests ────────────────────────────────────

    #[test]
    fn test_parse_ids_json_valid_array() {
        let json = r#"["id1","id2","id3"]"#;
        let ids: Vec<String> = serde_json::from_str(json).unwrap();
        assert_eq!(ids.len(), 3);
        assert_eq!(ids[0], "id1");
    }

    #[test]
    fn test_parse_ids_json_empty_array() {
        let json = r#"[]"#;
        let ids: Vec<String> = serde_json::from_str(json).unwrap();
        assert!(ids.is_empty());
    }

    #[test]
    fn test_parse_ids_json_invalid() {
        let json = r#"not json"#;
        let result: Result<Vec<String>, _> = serde_json::from_str(json);
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(!err.is_empty());
    }

    #[test]
    fn test_parse_updates_json_valid_object() {
        let json = r#"{"content":"hello","confidence":0.9}"#;
        let updates: HashMap<String, serde_json::Value> = serde_json::from_str(json).unwrap();
        assert_eq!(updates.len(), 2);
    }

    #[test]
    fn test_parse_updates_json_empty_object() {
        let json = r#"{}"#;
        let updates: HashMap<String, serde_json::Value> = serde_json::from_str(json).unwrap();
        assert!(updates.is_empty());
    }

    #[test]
    fn test_parse_updates_json_invalid() {
        let json = r#"["not an object"]"#;
        let result: Result<HashMap<String, serde_json::Value>, _> = serde_json::from_str(json);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_ids_json_large_valid() {
        let ids: Vec<String> = (0..MAX_BATCH_SIZE).map(|i| format!("id-{}", i)).collect();
        let json = serde_json::to_string(&ids).unwrap();
        let parsed: Vec<String> = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.len(), MAX_BATCH_SIZE);
    }

    // ── MemoryMeta construction pattern tests ─────────────────────────
    // These test the construction pattern used in upsert_memory_meta.

    #[test]
    fn test_memory_meta_construction_with_all_fields() {
        let meta = crate::memory_meta::MemoryMeta {
            id: "meta-001".to_string(),
            workspace_id: "ws-1".to_string(),
            memory_id: "mem-001".to_string(),
            category: "preferences".to_string(),
            immutable: true,
            extra_json: "{}".to_string(),
            created_at: 1_000_000,
            updated_at: 2_000_000,
        };
        assert_eq!(meta.id, "meta-001");
        assert_eq!(meta.category, "preferences");
        assert!(meta.immutable);
    }

    #[test]
    fn test_memory_meta_construction_defaults() {
        let meta = crate::memory_meta::MemoryMeta {
            id: String::new(),
            workspace_id: String::new(),
            memory_id: String::new(),
            category: String::new(),
            immutable: false,
            extra_json: String::new(),
            created_at: 0,
            updated_at: 0,
        };
        assert!(meta.id.is_empty());
        assert!(!meta.immutable);
        assert!(meta.category.is_empty());
    }

    #[test]
    fn test_memory_meta_category_immutable_extraction() {
        // Simulate the pattern: new_category extracted from updates["category"]
        let mut updates = HashMap::new();
        updates.insert("category".to_string(), serde_json::json!("history"));
        updates.insert("immutable".to_string(), serde_json::json!(false));

        let new_category: Option<String> = updates.get("category").and_then(|v| v.as_str()).map(|s| s.to_string());
        let new_immutable: Option<bool> = updates.get("immutable").and_then(|v| v.as_bool());

        assert_eq!(new_category, Some("history".to_string()));
        assert_eq!(new_immutable, Some(false));
    }

    #[test]
    fn test_memory_meta_category_immutable_missing() {
        let updates: HashMap<String, serde_json::Value> = HashMap::new();

        let new_category: Option<String> = updates.get("category").and_then(|v| v.as_str()).map(|s| s.to_string());
        let new_immutable: Option<bool> = updates.get("immutable").and_then(|v| v.as_bool());

        assert!(new_category.is_none());
        assert!(new_immutable.is_none());
    }

    // ── Error message format tests ─────────────────────────────────────

    #[test]
    fn test_error_message_batch_size_exceeded() {
        let size = MAX_BATCH_SIZE + 1;
        let err = format!("Batch size {} exceeds maximum {}", size, MAX_BATCH_SIZE);
        assert!(err.contains("exceeds maximum"));
        assert!(err.contains(&size.to_string()));
    }

    #[test]
    fn test_error_message_invalid_ids_json() {
        let invalid = "not valid json at all";
        let err = format!("Invalid ids_json: {}", serde_json::from_str::<Vec<String>>(invalid).unwrap_err());
        assert!(err.starts_with("Invalid ids_json:"));
    }

    #[test]
    fn test_error_message_invalid_updates_json() {
        let invalid = "not a json object";
        let err = format!("Invalid updates_json: {}", serde_json::from_str::<HashMap<String, serde_json::Value>>(invalid).unwrap_err());
        assert!(err.starts_with("Invalid updates_json:"));
    }
}
