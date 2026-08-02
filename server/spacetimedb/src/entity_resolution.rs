use spacetimedb::*;
use crate::auth::require_auth;
use crate::query::query_result;
use crate::{now_micros, uuid_v7};

/// MinHash entity signature, stored for fuzzy entity resolution (Graphiti parity).
///
/// The `signatures_json` field holds a JSON array of signature vectors, each
/// a JSON array of u64 hash values (128 minhashes per signature).
#[table(accessor = entity_signature)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct EntitySignature {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    #[index(btree)]
    pub entity_id: String,
    /// Canonical entity name at time of indexing
    pub entity_name: String,
    /// JSON array of signature arrays: [[u64; 128], ...]
    pub signatures_json: String,
    /// Number of hash functions used per signature (typically 128)
    pub num_hashes: u32,
    /// Algorithm version (1 = MinHash with sha256, 3-gram shingles)
    pub algorithm_version: u32,
    pub created_at: i64,
    pub updated_at: i64,
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn store_entity_signature(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_id: String,
    entity_name: String,
    signatures_json: String,
    num_hashes: u32,
    algorithm_version: u32,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    // Upsert: if a signature for this workspace+entity already exists, update it
    let existing = ctx
        .db
        .entity_signature()
        .workspace_id()
        .filter(&workspace_id)
        .find(|s| s.entity_id == entity_id);

    if let Some(mut sig) = existing {
        sig.entity_name = entity_name;
        sig.signatures_json = signatures_json;
        sig.num_hashes = num_hashes;
        sig.algorithm_version = algorithm_version;
        sig.updated_at = now;
        ctx.db.entity_signature().id().update(sig);
    } else {
        let id = uuid_v7(ctx);
        let sig = EntitySignature {
            id,
            workspace_id,
            entity_id,
            entity_name,
            signatures_json,
            num_hashes,
            algorithm_version,
            created_at: now,
            updated_at: now,
        };
        ctx.db.entity_signature().insert(sig);
    }

    Ok(())
}

/// Batch search signatures — returns all signatures in a workspace that match
/// the given entity_ids.  Used by the client for pre-filtering before fuzzy
/// comparison.
#[reducer]
pub fn batch_search_signatures(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_ids_json: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Parse the entity_id filter list
    let entity_ids: Vec<String> = serde_json::from_str(&entity_ids_json)
        .unwrap_or_default();

    // Insert matching results into a transient result table for the client to read.
    // We write to query_result (the existing infrastructure).
    let query_id = uuid_v7(ctx);

    let sigs = ctx
        .db
        .entity_signature()
        .workspace_id()
        .filter(&workspace_id)
        .take(crate::MAX_RESULTS);

    for sig in sigs {
        if entity_ids.is_empty() || entity_ids.contains(&sig.entity_id) {
            let row_json = serde_json::to_string(&sig)
                .unwrap_or_else(|_| "{}".to_string());
            ctx.db.query_result().insert(crate::query::GenericQueryResult {
                id: crate::uuid_v7(ctx),
                query_id: query_id.clone(),
                table_name: "entity_signature".to_string(),
                row_json,
                created_at: crate::now_micros(ctx),
            });
        }
    }

    Ok(())
}

/// Get a single entity signature by entity_id within a workspace.
#[reducer]
pub fn get_entity_signature(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    let sig = ctx
        .db
        .entity_signature()
        .workspace_id()
        .filter(&workspace_id)
        .find(|s| s.entity_id == entity_id);

    let query_id = uuid_v7(ctx);
    if let Some(s) = sig {
        let row_json = serde_json::to_string(&s)
            .unwrap_or_else(|_| "{}".to_string());
        ctx.db.query_result().insert(crate::query::GenericQueryResult {
            id: crate::uuid_v7(ctx),
            query_id,
            table_name: "entity_signature".to_string(),
            row_json,
            created_at: crate::now_micros(ctx),
        });
    }

    Ok(())
}

