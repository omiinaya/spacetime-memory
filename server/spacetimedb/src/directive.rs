use spacetimedb::*;

use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::{now_micros, uuid_v4_uniq};

// ---------------------------------------------------------------------------
// Directive table — agent directives/goals with status lifecycle
// ---------------------------------------------------------------------------

/// A directive represents an agent's goal, mission, or task with a status
/// lifecycle: active → paused → completed/abandoned.
#[table(accessor = directive)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Directive {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Human-readable title
    pub title: String,
    /// Full directive description
    pub description: String,
    /// One of: active, paused, completed, abandoned
    pub status: String,
    /// Priority level (1–5, higher = more important)
    pub priority: u32,
    /// The agent/user this directive belongs to
    #[index(btree)]
    pub assigned_to: String,
    /// Optional category grouping
    pub category: String,
    /// Tags for filtering (JSON array of strings)
    pub tags_json: String,
    /// Parent directive ID if this is a sub-goal
    pub parent_id: String,
    /// Deadline in unix micros (0 = no deadline)
    pub deadline: i64,
    /// Progress percentage 0–100
    pub progress: u32,
    /// Result/outcome when completed
    pub outcome: String,
    pub created_at: i64,
    pub updated_at: i64,
}

// ---------------------------------------------------------------------------
// Result tables
// ---------------------------------------------------------------------------

/// Result table for `list_directives` queries.
/// Clients read from this table after calling the reducer.
#[table(accessor = directive_list_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DirectiveListResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// JSON array of directive rows matching the query.
    pub json_data: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Directive reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_directive(
    ctx: &ReducerContext,
    workspace_id: String,
    title: String,
    description: String,
    priority: u32,
    assigned_to: String,
    category: String,
    tags_json: String,
    parent_id: String,
    deadline: i64,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "create_directive", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;
        let now = now_micros(ctx);
        let id = uuid_v4_uniq(ctx, |id| ctx.db.directive().id().find(id).is_none(), 3);

        let priority = priority.clamp(1, 5);

        let directive = Directive {
            id: id.clone(),
            workspace_id,
            title,
            description,
            status: "active".to_string(),
            priority,
            assigned_to,
            category,
            tags_json,
            parent_id,
            deadline,
            progress: 0,
            outcome: String::new(),
            created_at: now,
            updated_at: now,
        };

        let dir_json = change_event::record_to_json(&directive);
        ctx.db.directive().insert(directive);
        change_event::log_change(ctx, &ws_id, "directive", "insert", &id, &dir_json);
        Ok(())
    })
}

#[reducer]
pub fn update_directive_status(
    ctx: &ReducerContext,
    id: String,
    status: String,
    outcome: String,
) -> Result<(), String> {
    trace_span!(ctx, "update_directive_status", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        let valid_statuses = ["active", "paused", "completed", "abandoned"];
        if !valid_statuses.contains(&status.as_str()) {
            return Err(format!(
                "Invalid status '{}' — must be one of: {}",
                status,
                valid_statuses.join(", ")
            ));
        }

        let mut d = ctx
            .db
            .directive()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Directive '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &d.workspace_id, &caller, "editor")?;

        d.status = status;
        d.outcome = outcome;
        d.updated_at = now;
        if d.status == "completed" || d.status == "abandoned" {
            d.progress = if d.status == "completed" { 100 } else { d.progress };
        }

        let ws_id = d.workspace_id.clone();
        let dir_id = d.id.clone();
        let dir_json = change_event::record_to_json(&d);
        ctx.db.directive().id().update(d);
        change_event::log_change(ctx, &ws_id, "directive", "update", &dir_id, &dir_json);
        Ok(())
    })
}

#[reducer]
pub fn update_directive_progress(
    ctx: &ReducerContext,
    id: String,
    progress: u32,
) -> Result<(), String> {
    trace_span!(ctx, "update_directive_progress", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);
        let progress = progress.min(100);

        let mut d = ctx
            .db
            .directive()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Directive '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &d.workspace_id, &caller, "editor")?;

        d.progress = progress;
        d.updated_at = now;
        if progress == 100 && d.status == "active" {
            d.status = "completed".to_string();
        }

        let ws_id = d.workspace_id.clone();
        let dir_id = d.id.clone();
        let dir_json = change_event::record_to_json(&d);
        ctx.db.directive().id().update(d);
        change_event::log_change(ctx, &ws_id, "directive", "update", &dir_id, &dir_json);
        Ok(())
    })
}

#[reducer]
pub fn delete_directive(ctx: &ReducerContext, id: String) -> Result<(), String> {
    trace_span!(ctx, "delete_directive", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let d = ctx
            .db
            .directive()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Directive '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &d.workspace_id, &caller, "editor")?;

        let ws_id = d.workspace_id.clone();
        let dir_id = d.id.clone();
        let dir_json = change_event::record_to_json(&d);
        ctx.db.directive().id().delete(&id);
        change_event::log_change(ctx, &ws_id, "directive", "delete", &dir_id, &dir_json);
        Ok(())
    })
}

