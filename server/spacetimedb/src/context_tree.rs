use spacetimedb::*;

use crate::{now_micros, uuid_v4_uniq};
#[allow(unused_imports)]
use crate::auth::{require_auth, require_admin};
use crate::workspace::check_space_access;
use crate::trace_span;
use crate::tracing::TracingSpanKind;
use crate::change_event;

// ---------------------------------------------------------------------------
// ContextTree table
// ---------------------------------------------------------------------------

/// A hierarchical context entry supporting path-prefix matching for
/// contextual retrieval. Each entry maps a path (e.g. "/api/v2") to
/// a context text block, with priority for specificity ranking.
///
/// The (workspace_id, path) pair is unique per workspace, enforced via
/// upsert logic in `set_context`. Both fields carry individual btree
/// indexes for efficient composite lookups.
#[table(accessor = context_tree)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ContextTree {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Hierarchical path, e.g. "/api/v2" or "/user/preferences".
    /// Combined with workspace_id for unique identification of a context entry.
    #[index(btree)]
    pub path: String,
    /// The context text content — descriptive guidance for this path.
    pub content: String,
    /// Priority score; higher values indicate more specific/relevant contexts.
    /// Used for ranking when multiple paths match a given query path.
    pub priority: f64,
    /// Whether this context is global (applies across all paths).
    /// Global contexts are matched regardless of path prefix.
    pub is_global: bool,
    pub created_at: i64,
    pub updated_at: i64,
    /// Identity of the caller that created this entry.
    pub created_by: String,
}

// ---------------------------------------------------------------------------
// ContextTreeResult table
// ---------------------------------------------------------------------------

/// Result table for `list_contexts` and `resolve_context` queries.
/// Clients read from this table after calling the reducer.
#[table(accessor = context_tree_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ContextTreeResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Identifies the query that produced this result.
    /// For `list_contexts` this is "list"; for `resolve_context` this
    /// is the input path that was resolved.
    pub query_id: String,
    /// JSON array of matched context entries.
    pub results_json: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/// Generate all ancestor path prefixes for a given path, including the
/// path itself and the root "/".
///
/// # Examples
///
/// ```
/// assert_eq!(
///     path_prefixes("/api/v2/users/123"),
///     vec!["/api/v2/users/123", "/api/v2/users", "/api/v2", "/api", "/"]
/// );
/// assert_eq!(
///     path_prefixes("/"),
///     vec!["/"]
/// );
/// ```
#[allow(dead_code)]
fn path_prefixes(path: &str) -> Vec<String> {
    let mut prefixes = Vec::new();
    let trimmed = path.trim_end_matches('/');

    if trimmed.is_empty() || trimmed == "/" {
        prefixes.push("/".to_string());
        return prefixes;
    }

    // Collect path segments
    let segments: Vec<&str> = trimmed.split('/').filter(|s| !s.is_empty()).collect();

    // Build prefixes from longest to shortest
    for end in (1..=segments.len()).rev() {
        let prefix = format!("/{}", segments[..end].join("/"));
        prefixes.push(prefix);
    }

    // Always include root
    if prefixes.last().map(|p| p.as_str()) != Some("/") {
        prefixes.push("/".to_string());
    }

    prefixes
}

/// Check whether `candidate` is a path prefix of `target`.
///
/// Both paths are normalised: trailing slashes are stripped, then
/// `candidate` is compared segment-by-segment against the start of `target`.
fn is_path_prefix(candidate: &str, target: &str) -> bool {
    let c = candidate.trim_end_matches('/');
    let t = target.trim_end_matches('/');

    if c.is_empty() || c == "/" {
        return true; // root matches everything
    }

    let c_segments: Vec<&str> = c.split('/').filter(|s| !s.is_empty()).collect();
    let t_segments: Vec<&str> = t.split('/').filter(|s| !s.is_empty()).collect();

    if c_segments.len() > t_segments.len() {
        return false;
    }

    c_segments.iter().zip(t_segments.iter()).all(|(a, b)| a == b)
}

// ---------------------------------------------------------------------------
// ContextTree reducers
// ---------------------------------------------------------------------------

