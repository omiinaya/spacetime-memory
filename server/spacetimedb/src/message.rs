use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};
use crate::session::check_session_access;
use crate::trace_span;
use crate::tracing::TracingSpanKind;

/// A message within a session. Content types: "text", "tool_call", "tool_result", "event".
#[table(accessor = message)]
#[derive(Debug, Clone)]
pub struct Message {
    #[primary_key]
    pub id: String,
    pub session_id: String,
    pub sender_id: String,
    pub content: String,
    /// "text" | "tool_call" | "tool_result" | "event"
    pub content_type: String,
    pub metadata: String,
    pub created_at: i64,
}

#[reducer]
pub fn send_message(
    ctx: &ReducerContext,
    session_id: String,
    sender_id: String,
    content: String,
    content_type: String,
    metadata_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "send_message", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        // Verify session exists + caller has permission
        let caller = ctx.sender().to_hex();
        let _workspace_id = check_session_access(ctx, &session_id, &caller, "editor")?;

        // Validate content_type
        match content_type.as_str() {
            "text" | "tool_call" | "tool_result" | "event" => {}
            _ => {
                return Err(format!(
                    "Invalid content_type '{}': must be 'text', 'tool_call', 'tool_result', or 'event'",
                    content_type
                ));
            }
        }

        let now = now_micros(ctx);
        let id = uuid_v7(ctx);

        ctx.db.message().insert(Message {
            id: id.clone(),
            session_id,
            sender_id,
            content,
            content_type,
            metadata: if metadata_json.is_empty() {
                String::from("{}")
            } else {
                metadata_json
            },
            created_at: now,
        });
        Ok(())
    })
}

#[reducer]
pub fn delete_message(ctx: &ReducerContext, id: String) -> Result<(), String> {
    trace_span!(ctx, "delete_message", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let msg = ctx
            .db
            .message()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Message '{}' not found", id))?;

        let caller = ctx.sender().to_hex();
        check_session_access(ctx, &msg.session_id, &caller, "editor")?;

        ctx.db.message().id().delete(&id);
        Ok(())
    })
}
