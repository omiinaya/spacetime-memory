use spacetimedb::*;

use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::change_event;
use crate::tracing::TracingSpanKind;
use crate::trace_span;
use crate::memory::memory;
use crate::{now_micros, uuid_v4_uniq};

// ---------------------------------------------------------------------------
// Reasoning tier — formal tier system for agent reasoning depth
// ---------------------------------------------------------------------------

/// A reasoning tier defines constraints for agent reasoning depth.
/// Inspired by Honcho's tier system: quick, balanced, deep, research.
#[table(accessor = reasoning_tier)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ReasoningTier {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Tier name: "quick", "balanced", "deep", "research"
    pub name: String,
    /// Human-readable description of what this tier does
    pub description: String,
    /// Max tokens for this tier
    pub max_tokens: u32,
    /// LLM temperature setting (0.0–2.0)
    pub temperature: f64,
    /// Nucleus sampling parameter (0.0–1.0)
    pub top_p: f64,
    /// How many memories to retrieve for context
    pub max_context_memories: u32,
    /// Minimum confidence threshold for included memories (0.0–1.0)
    pub min_confidence: f64,
    /// Whether reflection/post-processing is required
    pub requires_reflection: bool,
    /// Whether knowledge graph traversal is used
    pub requires_graph_traversal: bool,
    /// Priority (lower = more important)
    pub priority: u32,
    /// Whether this is the default tier for the workspace
    pub is_default: bool,
    pub created_at: i64,
    pub updated_at: i64,
}

// ---------------------------------------------------------------------------
// Result tables
// ---------------------------------------------------------------------------

/// Result table for `get_reasoning_tiers` queries.
#[table(accessor = reasoning_tier_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ReasoningTierResult {
    #[primary_key]
    pub result_id: String,
    /// JSON data payload
    pub data: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_reasoning_tier(
    ctx: &ReducerContext,
    workspace_id: String,
    _peer_id: String,
    name: String,
    description: String,
    max_tokens: u32,
    temperature: f64,
    top_p: f64,
    max_context_memories: u32,
    min_confidence: f64,
    requires_reflection: bool,
    requires_graph_traversal: bool,
    priority: u32,
    is_default: bool,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "create_reasoning_tier", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        // Validate parameters
        if max_tokens == 0 {
            return Err("max_tokens must be > 0".to_string());
        }
        if !(0.0..=2.0).contains(&temperature) {
            return Err("temperature must be between 0.0 and 2.0".to_string());
        }
        if !(0.0..=1.0).contains(&top_p) {
            return Err("top_p must be between 0.0 and 1.0".to_string());
        }
        if max_context_memories == 0 {
            return Err("max_context_memories must be > 0".to_string());
        }
        if !(0.0..=1.0).contains(&min_confidence) {
            return Err("min_confidence must be between 0.0 and 1.0".to_string());
        }

        // If this tier is set as default, unset any existing default
        if is_default {
            for tier in ctx.db.reasoning_tier().iter() {
                if tier.workspace_id == workspace_id && tier.is_default {
                    let mut updated = tier.clone();
                    updated.is_default = false;
                    ctx.db.reasoning_tier().id().update(updated);
                }
            }
        }

        let now = now_micros(ctx);
        let id = uuid_v4_uniq(ctx, |id| ctx.db.reasoning_tier().id().find(id).is_none(), 3);

        let tier = ReasoningTier {
            id: id.clone(),
            workspace_id: workspace_id.clone(),
            name,
            description,
            max_tokens,
            temperature,
            top_p,
            max_context_memories,
            min_confidence,
            requires_reflection,
            requires_graph_traversal,
            priority,
            is_default,
            created_at: now,
            updated_at: now,
        };

        let tier_json = change_event::record_to_json(&tier);
        ctx.db.reasoning_tier().insert(tier);
        change_event::log_change(ctx, &ws_id, "reasoning_tier", "insert", &id, &tier_json);
        Ok(())
    })
}

