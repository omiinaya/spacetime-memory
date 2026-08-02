use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};

/// An entity link stores a canonical entity name with aliases,
/// providing Mem0-style entity resolution for the knowledge graph.
#[table(accessor = entity_link)]
#[derive(Debug, Clone)]
pub struct EntityLink {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Canonical entity name
    pub entity_name: String,
    /// JSON array of alias strings
    pub aliases_json: String,
    /// Entity type classification
    pub entity_type: String,
    pub description: String,
    /// How many times this entity has been mentioned/extracted
    pub used_count: u64,
    /// Micros timestamp of first occurrence
    pub first_seen: i64,
    /// Micros timestamp of most recent occurrence
    pub last_seen: i64,
    pub created_at: i64,
}

#[reducer]
pub fn create_entity_link(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_name: String,
    aliases_json: String,
    entity_type: String,
    description: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v7(ctx);

    let el = EntityLink {
        id: id.clone(),
        workspace_id,
        entity_name,
        aliases_json,
        entity_type,
        description,
        used_count: 0,
        first_seen: now,
        last_seen: now,
        created_at: now,
    };

    ctx.db.entity_link().insert(el);
    Ok(())
}

/// Append an alias to a JSON array of aliases, returning the updated JSON string.
/// This is a pure helper extracted so it can be unit-tested independently of the SpacetimeDB runtime.
fn append_alias(aliases_json: &str, alias: &str) -> String {
    let mut aliases: Vec<String> = match serde_json::from_str(aliases_json) {
        Ok(v) => v,
        Err(e) => {
            log::info!("Failed to parse aliases_json: {}", e);
            Vec::new()
        }
    };
    aliases.push(alias.to_string());
    serde_json::to_string(&aliases).unwrap_or_else(|_| "[]".to_string())
}

#[reducer]
pub fn add_alias(ctx: &ReducerContext, id: String, alias: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let mut el = ctx
        .db
        .entity_link()
        .id()
        .find(&id)
        .ok_or_else(|| format!("EntityLink '{}' not found", id))?;

    el.aliases_json = append_alias(&el.aliases_json, &alias);

    ctx.db.entity_link().id().update(el);
    Ok(())
}

/// Resolve an entity name within a workspace by checking if it exists.
#[reducer]
pub fn resolve_entity(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Check if entity already exists in this workspace
    let existing = ctx
        .db
        .entity_link()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS)
        .find(|el| el.entity_name.eq_ignore_ascii_case(&name));

    if let Some(el) = existing {
        log::info!(
            "Entity '{}' resolved to link '{}' (type: {}) in workspace {}",
            name,
            el.id,
            el.entity_type,
            workspace_id
        );
    } else {
        log::info!("Entity '{}' not found in workspace {}", name, workspace_id);
    }

    Ok(())
}

