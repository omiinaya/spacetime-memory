use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v4};

/// A guided tour that walks through a sequence of KG nodes.
#[table(accessor = tour, public)]
#[derive(Debug, Clone)]
pub struct Tour {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub title: String,
    pub description: String,
    pub created_at: i64,
}

/// A single stop on a guided tour.
#[table(accessor = tour_stop, public)]
#[derive(Debug, Clone)]
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
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);
    ctx.db.tour().insert(Tour {
        id: id.clone(),
        workspace_id,
        title,
        description,
        created_at: now,
    });
    Ok(())
}

#[reducer]
pub fn add_tour_stop(
    ctx: &ReducerContext,
    tour_id: String,
    node_id: String,
    heading: String,
    description: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Verify the tour exists
    ctx.db.tour().id().find(&tour_id)
        .ok_or_else(|| format!("Tour '{}' not found", tour_id))?;

    // Compute next stop_order
    let max_order = ctx.db.tour_stop().iter()
        .filter(|s| s.tour_id == tour_id)
        .map(|s| s.stop_order)
        .max()
        .unwrap_or(0);

    ctx.db.tour_stop().insert(TourStop {
        id: uuid_v4(ctx),
        tour_id,
        node_id,
        stop_order: max_order + 1,
        heading,
        description,
        created_at: now_micros(ctx),
    });
    Ok(())
}

#[reducer]
pub fn remove_tour_stop(
    ctx: &ReducerContext,
    stop_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    ctx.db.tour_stop().id().find(&stop_id)
        .ok_or_else(|| format!("TourStop '{}' not found", stop_id))?;
    ctx.db.tour_stop().id().delete(&stop_id);
    Ok(())
}

#[reducer]
pub fn delete_tour(
    ctx: &ReducerContext,
    tour_id: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    // Delete all stops
    let stops: Vec<_> = ctx.db.tour_stop().iter()
        .filter(|s| s.tour_id == tour_id)
        .map(|s| s.id.clone())
        .collect();
    for sid in &stops {
        ctx.db.tour_stop().id().delete(sid);
    }
    // Delete the tour
    ctx.db.tour().id().delete(&tour_id);
    Ok(())
}
