use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};
use crate::workspace::check_space_access;
use crate::trace_span;
use crate::tracing::TracingSpanKind;

/// A peer represents a user, AI agent, or other entity participating in sessions.
#[table(accessor = peer)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Peer {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub name: String,
    /// "user" | "agent" | "entity"
    pub peer_type: String,
    /// JSON metadata blob; defaults to "{}"
    pub metadata: String,
    pub created_at: i64,
    pub updated_at: i64,
}

/// Validates that `peer_type` is one of the allowed values: "user", "agent", or "entity".
pub fn validate_peer_type(peer_type: &str) -> Result<(), String> {
    match peer_type {
        "user" | "agent" | "entity" => Ok(()),
        _ => Err(format!(
            "Invalid peer_type '{}': must be 'user', 'agent', or 'entity'",
            peer_type
        )),
    }
}

#[reducer]
pub fn create_peer(
    ctx: &ReducerContext,
    workspace_id: String,
    name: String,
    peer_type: String,
    metadata_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_peer", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;
        validate_peer_type(&peer_type)?;

        let now = now_micros(ctx);
        let id = uuid_v7(ctx);

        ctx.db.peer().insert(Peer {
            id: id.clone(),
            workspace_id: workspace_id.clone(),
            name,
            peer_type,
            metadata: if metadata_json.is_empty() {
                String::from("{}")
            } else {
                metadata_json
            },
            created_at: now,
            updated_at: now,
        });
        Ok(())
    })
}

#[reducer]
pub fn update_peer(
    ctx: &ReducerContext,
    id: String,
    name: String,
    metadata_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "update_peer", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let existing = ctx
            .db
            .peer()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Peer '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &existing.workspace_id, &caller, "editor")?;

        ctx.db.peer().id().update(Peer {
            id: id.clone(),
            workspace_id: existing.workspace_id,
            name,
            peer_type: existing.peer_type,
            metadata: if metadata_json.is_empty() {
                String::from("{}")
            } else {
                metadata_json
            },
            created_at: existing.created_at,
            updated_at: now_micros(ctx),
        });
        Ok(())
    })
}