#[reducer]
pub fn delete_entity_signature(
    ctx: &ReducerContext,
    workspace_id: String,
    entity_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;

    if let Some(sig) = ctx
        .db
        .entity_signature()
        .workspace_id()
        .filter(&workspace_id)
        .find(|s| s.entity_id == entity_id)
    {
        ctx.db.entity_signature().id().delete(sig.id);
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_entity_signature_struct() {
        let sig = EntitySignature {
            id: "sig-001".to_string(),
            workspace_id: "ws-abc".to_string(),
            entity_id: "ent-001".to_string(),
            entity_name: "Test Entity".to_string(),
            signatures_json: r#"[[1,2,3]]"#.to_string(),
            num_hashes: 128,
            algorithm_version: 1,
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };

        assert_eq!(sig.id, "sig-001");
        assert_eq!(sig.workspace_id, "ws-abc");
        assert_eq!(sig.entity_id, "ent-001");
        assert_eq!(sig.entity_name, "Test Entity");
        assert_eq!(sig.signatures_json, r#"[[1,2,3]]"#);
        assert_eq!(sig.num_hashes, 128);
        assert_eq!(sig.algorithm_version, 1);
        assert_eq!(sig.created_at, 1_000_000);
        assert_eq!(sig.updated_at, 1_000_000);
    }

    #[test]
    fn test_entity_signature_clone() {
        let sig = EntitySignature {
            id: "clone-test".to_string(),
            workspace_id: "ws-clone".to_string(),
            entity_id: "ent-clone".to_string(),
            entity_name: "Clone".to_string(),
            signatures_json: "[]".to_string(),
            num_hashes: 128,
            algorithm_version: 1,
            created_at: 100,
            updated_at: 200,
        };
        let cloned = sig.clone();
        assert_eq!(cloned.id, sig.id);
        assert_eq!(cloned.workspace_id, sig.workspace_id);
        assert_eq!(cloned.entity_id, sig.entity_id);
        assert_eq!(cloned.entity_name, sig.entity_name);
        assert_eq!(cloned.signatures_json, sig.signatures_json);
        assert_eq!(cloned.num_hashes, 128);
        assert_eq!(cloned.algorithm_version, 1);
        assert_eq!(cloned.created_at, 100);
        assert_eq!(cloned.updated_at, 200);
    }

    #[test]
    fn test_entity_signature_debug_format() {
        let sig = EntitySignature {
            id: "debug-test".to_string(),
            workspace_id: "ws-debug".to_string(),
            entity_id: "ent-debug".to_string(),
            entity_name: "Debug".to_string(),
            signatures_json: "[]".to_string(),
            num_hashes: 64,
            algorithm_version: 1,
            created_at: 0,
            updated_at: 0,
        };
        let debug = format!("{:?}", sig);
        assert!(debug.contains("debug-test"));
        assert!(debug.contains("Debug"));
        assert!(debug.contains("num_hashes: 64"));
    }

    #[test]
    fn test_entity_signature_empty_strings() {
        let sig = EntitySignature {
            id: String::new(),
            workspace_id: String::new(),
            entity_id: String::new(),
            entity_name: String::new(),
            signatures_json: "[]".to_string(),
            num_hashes: 0,
            algorithm_version: 0,
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(sig.id, "");
        assert_eq!(sig.workspace_id, "");
        assert_eq!(sig.entity_id, "");
        assert_eq!(sig.entity_name, "");
    }

    #[test]
    fn test_entity_signature_large_fields() {
        let long_name = "x".repeat(10_000);
        let sig = EntitySignature {
            id: "large-test".to_string(),
            workspace_id: "ws-large".to_string(),
            entity_id: "ent-large".to_string(),
            entity_name: long_name.clone(),
            signatures_json: format!(r#"[{}]"#, "1,".repeat(128)),
            num_hashes: 128,
            algorithm_version: 1,
            created_at: 0,
            updated_at: 0,
        };
        assert_eq!(sig.entity_name.len(), 10_000);
        assert!(sig.signatures_json.len() > 128);
    }

    #[test]
    fn test_entity_signature_algorithm_versions() {
        let v1 = EntitySignature {
            algorithm_version: 1,
            ..create_dummy()
        };
        let v2 = EntitySignature {
            algorithm_version: 2,
            ..create_dummy()
        };
        assert_eq!(v1.algorithm_version, 1);
        assert_eq!(v2.algorithm_version, 2);
    }

    #[test]
    fn test_entity_signature_num_hashes_variants() {
        let s128 = EntitySignature {
            num_hashes: 128,
            ..create_dummy()
        };
        let s64 = EntitySignature {
            num_hashes: 64,
            ..create_dummy()
        };
        assert_eq!(s128.num_hashes, 128);
        assert_eq!(s64.num_hashes, 64);
    }

    fn create_dummy() -> EntitySignature {
        EntitySignature {
            id: "dummy".to_string(),
            workspace_id: "ws-dummy".to_string(),
            entity_id: "ent-dummy".to_string(),
            entity_name: "Dummy".to_string(),
            signatures_json: "[]".to_string(),
            num_hashes: 128,
            algorithm_version: 1,
            created_at: 0,
            updated_at: 0,
        }
    }

    #[test]
    fn test_entity_signature_timestamps_order() {
        let sig = EntitySignature {
            created_at: 100,
            updated_at: 200,
            ..create_dummy()
        };
        assert!(sig.created_at <= sig.updated_at);
    }

    #[test]
    fn test_entity_signature_json_roundtrip() {
        let sig = EntitySignature {
            id: "rt-test".to_string(),
            workspace_id: "ws-rt".to_string(),
            entity_id: "ent-rt".to_string(),
            entity_name: "RoundTrip".to_string(),
            signatures_json: r#"[[1,2,3],[4,5,6]]"#.to_string(),
            num_hashes: 3,
            algorithm_version: 1,
            created_at: 1000,
            updated_at: 1000,
        };

        let json = serde_json::to_string(&sig).expect("serialize");
        let parsed: EntitySignature = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(parsed.id, sig.id);
        assert_eq!(parsed.workspace_id, sig.workspace_id);
        assert_eq!(parsed.entity_id, sig.entity_id);
        assert_eq!(parsed.entity_name, sig.entity_name);
        assert_eq!(parsed.signatures_json, sig.signatures_json);
        assert_eq!(parsed.num_hashes, 3);
        assert_eq!(parsed.algorithm_version, 1);
        assert_eq!(parsed.created_at, 1000);
        assert_eq!(parsed.updated_at, 1000);
    }

    #[test]
    fn test_entity_signature_missing_fields_deserialize() {
        // Verify that missing signatures_json defaults gracefully
        let json = r#"{
            "id": "partial",
            "workspace_id": "ws-p",
            "entity_id": "ent-p",
            "entity_name": "Partial"
        }"#;
        let result: Result<EntitySignature, _> = serde_json::from_str(json);
        // Missing required fields should fail (our struct has no Option fields)
        assert!(result.is_err());
    }

    #[test]
    fn test_entity_signature_max_num_hashes() {
        let sig = EntitySignature {
            num_hashes: u32::MAX,
            ..create_dummy()
        };
        assert_eq!(sig.num_hashes, u32::MAX);
    }

    #[test]
    fn test_entity_signature_serialize_deserialize_empty_json() {
        let sig = EntitySignature {
            signatures_json: "[]".to_string(),
            ..create_dummy()
        };
        let json = serde_json::to_string(&sig).expect("serialize");
        let parsed: EntitySignature = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(parsed.signatures_json, "[]");
    }

    #[test]
    fn test_entity_signature_serialize_deserialize_nested_json() {
        let sig = EntitySignature {
            signatures_json: r#"[[1,2,3],[4,5,6],[7,8,9]]"#.to_string(),
            ..create_dummy()
        };
        let json = serde_json::to_string(&sig).expect("serialize");
        let parsed: EntitySignature = serde_json::from_str(&json).expect("deserialize");
        let parsed_sigs: Vec<Vec<u64>> = serde_json::from_str(&parsed.signatures_json).expect("parse sigs");
        assert_eq!(parsed_sigs.len(), 3);
        assert_eq!(parsed_sigs[0], vec![1, 2, 3]);
    }
}
