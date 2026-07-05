use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};
use crate::workspace::check_space_access;
use crate::trace_span;
use crate::tracing::TracingSpanKind;

/// A peer represents a user, AI agent, or other entity participating in sessions.
#[table(accessor = peer)]
#[derive(Debug, Clone)]
pub struct Peer {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    /// "user" | "agent" | "entity"
    pub peer_type: String,
    /// JSON metadata blob; defaults to "{}"
    pub metadata: String,
    pub created_at: i64,
    pub updated_at: i64,
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
        // Validate peer_type
        match peer_type.as_str() {
            "user" | "agent" | "entity" => {}
            _ => {
                return Err(format!(
                    "Invalid peer_type '{}': must be 'user', 'agent', or 'entity'",
                    peer_type
                ));
            }
        }

        let now = now_micros(ctx);
        let id = uuid_v7(ctx);

        ctx.db.peer().insert(Peer {
            id: id.clone(),
            workspace_id,
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