#[reducer]
pub fn update_reasoning_tier(
    ctx: &ReducerContext,
    workspace_id: String,
    tier_id: String,
    name: String,
    description: String,
    max_tokens: u32,
    temperature: f64,
    top_p: f64,
    max_context_memories: u32,
    min_confidence: f64,
    requires_reflection: bool,
    requires_graph_traversal: bool,
    priority: u32,
    is_default: bool,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "update_reasoning_tier", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        let mut existing = ctx.db.reasoning_tier().id().find(&tier_id)
            .ok_or_else(|| "Reasoning tier not found".to_string())?;

        if existing.workspace_id != workspace_id {
            return Err("Reasoning tier not found in this workspace".to_string());
        }

        // Validate parameters
        if max_tokens == 0 {
            return Err("max_tokens must be > 0".to_string());
        }
        if !(0.0..=2.0).contains(&temperature) {
            return Err("temperature must be between 0.0 and 2.0".to_string());
        }
        if !(0.0..=1.0).contains(&top_p) {
            return Err("top_p must be between 0.0 and 1.0".to_string());
        }
        if max_context_memories == 0 {
            return Err("max_context_memories must be > 0".to_string());
        }
        if !(0.0..=1.0).contains(&min_confidence) {
            return Err("min_confidence must be between 0.0 and 1.0".to_string());
        }

        // If setting as default, unset any existing default
        if is_default {
            for tier in ctx.db.reasoning_tier().iter() {
                if tier.workspace_id == workspace_id && tier.is_default && tier.id != tier_id {
                    let mut updated = tier.clone();
                    updated.is_default = false;
                    ctx.db.reasoning_tier().id().update(updated);
                }
            }
        }

        let now = now_micros(ctx);
        existing.name = name;
        existing.description = description;
        existing.max_tokens = max_tokens;
        existing.temperature = temperature;
        existing.top_p = top_p;
        existing.max_context_memories = max_context_memories;
        existing.min_confidence = min_confidence;
        existing.requires_reflection = requires_reflection;
        existing.requires_graph_traversal = requires_graph_traversal;
        existing.priority = priority;
        existing.is_default = is_default;
        existing.updated_at = now;

        let tier_json = change_event::record_to_json(&existing);
        ctx.db.reasoning_tier().id().update(existing);
        change_event::log_change(ctx, &ws_id, "reasoning_tier", "update", &tier_id, &tier_json);
        Ok(())
    })
}

#[reducer]
pub fn delete_reasoning_tier(
    ctx: &ReducerContext,
    workspace_id: String,
    tier_id: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "delete_reasoning_tier", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        let existing = ctx.db.reasoning_tier().id().find(&tier_id)
            .ok_or_else(|| "Reasoning tier not found".to_string())?;

        if existing.workspace_id != workspace_id {
            return Err("Reasoning tier not found in this workspace".to_string());
        }

        let tier_json = change_event::record_to_json(&existing);
        ctx.db.reasoning_tier().id().delete(&tier_id);
        change_event::log_change(ctx, &ws_id, "reasoning_tier", "delete", &tier_id, &tier_json);
        Ok(())
    })
}

#[reducer]
pub fn get_reasoning_tiers(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_reasoning_tiers", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "viewer")?;

        let mut tiers: Vec<ReasoningTier> = ctx.db.reasoning_tier()
            .iter()
            .filter(|t| t.workspace_id == workspace_id)
            .collect();

        // Sort by priority (lower = more important first)
        tiers.sort_by_key(|a| a.priority);

        let data = serde_json::to_string(&tiers).unwrap_or_else(|_| "[]".to_string());
        let now = now_micros(ctx);
        let result_id = uuid_v4_uniq(ctx, |id| ctx.db.reasoning_tier_result().result_id().find(id).is_none(), 3);

        ctx.db.reasoning_tier_result().insert(ReasoningTierResult {
            result_id,
            data,
            created_at: now,
        });

        Ok(())
    })
}

#[reducer]
pub fn get_default_reasoning_tier(
    ctx: &ReducerContext,
    workspace_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_default_reasoning_tier", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "viewer")?;

        let default: Vec<ReasoningTier> = ctx.db.reasoning_tier()
            .iter()
            .filter(|t| t.workspace_id == workspace_id && t.is_default)
            .collect();

        let data = if default.is_empty() {
            // Return empty JSON
            "{}".to_string()
        } else {
            serde_json::to_string(&default[0]).unwrap_or_else(|_| "{}".to_string())
        };

        let now = now_micros(ctx);
        let result_id = uuid_v4_uniq(ctx, |id| ctx.db.reasoning_tier_result().result_id().find(id).is_none(), 3);

        ctx.db.reasoning_tier_result().insert(ReasoningTierResult {
            result_id,
            data,
            created_at: now,
        });

        Ok(())
    })
}

#[reducer]
pub fn set_default_tier(
    ctx: &ReducerContext,
    workspace_id: String,
    tier_id: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "set_default_tier", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        let existing = ctx.db.reasoning_tier().id().find(&tier_id)
            .ok_or_else(|| "Reasoning tier not found".to_string())?;

        if existing.workspace_id != workspace_id {
            return Err("Reasoning tier not found in this workspace".to_string());
        }

        // Unset any existing default for this workspace
        for tier in ctx.db.reasoning_tier().iter() {
            if tier.workspace_id == workspace_id && tier.is_default && tier.id != tier_id {
                let mut updated = tier.clone();
                updated.is_default = false;
                ctx.db.reasoning_tier().id().update(updated);
            }
        }

        // Set the new default
        let mut updated = existing.clone();
        updated.is_default = true;
        updated.updated_at = now_micros(ctx);
        ctx.db.reasoning_tier().id().update(updated);

        change_event::log_change(ctx, &ws_id, "reasoning_tier", "update", &tier_id, "{\"is_default\":true}");
        Ok(())
    })
}