#[reducer]
pub fn delete_peer(ctx: &ReducerContext, id: String) -> Result<(), String> {
    trace_span!(ctx, "delete_peer", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let peer = ctx
            .db
            .peer()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Peer '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &peer.workspace_id, &caller, "editor")?;

        ctx.db.peer().id().delete(&id);
        Ok(())
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use pretty_assertions::assert_eq;

    // -----------------------------------------------------------------------
    // validate_peer_type tests
    // -----------------------------------------------------------------------

    #[rstest]
    #[case("user")]
    #[case("agent")]
    #[case("entity")]
    fn test_validate_peer_type_valid(#[case] peer_type: &str) {
        assert_eq!(validate_peer_type(peer_type), Ok(()));
    }

    #[rstest]
    #[case("admin")]
    #[case("robot")]
    #[case("system")]
    #[case("User")]   // case-sensitive
    #[case("AGENT")]  // case-sensitive
    #[case("Entity")] // case-sensitive
    #[case(" user")]  // leading whitespace
    #[case("user ")]  // trailing whitespace
    fn test_validate_peer_type_invalid(#[case] peer_type: &str) {
        let result = validate_peer_type(peer_type);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("Invalid peer_type"));
        assert!(err.contains("must be 'user', 'agent', or 'entity'"));
    }

    #[test]
    fn test_validate_peer_type_empty() {
        let result = validate_peer_type("");
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("Invalid peer_type"));
    }

    // -----------------------------------------------------------------------
    // Peer struct initialization tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_peer_struct_initialization() {
        let peer = Peer {
            id: "peer-001".to_string(),
            workspace_id: "ws-001".to_string(),
            name: "Test User".to_string(),
            peer_type: "user".to_string(),
            metadata: "{\"email\":\"test@example.com\"}".to_string(),
            created_at: 1_000_000,
            updated_at: 2_000_000,
        };

        assert_eq!(peer.id, "peer-001");
        assert_eq!(peer.workspace_id, "ws-001");
        assert_eq!(peer.name, "Test User");
        assert_eq!(peer.peer_type, "user");
        assert_eq!(peer.metadata, "{\"email\":\"test@example.com\"}");
        assert_eq!(peer.created_at, 1_000_000);
        assert_eq!(peer.updated_at, 2_000_000);
    }

    #[test]
    fn test_peer_default_metadata() {
        let peer = Peer {
            id: "peer-002".to_string(),
            workspace_id: "ws-001".to_string(),
            name: "Agent One".to_string(),
            peer_type: "agent".to_string(),
            metadata: "{}".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(peer.metadata, "{}");
    }

    #[test]
    fn test_peer_struct_update_via_struct_literal() {
        let peer = Peer {
            id: "peer-003".to_string(),
            workspace_id: "ws-002".to_string(),
            name: "Entity X".to_string(),
            peer_type: "entity".to_string(),
            metadata: "{}".to_string(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        // Read fields
        assert_eq!(peer.peer_type, "entity");
        // Clone-and-mutate pattern (Peer derives Clone)
        let updated = Peer { name: "Entity X v2".to_string(), ..peer };
        assert_eq!(updated.name, "Entity X v2");
        assert_eq!(updated.id, "peer-003");
        assert_eq!(updated.peer_type, "entity");
    }

    // -----------------------------------------------------------------------
    // Serde tests (requires Serialize + Deserialize on Peer)
    // -----------------------------------------------------------------------

    #[test]
    fn test_peer_serialize_to_json() {
        let peer = Peer {
            id: "peer-010".to_string(),
            workspace_id: "ws-010".to_string(),
            name: "Serialize Test".to_string(),
            peer_type: "user".to_string(),
            metadata: "{\"role\":\"admin\"}".to_string(),
            created_at: 100,
            updated_at: 200,
        };

        let json = serde_json::to_string(&peer).expect("serialize to json");
        assert!(json.contains("\"id\":\"peer-010\""));
        assert!(json.contains("\"peer_type\":\"user\""));
        assert!(json.contains("\"created_at\":100"));
        assert!(json.contains("\"updated_at\":200"));
    }

    #[test]
    fn test_peer_deserialize_from_json() {
        let json = r#"{
            "id": "peer-011",
            "workspace_id": "ws-011",
            "name": "Deserialize Test",
            "peer_type": "agent",
            "metadata": "{\"model\":\"gpt-4\"}",
            "created_at": 300,
            "updated_at": 400
        }"#;

        let peer: Peer = serde_json::from_str(json).expect("deserialize from json");
        assert_eq!(peer.id, "peer-011");
        assert_eq!(peer.workspace_id, "ws-011");
        assert_eq!(peer.name, "Deserialize Test");
        assert_eq!(peer.peer_type, "agent");
        assert_eq!(peer.metadata, "{\"model\":\"gpt-4\"}");
        assert_eq!(peer.created_at, 300);
        assert_eq!(peer.updated_at, 400);
    }

    #[test]
    fn test_peer_roundtrip_serde() {
        let peer = Peer {
            id: "peer-012".to_string(),
            workspace_id: "ws-012".to_string(),
            name: "Round Trip".to_string(),
            peer_type: "entity".to_string(),
            metadata: "{}".to_string(),
            created_at: 500,
            updated_at: 600,
        };

        let json = serde_json::to_string(&peer).expect("serialize");
        let deserialized: Peer = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, peer.id);
        assert_eq!(deserialized.workspace_id, peer.workspace_id);
        assert_eq!(deserialized.name, peer.name);
        assert_eq!(deserialized.peer_type, peer.peer_type);
        assert_eq!(deserialized.metadata, peer.metadata);
        assert_eq!(deserialized.created_at, peer.created_at);
        assert_eq!(deserialized.updated_at, peer.updated_at);
    }
}
