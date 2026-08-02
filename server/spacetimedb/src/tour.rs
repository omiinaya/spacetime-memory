use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v7};
use crate::trace_span;
use crate::tracing::TracingSpanKind;

/// A guided tour that walks through a sequence of KG nodes.
#[table(accessor = tour)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Tour {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub title: String,
    pub description: String,
    pub created_at: i64,
}

/// A single stop on a guided tour.
#[table(accessor = tour_stop)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct TourStop {
    #[primary_key]
    pub id: String,
    pub tour_id: String,
    pub node_id: String,
    /// Display order within the tour
    pub stop_order: u32,
    /// Heading shown when this stop is active
    pub heading: String,
    /// Body text explaining what to look at
    pub description: String,
    pub created_at: i64,
}

#[reducer]
pub fn create_tour(
    ctx: &ReducerContext,
    workspace_id: String,
    title: String,
    description: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_tour", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let now = now_micros(ctx);
        let id = uuid_v7(ctx);
        ctx.db.tour().insert(Tour {
            id: id.clone(),
            workspace_id: workspace_id.clone(),
            title,
            description,
            created_at: now,
        });
        Ok(())
    })
}

#[reducer]
pub fn add_tour_stop(
    ctx: &ReducerContext,
    tour_id: String,
    node_id: String,
    heading: String,
    description: String,
) -> Result<(), String> {
    trace_span!(ctx, "add_tour_stop", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        // Verify the tour exists
        ctx.db.tour().id().find(&tour_id)
            .ok_or_else(|| format!("Tour '{}' not found", tour_id))?;

        // Compute next stop_order
        let max_order = ctx.db.tour_stop().iter().take(crate::MAX_RESULTS)
            .filter(|ts| ts.tour_id == tour_id)
            .map(|ts| ts.stop_order)
            .max()
            .unwrap_or(0);

        ctx.db.tour_stop().insert(TourStop {
            id: uuid_v7(ctx),
            tour_id,
            node_id,
            stop_order: max_order + 1,
            heading,
            description,
            created_at: now_micros(ctx),
        });
        Ok(())
    })
}

#[reducer]
pub fn remove_tour_stop(
    ctx: &ReducerContext,
    stop_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "remove_tour_stop", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        ctx.db.tour_stop().id().find(&stop_id)
            .ok_or_else(|| format!("TourStop '{}' not found", stop_id))?;
        ctx.db.tour_stop().id().delete(&stop_id);
        Ok(())
    })
}

#[reducer]
pub fn delete_tour(
    ctx: &ReducerContext,
    tour_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "delete_tour", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        // Delete all stops
        let stops: Vec<_> = ctx.db.tour_stop().iter().take(crate::MAX_RESULTS)
            .filter(|s| s.tour_id == tour_id)
            .map(|s| s.id.clone())
            .collect();
        for sid in &stops {
            ctx.db.tour_stop().id().delete(sid);
        }
        // Delete the tour
        ctx.db.tour().id().delete(&tour_id);
        Ok(())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tour_creation() {
        let tour = Tour {
            id: "tour-1".to_string(),
            workspace_id: "ws-1".to_string(),
            title: "Knowledge Graph Tour".to_string(),
            description: "A tour of the knowledge graph".to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(tour.id, "tour-1");
        assert_eq!(tour.workspace_id, "ws-1");
        assert_eq!(tour.title, "Knowledge Graph Tour");
        assert_eq!(tour.description, "A tour of the knowledge graph");
        assert_eq!(tour.created_at, 1_000_000);
    }

    #[test]
    fn test_tour_stop_creation() {
        let stop = TourStop {
            id: "stop-1".to_string(),
            tour_id: "tour-1".to_string(),
            node_id: "node-1".to_string(),
            stop_order: 1,
            heading: "Introduction".to_string(),
            description: "Welcome to the tour".to_string(),
            created_at: 1_000_000,
        };
        assert_eq!(stop.id, "stop-1");
        assert_eq!(stop.tour_id, "tour-1");
        assert_eq!(stop.node_id, "node-1");
        assert_eq!(stop.stop_order, 1);
        assert_eq!(stop.heading, "Introduction");
        assert_eq!(stop.description, "Welcome to the tour");
        assert_eq!(stop.created_at, 1_000_000);
    }

    #[test]
    fn test_tour_deserialization() {
        let json = r#"{
            "id": "tour-1",
            "workspace_id": "ws-1",
            "title": "Knowledge Graph Tour",
            "description": "A tour of the knowledge graph",
            "created_at": 1000000
        }"#;
        let tour: Tour = serde_json::from_str(json).expect("Failed to deserialize Tour");
        assert_eq!(tour.id, "tour-1");
        assert_eq!(tour.workspace_id, "ws-1");
        assert_eq!(tour.title, "Knowledge Graph Tour");
        assert_eq!(tour.description, "A tour of the knowledge graph");
        assert_eq!(tour.created_at, 1_000_000);
    }

    #[test]
    fn test_tour_stop_serialization() {
        let stop = TourStop {
            id: "stop-42".to_string(),
            tour_id: "tour-1".to_string(),
            node_id: "node-7".to_string(),
            stop_order: 3,
            heading: "Deep Dive".to_string(),
            description: "Let's look at the details".to_string(),
            created_at: 2_000_000,
        };
        let json = serde_json::to_string(&stop).expect("Failed to serialize TourStop");
        assert!(json.contains("\"id\":\"stop-42\""));
        assert!(json.contains("\"tour_id\":\"tour-1\""));
        assert!(json.contains("\"node_id\":\"node-7\""));
        assert!(json.contains("\"stop_order\":3"));
        assert!(json.contains("\"heading\":\"Deep Dive\""));
        assert!(json.contains("\"description\":\"Let's look at the details\""));
        assert!(json.contains("\"created_at\":2000000"));
    }
}