#[reducer]
pub fn apply_reasoning_tier_to_memory(
    ctx: &ReducerContext,
    workspace_id: String,
    memory_id: String,
    tier_id: String,
) -> Result<(), String> {
    let ws_id = workspace_id.clone();
    trace_span!(ctx, "apply_reasoning_tier_to_memory", TracingSpanKind::Write, &ws_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        // Verify tier exists in this workspace
        let tier = ctx.db.reasoning_tier().id().find(&tier_id)
            .ok_or_else(|| "Reasoning tier not found".to_string())?;
        if tier.workspace_id != workspace_id {
            return Err("Reasoning tier not found in this workspace".to_string());
        }

        // Verify memory exists in this workspace
        let mem = ctx.db.memory().id().find(&memory_id)
            .ok_or_else(|| "Memory not found".to_string())?;
        if mem.workspace_id != workspace_id {
            return Err("Memory not found in this workspace".to_string());
        }

        // Tag the memory with the tier name
        let mut mem = mem.clone();
        mem.tier = tier.name.clone();
        ctx.db.memory().id().update(mem);

        let log_msg = format!("{{\"memory_id\":\"{}\",\"tier_id\":\"{}\",\"tier_name\":\"{}\"}}", memory_id, tier_id, tier.name);
        change_event::log_change(ctx, &ws_id, "reasoning_tier", "apply", &memory_id, &log_msg);
        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ----- Unit tests for validation logic -----

    #[test]
    fn test_validate_max_tokens_zero() {
        let result = validate_tier_params(0, 0.7, 0.9, 5, 0.5);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("max_tokens"));
    }

    #[test]
    fn test_validate_temperature_range_low() {
        let result = validate_tier_params(100, -0.1, 0.9, 5, 0.5);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("temperature"));
    }

    #[test]
    fn test_validate_temperature_range_high() {
        let result = validate_tier_params(100, 2.1, 0.9, 5, 0.5);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("temperature"));
    }

    #[test]
    fn test_validate_temperature_ok() {
        let result = validate_tier_params(100, 0.0, 0.9, 5, 0.5);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_temperature_max() {
        let result = validate_tier_params(100, 2.0, 0.9, 5, 0.5);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_top_p_range_low() {
        let result = validate_tier_params(100, 0.7, -0.1, 5, 0.5);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("top_p"));
    }

    #[test]
    fn test_validate_top_p_range_high() {
        let result = validate_tier_params(100, 0.7, 1.1, 5, 0.5);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("top_p"));
    }

    #[test]
    fn test_validate_max_context_memories_zero() {
        let result = validate_tier_params(100, 0.7, 0.9, 0, 0.5);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("max_context_memories"));
    }

    #[test]
    fn test_validate_min_confidence_range_low() {
        let result = validate_tier_params(100, 0.7, 0.9, 5, -0.1);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("min_confidence"));
    }

    #[test]
    fn test_validate_min_confidence_range_high() {
        let result = validate_tier_params(100, 0.7, 0.9, 5, 1.1);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("min_confidence"));
    }

    #[test]
    fn test_validate_all_ok() {
        let result = validate_tier_params(500, 0.7, 0.9, 20, 0.5);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_edge_ok() {
        // Edge values: temperature=0, top_p=0, min_confidence=0
        let result = validate_tier_params(1, 0.0, 0.0, 1, 0.0);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_all_max_ok() {
        // Max values: temperature=2.0, top_p=1.0, min_confidence=1.0
        let result = validate_tier_params(u32::MAX, 2.0, 1.0, u32::MAX, 1.0);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_priority_zero_ok() {
        let result = validate_tier_params(100, 0.7, 0.9, 5, 0.5);
        assert!(result.is_ok());
    }
}

#[allow(dead_code)]
/// Pure validation function for tier parameters (testable without STDB context).
fn validate_tier_params(
    max_tokens: u32,
    temperature: f64,
    top_p: f64,
    max_context_memories: u32,
    min_confidence: f64,
) -> Result<(), String> {
    if max_tokens == 0 {
        return Err("max_tokens must be > 0".to_string());
    }
    if !(0.0..=2.0).contains(&temperature) {
        return Err("temperature must be between 0.0 and 2.0".to_string());
    }
    if !(0.0..=1.0).contains(&top_p) {
        return Err("top_p must be between 0.0 and 1.0".to_string());
    }
    if max_context_memories == 0 {
        return Err("max_context_memories must be > 0".to_string());
    }
    if !(0.0..=1.0).contains(&min_confidence) {
        return Err("min_confidence must be between 0.0 and 1.0".to_string());
    }
    Ok(())
}