/// Create or update a context entry for the given workspace and path.
///
/// If a context already exists for this (workspace_id, path) pair, it is
/// updated in-place (upsert). Otherwise a new entry is inserted.
#[reducer]
pub fn set_context(
    ctx: &ReducerContext,
    workspace_id: String,
    path: String,
    content: String,
    priority: f64,
    is_global: bool,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "set_context", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        // Upsert: find existing entry for this (workspace_id, path) combo
        let existing: Option<ContextTree> = ctx
            .db
            .context_tree()
            .iter()
            .take(crate::MAX_RESULTS)
            .find(|ct| ct.workspace_id == ws_id && ct.path == path);

        if let Some(mut existing) = existing {
            // Update existing entry
            existing.content = content;
            existing.priority = priority;
            existing.is_global = is_global;
            existing.updated_at = now;
            existing.created_by = caller.to_string();

            let entry_id = existing.id.clone();
            let entry_json = change_event::record_to_json(&existing);
            ctx.db.context_tree().id().update(existing);
            change_event::log_change(ctx, &ws_id, "context_tree", "update", &entry_id, &entry_json);
            Ok(())
        } else {
            // Insert new entry
            let id = uuid_v4_uniq(ctx, |id| ctx.db.context_tree().id().find(id).is_none(), 3);

            let entry = ContextTree {
                id: id.clone(),
                workspace_id,
                path,
                content,
                priority,
                is_global,
                created_at: now,
                updated_at: now,
                created_by: caller.to_string(),
            };

            let entry_json = change_event::record_to_json(&entry);
            ctx.db.context_tree().insert(entry);
            change_event::log_change(ctx, &ws_id, "context_tree", "insert", &id, &entry_json);
            Ok(())
        }
    })
}

/// Delete a context entry by its primary key id.
#[reducer]
pub fn delete_context(ctx: &ReducerContext, context_id: String) -> Result<(), String> {
    trace_span!(ctx, "delete_context", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let entry = ctx
            .db
            .context_tree()
            .id()
            .find(&context_id)
            .ok_or_else(|| format!("ContextTree '{}' not found", context_id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &entry.workspace_id, &caller, "editor")?;

        let ws_id = entry.workspace_id.clone();
        let entry_id = entry.id.clone();
        let entry_json = change_event::record_to_json(&entry);
        ctx.db.context_tree().id().delete(&context_id);
        change_event::log_change(ctx, &ws_id, "context_tree", "delete", &entry_id, &entry_json);
        Ok(())
    })
}

/// List all context entries for a given workspace.
///
/// Results are stored in `context_tree_result` with query_id = "list".
#[reducer]
pub fn list_contexts(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "list_contexts", TracingSpanKind::Read, &ws_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        let entries: Vec<ContextTree> = ctx
            .db
            .context_tree()
            .workspace_id()
            .filter(&workspace_id)
            .take(crate::MAX_RESULTS)
            .collect();

        let results_json = serde_json::to_string(&entries).unwrap_or_else(|_| "[]".to_string());

        // Pre-cleanup: remove stale results for this workspace_id + query_id "list"
        for old in ctx
            .db
            .context_tree_result()
            .iter()
            .filter(|r| r.workspace_id == workspace_id && r.query_id == "list")
            .collect::<Vec<_>>()
        {
            ctx.db.context_tree_result().id().delete(&old.id);
        }

        let result_id = uuid_v4_uniq(
            ctx,
            |rid| ctx.db.context_tree_result().id().find(rid).is_none(),
            3,
        );
        ctx.db.context_tree_result().insert(ContextTreeResult {
            id: result_id,
            workspace_id,
            query_id: "list".to_string(),
            results_json,
            created_at: now,
        });
        Ok(())
    })
}