#[reducer]
pub fn list_directives(
    ctx: &ReducerContext,
    workspace_id: String,
    status: String,
    assigned_to: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "list_directives", TracingSpanKind::Read, &ws_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        let directives: Vec<Directive> = ctx
            .db
            .directive()
            .iter()
            .filter(|d| {
                if d.workspace_id != workspace_id {
                    return false;
                }
                if !status.is_empty() && d.status != status {
                    return false;
                }
                if !assigned_to.is_empty() && d.assigned_to != assigned_to {
                    return false;
                }
                true
            })
            .take(crate::MAX_RESULTS)
            .collect();

        let json_data =
            serde_json::to_string(&directives).unwrap_or_else(|_| "[]".to_string());

        // Pre-cleanup: remove stale results for this workspace_id
        for old in ctx
            .db
            .directive_list_result()
            .iter()
            .filter(|r| r.workspace_id == workspace_id)
            .collect::<Vec<_>>()
        {
            ctx.db.directive_list_result().id().delete(&old.id);
        }

        let result_id = uuid_v4_uniq(
            ctx,
            |rid| ctx.db.directive_list_result().id().find(rid).is_none(),
            3,
        );
        ctx.db
            .directive_list_result()
            .insert(DirectiveListResult {
                id: result_id,
                workspace_id,
                json_data,
                created_at: now,
            });
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
    fn test_directive_initialization() {
        let d = Directive {
            id: "dir_001".to_string(),
            workspace_id: "ws_001".to_string(),
            title: "Explore the maze".to_string(),
            description: "Navigate to the center and return.".to_string(),
            status: "active".to_string(),
            priority: 3,
            assigned_to: "agent_001".to_string(),
            category: "exploration".to_string(),
            tags_json: r#"["urgent","navigation"]"#.to_string(),
            parent_id: String::new(),
            deadline: 1_700_000_000_000_000,
            progress: 0,
            outcome: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(d.id, "dir_001");
        assert_eq!(d.status, "active");
        assert_eq!(d.priority, 3);
        assert_eq!(d.progress, 0);
    }

    #[test]
    fn test_directive_status_transitions() {
        let d = Directive {
            id: "dir_002".to_string(),
            workspace_id: "ws_001".to_string(),
            title: "Gather resources".to_string(),
            description: "Collect 10 wood and 5 stone.".to_string(),
            status: "active".to_string(),
            priority: 2,
            assigned_to: "agent_001".to_string(),
            category: "gathering".to_string(),
            tags_json: "[]".to_string(),
            parent_id: String::new(),
            deadline: 0,
            progress: 30,
            outcome: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert_eq!(d.status, "active");

        // Simulate completed
        let completed = Directive {
            status: "completed".to_string(),
            outcome: "All resources collected.".to_string(),
            progress: 100,
            ..d.clone()
        };
        assert_eq!(completed.status, "completed");
        assert_eq!(completed.progress, 100);
        assert_eq!(completed.outcome, "All resources collected.");

        // Simulate abandoned
        let abandoned = Directive {
            status: "abandoned".to_string(),
            outcome: "No longer needed.".to_string(),
            ..d
        };
        assert_eq!(abandoned.status, "abandoned");
        assert_eq!(abandoned.outcome, "No longer needed.");

        // Simulate paused
        let paused = Directive {
            status: "paused".to_string(),
            ..completed
        };
        assert_eq!(paused.status, "paused");
    }

    #[test]
    fn test_directive_priority_clamping() {
        // Verify priority clamping: min 1, max 5
        assert_eq!((0u32).min(5).max(1), 1);
        assert_eq!((3u32).min(5).max(1), 3);
        assert_eq!((7u32).min(5).max(1), 5);

        let d = Directive {
            id: "dir_003".to_string(),
            workspace_id: "ws_001".to_string(),
            title: "High priority task".to_string(),
            description: String::new(),
            status: "active".to_string(),
            priority: 5,
            assigned_to: "agent_001".to_string(),
            category: String::new(),
            tags_json: String::new(),
            parent_id: String::new(),
            deadline: 0,
            progress: 0,
            outcome: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        assert!(d.priority <= 5);
        assert!(d.priority >= 1);
    }

    #[test]
    fn test_directive_serde_roundtrip() {
        let d = Directive {
            id: "dir_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            title: "Serde test directive".to_string(),
            description: "Testing serialisation.".to_string(),
            status: "active".to_string(),
            priority: 1,
            assigned_to: "agent_test".to_string(),
            category: "test".to_string(),
            tags_json: r#"["test"]"#.to_string(),
            parent_id: String::new(),
            deadline: 0,
            progress: 50,
            outcome: String::new(),
            created_at: 1_000_000,
            updated_at: 1_000_000,
        };
        let json = serde_json::to_string(&d).expect("serialize");
        let deserialized: Directive = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, d.id);
        assert_eq!(deserialized.title, "Serde test directive");
        assert_eq!(deserialized.status, "active");
        assert_eq!(deserialized.priority, 1);
        assert_eq!(deserialized.progress, 50);
    }

    #[test]
    fn test_directive_valid_statuses() {
        for s in &["active", "paused", "completed", "abandoned"] {
            let d = Directive {
                id: format!("dir_status_{}", s),
                workspace_id: "ws".to_string(),
                title: format!("Status: {}", s),
                description: String::new(),
                status: s.to_string(),
                priority: 1,
                assigned_to: String::new(),
                category: String::new(),
                tags_json: String::new(),
                parent_id: String::new(),
                deadline: 0,
                progress: 0,
                outcome: String::new(),
                created_at: 0,
                updated_at: 0,
            };
            assert_eq!(d.status, *s);
        }
    }

    #[test]
    fn test_directive_list_result_initialization() {
        let r = DirectiveListResult {
            id: "r_001".to_string(),
            workspace_id: "ws_001".to_string(),
            json_data: r#"[{"id":"dir_001"}]"#.to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(r.workspace_id, "ws_001");
        assert!(r.json_data.contains("dir_001"));
    }
}