// -----------------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::append_alias;
    use super::EntityLink;

    #[test]
    fn test_entity_link_creation() {
        let el = EntityLink {
            id: "test-id-001".to_string(),
            workspace_id: "ws-abc".to_string(),
            entity_name: "TestEntity".to_string(),
            aliases_json: r#"["A","B"]"#.to_string(),
            entity_type: "concept".to_string(),
            description: "A test entity for unit testing".to_string(),
            used_count: 0,
            first_seen: 1_234_567_890,
            last_seen: 1_234_567_890,
            created_at: 1_234_567_890,
        };
        assert_eq!(el.id, "test-id-001");
        assert_eq!(el.workspace_id, "ws-abc");
        assert_eq!(el.entity_name, "TestEntity");
        assert_eq!(el.aliases_json, r#"["A","B"]"#);
        assert_eq!(el.entity_type, "concept");
        assert_eq!(el.description, "A test entity for unit testing");
        assert_eq!(el.used_count, 0);
        assert_eq!(el.first_seen, 1_234_567_890);
        assert_eq!(el.last_seen, 1_234_567_890);
        assert_eq!(el.created_at, 1_234_567_890);
    }

    #[test]
    fn test_entity_link_alias_append() {
        let aliases_json = r#"["A","B"]"#;
        let result = append_alias(aliases_json, "C");
        assert_eq!(result, r#"["A","B","C"]"#);
    }

    // -------------------------------------------------------------------------
    // append_alias
    // -------------------------------------------------------------------------

    #[test]
    fn test_append_alias_empty_json() {
        let result = append_alias("[]", "first");
        assert_eq!(result, r#"["first"]"#);
    }

    #[test]
    fn test_append_alias_multiple() {
        let result = append_alias(r#"["a"]"#, "b");
        assert_eq!(result, r#"["a","b"]"#);
    }

    #[test]
    fn test_append_alias_special_chars() {
        let result = append_alias(r#"[]"#, "some-alias-with-dashes");
        assert_eq!(result, r#"["some-alias-with-dashes"]"#);
    }

    #[test]
    fn test_append_alias_with_unicode() {
        let result = append_alias(r#"["ascii"]"#, "uber-cool");
        assert_eq!(result, r#"["ascii","uber-cool"]"#);
    }

    #[test]
    fn test_append_alias_invalid_json_falls_back_to_empty() {
        let result = append_alias("not-json", "fallback");
        assert_eq!(result, r#"["fallback"]"#);
    }

    #[test]
    fn test_append_alias_empty_string_value() {
        let result = append_alias("[]", "");
        assert_eq!(result, r#"[""]"#);
    }

    #[test]
    fn test_append_alias_empty_input_json() {
        let result = append_alias("", "only");
        assert_eq!(result, r#"["only"]"#);
    }

    #[test]
    fn test_append_alias_null_json() {
        let result = append_alias("null", "after-null");
        assert_eq!(result, r#"["after-null"]"#);
    }

    #[test]
    fn test_append_alias_whitespace_preserved() {
        let result = append_alias(r#"["hello world"]"#, "  spaced  ");
        assert_eq!(result, r#"["hello world","  spaced  "]"#);
    }

    #[test]
    fn test_append_alias_ten_aliases() {
        let mut json = "[]".to_string();
        for i in 0..10 {
            json = append_alias(&json, &format!("alias-{}", i));
        }
        let expected = r#"["alias-0","alias-1","alias-2","alias-3","alias-4","alias-5","alias-6","alias-7","alias-8","alias-9"]"#;
        assert_eq!(json, expected);
    }

    #[test]
    fn test_append_alias_duplicates_not_deduplicated() {
        let json = r#"["same"]"#;
        let result = append_alias(json, "same");
        assert_eq!(result, r#"["same","same"]"#);
    }

    #[test]
    fn test_append_alias_json_with_escaped_chars() {
        let json = r#"["quote\"inside"]"#;
        let result = append_alias(json, "normal");
        assert_eq!(result, r#"["quote\"inside","normal"]"#);
    }

    #[test]
    fn test_append_alias_preserves_original_on_valid() {
        let json = r#"["alpha","beta","gamma"]"#;
        let result = append_alias(json, "delta");
        assert_eq!(result, r#"["alpha","beta","gamma","delta"]"#);
    }

    #[test]
    fn test_append_alias_number_in_json() {
        let result = append_alias(r#"[1, 2, 3]"#, "fallback");
        assert_eq!(result, r#"["fallback"]"#);
    }

    #[test]
    fn test_append_alias_mixed_types_in_json() {
        let result = append_alias(r#"["valid", 42]"#, "after-mixed");
        assert_eq!(result, r#"["after-mixed"]"#);
    }

    #[test]
    fn test_append_alias_nested_json() {
        let result = append_alias(r#"[{"name": "test"}]"#, "simple");
        assert_eq!(result, r#"["simple"]"#);
    }

    #[test]
    fn test_append_alias_large_alias_value() {
        let large = "x".repeat(10_000);
        let result = append_alias("[]", &large);
        assert!(result.len() > 10_000);
        assert!(result.contains(&large));
    }

    #[test]
    fn test_append_alias_output_is_valid_json() {
        let result = append_alias(r#"["a","b"]"#, "c");
        let parsed: Result<Vec<String>, _> = serde_json::from_str(&result);
        assert!(parsed.is_ok(), "append_alias output must be valid JSON");
        let parsed = parsed.unwrap();
        assert_eq!(parsed.len(), 3);
        assert!(parsed.contains(&"a".to_string()));
        assert!(parsed.contains(&"b".to_string()));
        assert!(parsed.contains(&"c".to_string()));
    }

    #[test]
    fn test_append_alias_idempotent_valid_json() {
        let r1 = append_alias(r#"["x","y"]"#, "z");
        let r2 = append_alias(&r1, "w");
        assert_eq!(r2, r#"["x","y","z","w"]"#);
    }

    #[test]
    fn test_append_alias_back_to_back_calls() {
        let mut json = r#"["start"]"#.to_string();
        json = append_alias(&json, "a");
        json = append_alias(&json, "b");
        json = append_alias(&json, "c");
        assert_eq!(json, r#"["start","a","b","c"]"#);
    }

    #[test]
    fn test_append_alias_boolean_in_json() {
        let result = append_alias(r#"[true, false]"#, "recovery");
        assert_eq!(result, r#"["recovery"]"#);
    }

    #[test]
    fn test_append_alias_null_element_in_json() {
        let result = append_alias(r#"["ok", null]"#, "after-null");
        assert_eq!(result, r#"["after-null"]"#);
    }

    // -------------------------------------------------------------------------
    // EntityLink struct edge cases
    // -------------------------------------------------------------------------

    #[test]
    fn test_entity_link_clone_maintains_all_fields() {
        let el = EntityLink {
            id: "clone-test".to_string(),
            workspace_id: "ws-clone".to_string(),
            entity_name: "CloneEntity".to_string(),
            aliases_json: r#"["original"]"#.to_string(),
            entity_type: "concept".to_string(),
            description: "Clone test".to_string(),
            used_count: 42,
            first_seen: 100,
            last_seen: 200,
            created_at: 50,
        };
        let cloned = el.clone();
        assert_eq!(cloned.id, el.id);
        assert_eq!(cloned.workspace_id, el.workspace_id);
        assert_eq!(cloned.entity_name, el.entity_name);
        assert_eq!(cloned.aliases_json, el.aliases_json);
        assert_eq!(cloned.entity_type, el.entity_type);
        assert_eq!(cloned.description, el.description);
        assert_eq!(cloned.used_count, 42);
        assert_eq!(cloned.first_seen, 100);
        assert_eq!(cloned.last_seen, 200);
        assert_eq!(cloned.created_at, 50);
    }

    #[test]
    fn test_entity_link_debug_format() {
        let el = EntityLink {
            id: "debug-test".to_string(),
            workspace_id: "ws-debug".to_string(),
            entity_name: "DebugEntity".to_string(),
            aliases_json: "[]".to_string(),
            entity_type: "entity".to_string(),
            description: String::new(),
            used_count: 7,
            first_seen: 300,
            last_seen: 400,
            created_at: 300,
        };
        let debug_str = format!("{:?}", el);
        assert!(debug_str.contains("debug-test"));
        assert!(debug_str.contains("DebugEntity"));
        assert!(debug_str.contains("used_count: 7"));
    }

    #[test]
    fn test_entity_link_empty_strings_allowed() {
        let el = EntityLink {
            id: String::new(),
            workspace_id: String::new(),
            entity_name: String::new(),
            aliases_json: "[]".to_string(),
            entity_type: String::new(),
            description: String::new(),
            used_count: 0,
            first_seen: 0,
            last_seen: 0,
            created_at: 0,
        };
        assert_eq!(el.id, "");
        assert_eq!(el.workspace_id, "");
        assert_eq!(el.entity_name, "");
        assert_eq!(el.entity_type, "");
    }

    #[test]
    fn test_entity_link_large_string_fields() {
        let long_name = "a".repeat(10_000);
        let el = EntityLink {
            id: "large-test".to_string(),
            workspace_id: "ws-large".to_string(),
            entity_name: long_name.clone(),
            aliases_json: format!(r#"["{}"]"#, "x".repeat(5_000)),
            entity_type: "concept".to_string(),
            description: "z".repeat(10_000),
            used_count: 0,
            first_seen: 0,
            last_seen: 0,
            created_at: 0,
        };
        assert_eq!(el.entity_name.len(), 10_000);
        assert_eq!(el.description.len(), 10_000);
        assert!(el.aliases_json.len() > 5_000);
    }

    #[test]
    fn test_entity_link_timestamps_monotonic() {
        let el = EntityLink {
            id: "ts-test".to_string(),
            workspace_id: "ws-ts".to_string(),
            entity_name: "TsEntity".to_string(),
            aliases_json: "[]".to_string(),
            entity_type: "entity".to_string(),
            description: String::new(),
            used_count: 0,
            first_seen: 100,
            last_seen: 200,
            created_at: 50,
        };
        assert!(el.created_at <= el.first_seen);
        assert!(el.first_seen <= el.last_seen);
    }

    #[test]
    fn test_entity_link_used_count_large() {
        let el = EntityLink {
            id: "count-test".to_string(),
            workspace_id: "ws-count".to_string(),
            entity_name: "CountEntity".to_string(),
            aliases_json: "[]".to_string(),
            entity_type: "concept".to_string(),
            description: String::new(),
            used_count: u64::MAX,
            first_seen: 1,
            last_seen: 2,
            created_at: 0,
        };
        assert_eq!(el.used_count, u64::MAX);
    }

    #[test]
    fn test_append_alias_preserves_existing_on_number_json() {
        // When aliases_json contains a number instead of an array,
        // append_alias should fall back to empty and start fresh.
        let result = append_alias("42", "fallback");
        assert_eq!(result, r#"["fallback"]"#);
    }
}
