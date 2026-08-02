use spacetimedb::*;
use crate::auth::require_auth;
use crate::crypto::encrypt_if_enabled;

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
    #[index(btree)]
    pub session_id: String,
    pub sender_id: String,
    pub content: String,
    /// "text" | "tool_call" | "tool_result" | "event"
    pub content_type: String,
    pub metadata: String,
    pub created_at: i64,
}

/// Validate that `content_type` is one of the allowed values: "text", "tool_call", "tool_result", or "event".
pub fn validate_content_type(content_type: &str) -> Result<(), String> {
    match content_type {
        "text" | "tool_call" | "tool_result" | "event" => Ok(()),
        _ => Err(format!(
            "Invalid content_type '{}': must be 'text', 'tool_call', 'tool_result', or 'event'",
            content_type
        )),
    }
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
        validate_content_type(&content_type)?;

        let now = now_micros(ctx);
        let id = uuid_v7(ctx);

        // Encrypt content if workspace encryption is enabled
        let enc_content = encrypt_if_enabled(ctx, &_workspace_id, &content)?;
        ctx.db.message().insert(Message {
            id: id.clone(),
            session_id,
            sender_id,
            content: enc_content,
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

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case("text")]
    #[case("tool_call")]
    #[case("tool_result")]
    #[case("event")]
    fn test_valid_content_types(#[case] content_type: &str) {
        assert!(validate_content_type(content_type).is_ok());
    }

    #[rstest]
    #[case("invalid")]
    #[case("text ")]
    #[case(" TEXT")]
    #[case("Tool_Call")]
    #[case("TOOL_RESULT")]
    #[case("Event")]
    #[case("text/plain")]
    #[case("")]
    #[case(" ")]
    #[case("tool_call\n")]
    #[case(" event")]
    fn test_invalid_content_types(#[case] content_type: &str) {
        let result = validate_content_type(content_type);
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains(content_type), "Error should contain the invalid type");
        assert!(err.contains("must be 'text', 'tool_call', 'tool_result', or 'event'"));
    }

    #[rstest]
    #[case("text", Err(String::new()))]
    #[case("tool_call", Err(String::new()))]
    #[case("tool_result", Err(String::new()))]
    #[case("event", Err(String::new()))]
    fn test_apply_valid(#[case] content_type: &str, #[case] _expected: Result<(), String>) {
        assert!(validate_content_type(content_type).is_ok());
    }

    #[rstest]
    #[case("bad", true)]
    #[case("text ", true)]
    #[case("", true)]
    #[case("TEXT", true)]
    fn test_apply_invalid(#[case] content_type: &str, #[case] expect_err: bool) {
        let result = validate_content_type(content_type);
        assert_eq!(result.is_err(), expect_err);
    }

    // ── Message struct construction tests ──────────────────────────────

    #[test]
    fn test_message_construction_text() {
        let msg = Message {
            id: "msg_001".to_string(),
            session_id: "sess_abc".to_string(),
            sender_id: "usr_001".to_string(),
            content: "Hello, world!".to_string(),
            content_type: "text".to_string(),
            metadata: r#"{}"#.to_string(),
            created_at: 1_700_000_000,
        };
        assert_eq!(msg.id, "msg_001");
        assert_eq!(msg.sender_id, "usr_001");
        assert_eq!(msg.content, "Hello, world!");
        assert_eq!(msg.content_type, "text");
    }

    #[test]
    fn test_message_construction_tool_call() {
        let msg = Message {
            id: "msg_002".to_string(),
            session_id: "sess_abc".to_string(),
            sender_id: "agent_001".to_string(),
            content: r#"{"name":"get_weather","args":{"city":"London"}}"#.to_string(),
            content_type: "tool_call".to_string(),
            metadata: r#"{"tool_id":"call_123"}"#.to_string(),
            created_at: 1_700_000_001,
        };
        assert_eq!(msg.content_type, "tool_call");
        assert!(msg.content.contains("get_weather"));
        assert!(msg.metadata.contains("call_123"));
    }

    #[test]
    fn test_message_construction_tool_result() {
        let msg = Message {
            id: "msg_003".to_string(),
            session_id: "sess_abc".to_string(),
            sender_id: "system".to_string(),
            content: r#"{"temperature":15,"conditions":"cloudy"}"#.to_string(),
            content_type: "tool_result".to_string(),
            metadata: r#"{"tool_id":"call_123"}"#.to_string(),
            created_at: 1_700_000_002,
        };
        assert_eq!(msg.content_type, "tool_result");
    }

    #[test]
    fn test_message_construction_event() {
        let msg = Message {
            id: "msg_004".to_string(),
            session_id: "sess_def".to_string(),
            sender_id: "system".to_string(),
            content: "User joined the session".to_string(),
            content_type: "event".to_string(),
            metadata: r#"{"event_type":"user_joined"}"#.to_string(),
            created_at: 1_700_000_003,
        };
        assert_eq!(msg.content_type, "event");
    }

    #[test]
    fn test_message_empty_content() {
        let msg = Message {
            id: "msg_empty".to_string(),
            session_id: "sess_empty".to_string(),
            sender_id: "usr_empty".to_string(),
            content: String::new(),
            content_type: "text".to_string(),
            metadata: r#"{}"#.to_string(),
            created_at: 0,
        };
        assert!(msg.content.is_empty());
        assert_eq!(msg.metadata, r#"{}"#);
    }

    #[test]
    fn test_message_default_metadata() {
        // In send_message, empty metadata_json becomes "{}"
        let metadata = if true { String::from("{}") } else { String::new() };
        let msg = Message {
            id: "msg_meta".to_string(),
            session_id: "sess_meta".to_string(),
            sender_id: "usr_meta".to_string(),
            content: "test".to_string(),
            content_type: "text".to_string(),
            metadata,
            created_at: 1000,
        };
        assert_eq!(msg.metadata, "{}");
    }

    #[test]
    fn test_message_long_content() {
        let long_content = "A".repeat(10_000);
        let msg = Message {
            id: "msg_long".to_string(),
            session_id: "sess_long".to_string(),
            sender_id: "usr_long".to_string(),
            content: long_content.clone(),
            content_type: "text".to_string(),
            metadata: "{}".to_string(),
            created_at: 2000,
        };
        assert_eq!(msg.content.len(), 10_000);
    }

    #[test]
    fn test_message_special_chars_in_content() {
        let content = "Hello\nWorld\twith\u{0000}null and emoji 🎉".to_string();
        let msg = Message {
            id: "msg_special".to_string(),
            session_id: "sess_special".to_string(),
            sender_id: "usr_special".to_string(),
            content: content.clone(),
            content_type: "text".to_string(),
            metadata: r#"{"chars":"special"}"#.to_string(),
            created_at: 3000,
        };
        assert!(msg.content.contains('\n'));
        assert!(msg.content.contains("🎉"));
    }

    #[test]
    fn test_message_session_id_linking() {
        let session_id = "sess_main_001".to_string();
        let msg1 = Message {
            id: "msg_100".to_string(),
            session_id: session_id.clone(),
            sender_id: "usr_001".to_string(),
            content: "First".to_string(),
            content_type: "text".to_string(),
            metadata: "{}".to_string(),
            created_at: 100,
        };
        let msg2 = Message {
            id: "msg_101".to_string(),
            session_id: session_id.clone(),
            sender_id: "usr_002".to_string(),
            content: "Second".to_string(),
            content_type: "text".to_string(),
            metadata: "{}".to_string(),
            created_at: 200,
        };
        assert_eq!(msg1.session_id, "sess_main_001");
        assert_eq!(msg2.session_id, "sess_main_001");
        // Both messages belong to the same session
        assert_eq!(msg1.session_id, msg2.session_id);
    }
}