/// Resolve the most specific context entries for a given path using
/// hierarchical prefix matching.
///
/// Given a path like "/api/v2/users/123", this reducer finds all contexts
/// whose path is a prefix of the input path (including the exact match
/// and the root "/"), ranks them by specificity (longest prefix wins)
/// and then by priority (higher = better), and stores the result in
/// `context_tree_result` with query_id = the input path.
#[reducer]
pub fn resolve_context(
    ctx: &ReducerContext,
    workspace_id: String,
    path: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "resolve_context", TracingSpanKind::Read, &ws_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);

        // Collect all contexts for this workspace
        let all_entries: Vec<ContextTree> = ctx
            .db
            .context_tree()
            .workspace_id()
            .filter(&workspace_id)
            .take(crate::MAX_RESULTS)
            .collect();

        // Filter to those that are global or match the path prefix
        let mut matched: Vec<&ContextTree> = all_entries
            .iter()
            .filter(|ct| ct.is_global || is_path_prefix(&ct.path, &path))
            .collect();

        // Sort by specificity (longest path first), then by priority (highest first)
        matched.sort_by(|a, b| {
            b.path
                .len()
                .cmp(&a.path.len())
                .then_with(|| b.priority.partial_cmp(&a.priority).unwrap_or(std::cmp::Ordering::Equal))
        });

        let results_json =
            serde_json::to_string(&matched).unwrap_or_else(|_| "[]".to_string());

        // Pre-cleanup: remove stale results for this workspace_id + query_id (the input path)
        for old in ctx
            .db
            .context_tree_result()
            .iter()
            .filter(|r| r.workspace_id == workspace_id && r.query_id == path)
            .collect::<Vec<_>>()
        {
            ctx.db.context_tree_result().id().delete(&old.id);
        }

        let result_id = uuid_v4_uniq(
            ctx,
            |rid| ctx.db.context_tree_result().id().find(rid).is_none(),
            3,
        );
        ctx.db.context_tree_result().insert(ContextTreeResult {
            id: result_id,
            workspace_id,
            query_id: path,
            results_json,
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

    // ---- path_prefixes ----

    #[test]
    fn test_path_prefixes_root() {
        let prefixes = path_prefixes("/");
        assert_eq!(prefixes, vec!["/".to_string()]);
    }

    #[test]
    fn test_path_prefixes_single_segment() {
        let prefixes = path_prefixes("/api");
        assert_eq!(prefixes, vec!["/api".to_string(), "/".to_string()]);
    }

    #[test]
    fn test_path_prefixes_multi_segment() {
        let prefixes = path_prefixes("/api/v2/users/123");
        let expected = vec![
            "/api/v2/users/123".to_string(),
            "/api/v2/users".to_string(),
            "/api/v2".to_string(),
            "/api".to_string(),
            "/".to_string(),
        ];
        assert_eq!(prefixes, expected);
    }

    #[test]
    fn test_path_prefixes_with_trailing_slash() {
        let prefixes = path_prefixes("/api/v2/");
        let expected = vec!["/api/v2".to_string(), "/api".to_string(), "/".to_string()];
        assert_eq!(prefixes, expected);
    }

    #[test]
    fn test_path_prefixes_deep() {
        let prefixes = path_prefixes("/a/b/c/d/e");
        let expected = vec![
            "/a/b/c/d/e".to_string(),
            "/a/b/c/d".to_string(),
            "/a/b/c".to_string(),
            "/a/b".to_string(),
            "/a".to_string(),
            "/".to_string(),
        ];
        assert_eq!(prefixes, expected);
    }

    // ---- is_path_prefix ----

    #[test]
    fn test_is_path_prefix_root_matches_everything() {
        assert!(is_path_prefix("/", "/api/v2"));
        assert!(is_path_prefix("/", "/"));
        assert!(is_path_prefix("/", "/a"));
    }

    #[test]
    fn test_is_path_prefix_exact_match() {
        assert!(is_path_prefix("/api/v2", "/api/v2"));
    }

    #[test]
    fn test_is_path_prefix_valid_prefix() {
        assert!(is_path_prefix("/api", "/api/v2/users"));
        assert!(is_path_prefix("/api/v2", "/api/v2/users/123"));
    }

    #[test]
    fn test_is_path_prefix_not_a_prefix() {
        assert!(!is_path_prefix("/api/v3", "/api/v2/users"));
        assert!(!is_path_prefix("/users", "/api/v2"));
    }

    #[test]
    fn test_is_path_prefix_candidate_longer_than_target() {
        assert!(!is_path_prefix("/api/v2/users/extra", "/api/v2"));
    }

    #[test]
    fn test_is_path_prefix_trailing_slash_handling() {
        assert!(is_path_prefix("/api/", "/api/v2"));
        assert!(is_path_prefix("/api", "/api/v2/"));
    }

    #[test]
    fn test_is_path_prefix_empty_paths() {
        assert!(is_path_prefix("", ""));
        assert!(is_path_prefix("/", ""));
        assert!(is_path_prefix("", "/a"));
    }

    // ---- ContextTree initialization ----

    #[test]
    fn test_context_tree_initialization() {
        let entry = ContextTree {
            id: "ctx_001".to_string(),
            workspace_id: "ws_001".to_string(),
            path: "/api/v2".to_string(),
            content: "API v2 context: rate limiting applies.".to_string(),
            priority: 1.0,
            is_global: false,
            created_at: 1_000_000,
            updated_at: 1_000_000,
            created_by: "user_abc".to_string(),
        };
        assert_eq!(entry.id, "ctx_001");
        assert_eq!(entry.workspace_id, "ws_001");
        assert_eq!(entry.path, "/api/v2");
        assert_eq!(entry.content, "API v2 context: rate limiting applies.");
        assert!((entry.priority - 1.0).abs() < f64::EPSILON);
        assert!(!entry.is_global);
        assert_eq!(entry.created_by, "user_abc");
    }

    #[test]
    fn test_context_tree_global_flag() {
        let global = ContextTree {
            id: "ctx_global".to_string(),
            workspace_id: "ws_001".to_string(),
            path: "/".to_string(),
            content: "Global fallback context.".to_string(),
            priority: 0.0,
            is_global: true,
            created_at: 0,
            updated_at: 0,
            created_by: "admin".to_string(),
        };
        assert!(global.is_global);
    }

    #[test]
    fn test_context_tree_serde_roundtrip() {
        let entry = ContextTree {
            id: "ctx_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            path: "/user/preferences".to_string(),
            content: "User preference context.".to_string(),
            priority: 2.5,
            is_global: false,
            created_at: 2_000_000,
            updated_at: 2_000_000,
            created_by: "user_xyz".to_string(),
        };
        let json = serde_json::to_string(&entry).expect("serialize");
        let deserialized: ContextTree = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, entry.id);
        assert_eq!(deserialized.workspace_id, entry.workspace_id);
        assert_eq!(deserialized.path, entry.path);
        assert_eq!(deserialized.content, entry.content);
        assert!((deserialized.priority - entry.priority).abs() < f64::EPSILON);
        assert_eq!(deserialized.is_global, entry.is_global);
        assert_eq!(deserialized.created_by, entry.created_by);
    }

    // ---- ContextTreeResult initialization ----

    #[test]
    fn test_context_tree_result_initialization() {
        let result = ContextTreeResult {
            id: "res_001".to_string(),
            workspace_id: "ws_001".to_string(),
            query_id: "list".to_string(),
            results_json: r#"[]"#.to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(result.id, "res_001");
        assert_eq!(result.query_id, "list");
        assert_eq!(result.results_json, "[]");
    }

    // ---- Context matching logic ----

    #[test]
    fn test_path_prefix_matching_most_specific_wins() {
        // Simulate the matching logic: contexts defined at various paths
        let contexts = vec![
            ContextTree {
                id: "root".to_string(),
                workspace_id: "ws".to_string(),
                path: "/".to_string(),
                content: "Root context".to_string(),
                priority: 0.0,
                is_global: false,
                created_at: 0,
                updated_at: 0,
                created_by: "u".to_string(),
            },
            ContextTree {
                id: "api".to_string(),
                workspace_id: "ws".to_string(),
                path: "/api".to_string(),
                content: "API context".to_string(),
                priority: 1.0,
                is_global: false,
                created_at: 0,
                updated_at: 0,
                created_by: "u".to_string(),
            },
            ContextTree {
                id: "api_v2".to_string(),
                workspace_id: "ws".to_string(),
                path: "/api/v2".to_string(),
                content: "API v2 context".to_string(),
                priority: 1.0,
                is_global: false,
                created_at: 0,
                updated_at: 0,
                created_by: "u".to_string(),
            },
        ];

        let target = "/api/v2/users/123";

        let mut matched: Vec<&ContextTree> = contexts
            .iter()
            .filter(|ct| ct.is_global || is_path_prefix(&ct.path, target))
            .collect();

        // Sort by specificity (longest path first), then priority
        matched.sort_by(|a, b| {
            b.path
                .len()
                .cmp(&a.path.len())
                .then_with(|| b.priority.partial_cmp(&a.priority).unwrap_or(std::cmp::Ordering::Equal))
        });

        assert_eq!(matched.len(), 3);
        assert_eq!(matched[0].id, "api_v2"); // most specific
        assert_eq!(matched[1].id, "api");
        assert_eq!(matched[2].id, "root"); // least specific
    }

    #[test]
    fn test_path_prefix_matching_priority_tiebreak() {
        let contexts = vec![
            ContextTree {
                id: "low".to_string(),
                workspace_id: "ws".to_string(),
                path: "/api".to_string(),
                content: "Low priority".to_string(),
                priority: 0.5,
                is_global: false,
                created_at: 0,
                updated_at: 0,
                created_by: "u".to_string(),
            },
            ContextTree {
                id: "high".to_string(),
                workspace_id: "ws".to_string(),
                path: "/api".to_string(),
                content: "High priority".to_string(),
                priority: 2.0,
                is_global: false,
                created_at: 0,
                updated_at: 0,
                created_by: "u".to_string(),
            },
        ];

        let target = "/api/v2";

        let mut matched: Vec<&ContextTree> = contexts
            .iter()
            .filter(|ct| ct.is_global || is_path_prefix(&ct.path, target))
            .collect();

        matched.sort_by(|a, b| {
            b.path
                .len()
                .cmp(&a.path.len())
                .then_with(|| b.priority.partial_cmp(&a.priority).unwrap_or(std::cmp::Ordering::Equal))
        });

        assert_eq!(matched.len(), 2);
        assert_eq!(matched[0].id, "high"); // same length, higher priority first
        assert_eq!(matched[1].id, "low");
    }

    #[test]
    fn test_path_prefix_matching_global_context() {
        let contexts = vec![
            ContextTree {
                id: "specific".to_string(),
                workspace_id: "ws".to_string(),
                path: "/api".to_string(),
                content: "API context".to_string(),
                priority: 1.0,
                is_global: false,
                created_at: 0,
                updated_at: 0,
                created_by: "u".to_string(),
            },
            ContextTree {
                id: "global_ctx".to_string(),
                workspace_id: "ws".to_string(),
                path: "/unrelated".to_string(),
                content: "Global context".to_string(),
                priority: 0.5,
                is_global: true,
                created_at: 0,
                updated_at: 0,
                created_by: "u".to_string(),
            },
        ];

        let target = "/api/v2";

        let matched: Vec<&ContextTree> = contexts
            .iter()
            .filter(|ct| ct.is_global || is_path_prefix(&ct.path, target))
            .collect();

        assert_eq!(matched.len(), 2);
        // Both match: "specific" via path prefix, "global_ctx" via is_global
    }

    #[test]
    fn test_path_prefix_matching_no_match() {
        let contexts = vec![ContextTree {
            id: "unrelated".to_string(),
            workspace_id: "ws".to_string(),
            path: "/something/else".to_string(),
            content: "Unrelated".to_string(),
            priority: 1.0,
            is_global: false,
            created_at: 0,
            updated_at: 0,
            created_by: "u".to_string(),
        }];

        let target = "/api/v2";

        let matched: Vec<&ContextTree> = contexts
            .iter()
            .filter(|ct| ct.is_global || is_path_prefix(&ct.path, target))
            .collect();

        assert!(matched.is_empty());
    }
}
