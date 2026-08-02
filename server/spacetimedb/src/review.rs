use spacetimedb::*;

use crate::{now_micros, uuid_v4_uniq};
use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::tracing::TracingSpanKind;
use crate::trace_span;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// Minimum easiness factor per SM-2 specification.
pub const MIN_EF: f64 = 1.3;

/// Default initial easiness factor.
pub const DEFAULT_EF: f64 = 2.5;

/// Interval for the first successful review (grade >= 2), in days.
pub const FIRST_INTERVAL_DAYS: u32 = 1;

/// Interval for the second successful review (grade >= 2), in days.
pub const SECOND_INTERVAL_DAYS: u32 = 6;

/// Maximum grade value for the SM-2 scale.
pub const MAX_GRADE: u8 = 6;

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/// An individual review item tracking SM-2 spaced repetition state for a
/// memory within a workspace, scoped to a specific user.
#[table(accessor = review_item)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ReviewItem {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The memory/content this review item tracks.
    pub memory_id: String,
    /// The user performing the review.
    pub user_id: String,
    /// SM-2 easiness factor (default 2.5, clamped to ≥ 1.3).
    pub easiness_factor: f64,
    /// Current review interval in days.
    pub interval_days: u32,
    /// Number of consecutive successful reviews (grade >= 2).
    pub repetitions: u32,
    /// Timestamp (micros) of the next scheduled review.
    pub next_review_at: i64,
    /// Timestamp (micros) of the last review.
    pub last_reviewed_at: i64,
    /// Timestamp (micros) of creation.
    pub created_at: i64,
    /// Sum of all grades received (for statistics).
    pub grade_sum: u64,
    /// Number of grades recorded (for statistics).
    pub grade_count: u32,
    /// Whether this review item is active.
    pub is_active: bool,
}

/// Result table for `get_due_reviews` and `get_review_stats` reducers.
/// Clients read from this table after calling the reducer.
#[table(accessor = review_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ReviewResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub user_id: String,
    /// JSON representation of the returned items or stats.
    pub items_json: String,
    /// Number of items in the result.
    pub due_count: u32,
    /// Timestamp (micros) of creation.
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// SM-2 Algorithm (pure helper, no STDB dependency)
// ---------------------------------------------------------------------------

/// Represents the updatable state of an SM-2 review item.
#[derive(Debug, Clone, Copy)]
pub struct Sm2State {
    pub easiness_factor: f64,
    pub interval_days: u32,
    pub repetitions: u32,
}

/// Applies the SM-2 algorithm given a grade (0–6) and the current state.
///
/// Returns the updated state and the computed next interval in days.
///
/// # SM-2 Algorithm
///
/// ## Retention phase (grade >= 2)
/// - EF' = EF + (0.1 - (5 - g) * (0.08 + (5 - g) * 0.02))
/// - Clamp EF' to ≥ 1.3
/// - If repetitions == 0: interval = 1 day
/// - If repetitions == 1: interval = 6 days
/// - Else: interval = round(interval * EF)
/// - repetitions += 1
///
/// ## Acquisition phase (grade < 2)
/// - Reset repetitions to 0
/// - Set interval to 1 day
/// - Decrease EF slightly (same formula, but the user is expected to relearn)
pub fn sm2_next_state(state: &Sm2State, grade: u8) -> Sm2State {
    let grade = grade.min(MAX_GRADE);

    if grade >= 2 {
        // Retention phase: successful recall
        let q = 5.0 - grade as f64;
        let mut ef = state.easiness_factor + (0.1 - q * (0.08 + q * 0.02));
        if ef < MIN_EF {
            ef = MIN_EF;
        }

        let interval = if state.repetitions == 0 {
            FIRST_INTERVAL_DAYS
        } else if state.repetitions == 1 {
            SECOND_INTERVAL_DAYS
        } else {
            // interval = round(interval * EF)
            let raw = state.interval_days as f64 * state.easiness_factor;
            raw.round().max(1.0) as u32
        };

        Sm2State {
            easiness_factor: ef,
            interval_days: interval,
            repetitions: state.repetitions + 1,
        }
    } else {
        // Acquisition phase: failed recall — reset
        // Apply the same EF adjustment (with negative grade → larger decrease)
        let q = 5.0 - grade as f64;
        let mut ef = state.easiness_factor + (0.1 - q * (0.08 + q * 0.02));
        if ef < MIN_EF {
            ef = MIN_EF;
        }

        Sm2State {
            easiness_factor: ef,
            interval_days: FIRST_INTERVAL_DAYS,
            repetitions: 0,
        }
    }
}

/// Compute the next review timestamp (micros) given an interval in days and a
/// base timestamp (usually `now`). Pure function — no STDB dependency.
pub fn compute_next_review_at(now_micros: i64, interval_days: u32) -> i64 {
    now_micros + (interval_days as i64) * 86_400_000_000i64
}

// ---------------------------------------------------------------------------
// Reducers
// ---------------------------------------------------------------------------

/// Create or update a ReviewItem for the given memory and user with initial
/// SM-2 scheduling (first review due immediately with default EF).
#[reducer]
pub fn schedule_review(
    ctx: &ReducerContext,
    workspace_id: String,
    memory_id: String,
    user_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "schedule_review", TracingSpanKind::Write, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;

        let now = now_micros(ctx);

        // Check if a review item already exists for this workspace + memory + user
        let existing: Vec<ReviewItem> = ctx
            .db
            .review_item()
            .workspace_id()
            .filter(&workspace_id)
            .filter(|ri| ri.memory_id == memory_id && ri.user_id == user_id)
            .take(1)
            .collect();

        if let Some(mut item) = existing.into_iter().next() {
            // Update existing — reset to initial state for rescheduling
            item.easiness_factor = DEFAULT_EF;
            item.interval_days = 0;
            item.repetitions = 0;
            item.next_review_at = now; // due immediately
            item.last_reviewed_at = now;
            item.is_active = true;
            item.grade_sum = 0;
            item.grade_count = 0;
            ctx.db.review_item().id().update(item);
        } else {
            // Create new review item
            let id = uuid_v4_uniq(ctx, |id| ctx.db.review_item().id().find(id).is_none(), 3);
            let item = ReviewItem {
                id,
                workspace_id: workspace_id.clone(),
                memory_id,
                user_id,
                easiness_factor: DEFAULT_EF,
                interval_days: 0,
                repetitions: 0,
                next_review_at: now,
                last_reviewed_at: now,
                created_at: now,
                grade_sum: 0,
                grade_count: 0,
                is_active: true,
            };
            ctx.db.review_item().insert(item);
        }

        Ok(())
    })
}

/// Perform a review on an existing ReviewItem with the given grade (0–6).
/// Implements the SM-2 algorithm to update easiness_factor, interval, and
/// next_review_at.
#[reducer]
pub fn perform_review(
    ctx: &ReducerContext,
    review_id: String,
    grade: u8,
) -> Result<(), String> {
    trace_span!(ctx, "perform_review", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();

        // Validate grade
        if grade > MAX_GRADE {
            return Err(format!(
                "Invalid grade {}: must be 0–{}",
                grade, MAX_GRADE
            ));
        }

        let mut item = ctx
            .db
            .review_item()
            .id()
            .find(&review_id)
            .ok_or_else(|| format!("ReviewItem '{}' not found", review_id))?;

        // Check caller has access to the workspace
        check_space_access(ctx, &item.workspace_id, &caller, "editor")?;

        let now = now_micros(ctx);

        // Get current SM-2 state
        let state = Sm2State {
            easiness_factor: item.easiness_factor,
            interval_days: item.interval_days,
            repetitions: item.repetitions,
        };

        // Apply SM-2 algorithm
        let new_state = sm2_next_state(&state, grade);

        let next_review_at = compute_next_review_at(now, new_state.interval_days);

        // Update the review item
        item.easiness_factor = new_state.easiness_factor;
        item.interval_days = new_state.interval_days;
        item.repetitions = new_state.repetitions;
        item.next_review_at = next_review_at;
        item.last_reviewed_at = now;
        item.grade_sum = item.grade_sum.wrapping_add(grade as u64);
        item.grade_count = item.grade_count.wrapping_add(1);

        ctx.db.review_item().id().update(item);

        Ok(())
    })
}

/// Find all review items for a workspace/user where `next_review_at <= now`,
/// and store the results in the `review_result` table.
#[reducer]
pub fn get_due_reviews(
    ctx: &ReducerContext,
    workspace_id: String,
    user_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_due_reviews", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "viewer")?;

        let now = now_micros(ctx);

        // Collect due review items
        let due: Vec<ReviewItem> = ctx
            .db
            .review_item()
            .workspace_id()
            .filter(&workspace_id)
            .filter(|ri| {
                ri.is_active
                    && ri.user_id == user_id
                    && ri.next_review_at <= now
            })
            .take(crate::MAX_RESULTS)
            .collect();

        let items_json = serde_json::to_string(&due)
            .map_err(|e| format!("Failed to serialize due reviews: {}", e))?;
        let due_count = due.len() as u32;

        // Clean up stale results for this workspace + user
        for old in ctx
            .db
            .review_result()
            .iter()
            .filter(|r| r.workspace_id == workspace_id && r.user_id == user_id)
            .collect::<Vec<_>>()
        {
            ctx.db.review_result().id().delete(&old.id);
        }

        let id = uuid_v4_uniq(ctx, |id| ctx.db.review_result().id().find(id).is_none(), 3);
        ctx.db.review_result().insert(ReviewResult {
            id,
            workspace_id: workspace_id.clone(),
            user_id: user_id.clone(),
            items_json,
            due_count,
            created_at: now,
        });

        Ok(())
    })
}

/// Collect and store review statistics (aggregate grade/interval data) for a
/// workspace/user. Results are stored in `review_result` table with
/// `items_json` containing summary statistics.
#[reducer]
pub fn get_review_stats(
    ctx: &ReducerContext,
    workspace_id: String,
    user_id: String,
) -> Result<(), String> {
    trace_span!(ctx, "get_review_stats", TracingSpanKind::Read, &workspace_id, {
        let _account = require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "viewer")?;

        let now = now_micros(ctx);

        let items: Vec<ReviewItem> = ctx
            .db
            .review_item()
            .workspace_id()
            .filter(&workspace_id)
            .filter(|ri| ri.is_active && ri.user_id == user_id)
            .take(crate::MAX_RESULTS)
            .collect();

        let total = items.len() as u32;
        let active = items.iter().filter(|ri| ri.is_active).count() as u32;
        let due_now = items
            .iter()
            .filter(|ri| ri.is_active && ri.next_review_at <= now)
            .count() as u32;
        let avg_grade = if items.is_empty() {
            0.0
        } else {
            let total_grades: u64 = items.iter().map(|ri| ri.grade_sum).sum();
            let total_count: u64 = items.iter().map(|ri| ri.grade_count as u64).sum();
            if total_count == 0 {
                0.0
            } else {
                total_grades as f64 / total_count as f64
            }
        };
        let avg_ef = if items.is_empty() {
            0.0
        } else {
            items.iter().map(|ri| ri.easiness_factor).sum::<f64>() / items.len() as f64
        };

        #[derive(serde::Serialize)]
        struct Stats {
            total_review_items: u32,
            active_items: u32,
            due_now: u32,
            average_grade: f64,
            average_easiness_factor: f64,
            user_id: String,
        }

        let stats = Stats {
            total_review_items: total,
            active_items: active,
            due_now,
            average_grade: avg_grade,
            average_easiness_factor: avg_ef,
            user_id: user_id.clone(),
        };

        let items_json = serde_json::to_string(&stats)
            .map_err(|e| format!("Failed to serialize review stats: {}", e))?;

        // Clean up stale results for this workspace + user
        for old in ctx
            .db
            .review_result()
            .iter()
            .filter(|r| r.workspace_id == workspace_id && r.user_id == user_id)
            .collect::<Vec<_>>()
        {
            ctx.db.review_result().id().delete(&old.id);
        }

        let id = uuid_v4_uniq(ctx, |id| ctx.db.review_result().id().find(id).is_none(), 3);
        ctx.db.review_result().insert(ReviewResult {
            id,
            workspace_id: workspace_id.clone(),
            user_id: user_id.clone(),
            items_json,
            due_count: due_now,
            created_at: now,
        });

        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ---- SM-2 Algorithm Tests ----

    #[test]
    fn test_sm2_initial_state_defaults() {
        let state = Sm2State {
            easiness_factor: DEFAULT_EF,
            interval_days: 0,
            repetitions: 0,
        };
        assert_eq!(state.easiness_factor, 2.5);
        assert_eq!(state.interval_days, 0);
        assert_eq!(state.repetitions, 0);
    }

    #[test]
    fn test_sm2_grade_0_resets_repetitions() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 10,
            repetitions: 5,
        };
        let new = sm2_next_state(&state, 0);
        // Grade < 2 resets repetitions and interval
        assert_eq!(new.repetitions, 0);
        assert_eq!(new.interval_days, FIRST_INTERVAL_DAYS);
    }

    #[test]
    fn test_sm2_grade_1_resets_repetitions() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 10,
            repetitions: 5,
        };
        let new = sm2_next_state(&state, 1);
        assert_eq!(new.repetitions, 0);
        assert_eq!(new.interval_days, FIRST_INTERVAL_DAYS);
    }

    #[test]
    fn test_sm2_grade_2_first_review() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 0,
            repetitions: 0,
        };
        let new = sm2_next_state(&state, 2);
        // First successful review → interval = 1 day, repetitions = 1
        assert_eq!(new.interval_days, FIRST_INTERVAL_DAYS);
        assert_eq!(new.repetitions, 1);
        // EF should stay roughly the same: EF + (0.1 - 3 * (0.08 + 3 * 0.02))
        // = 2.5 + (0.1 - 3 * (0.08 + 0.06)) = 2.5 + (0.1 - 3 * 0.14)
        // = 2.5 + (0.1 - 0.42) = 2.5 - 0.32 = 2.18
        assert!((new.easiness_factor - 2.18).abs() < 0.001);
    }

    #[test]
    fn test_sm2_grade_3_first_review() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 0,
            repetitions: 0,
        };
        let new = sm2_next_state(&state, 3);
        assert_eq!(new.interval_days, FIRST_INTERVAL_DAYS);
        assert_eq!(new.repetitions, 1);
        // EF + (0.1 - 2 * (0.08 + 2 * 0.02)) = 2.5 + (0.1 - 2 * 0.12)
        // = 2.5 + (0.1 - 0.24) = 2.5 - 0.14 = 2.36
        assert!((new.easiness_factor - 2.36).abs() < 0.001);
    }

    #[test]
    fn test_sm2_grade_5_first_review() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 0,
            repetitions: 0,
        };
        let new = sm2_next_state(&state, 5);
        assert_eq!(new.interval_days, FIRST_INTERVAL_DAYS);
        assert_eq!(new.repetitions, 1);
        // EF + (0.1 - 0 * (0.08 + 0 * 0.02)) = 2.5 + 0.1 = 2.6
        assert!((new.easiness_factor - 2.6).abs() < 0.001);
    }

    #[test]
    fn test_sm2_grade_4_second_review() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: FIRST_INTERVAL_DAYS,
            repetitions: 1,
        };
        let new = sm2_next_state(&state, 4);
        // Second successful review → interval = 6 days, repetitions = 2
        assert_eq!(new.interval_days, SECOND_INTERVAL_DAYS);
        assert_eq!(new.repetitions, 2);
        // EF + (0.1 - 1 * (0.08 + 1 * 0.02)) = 2.5 + (0.1 - 0.1) = 2.5
        assert!((new.easiness_factor - 2.5).abs() < 0.001);
    }

    #[test]
    fn test_sm2_grade_4_third_review() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: SECOND_INTERVAL_DAYS,
            repetitions: 2,
        };
        let new = sm2_next_state(&state, 4);
        // Third+ review: interval = round(6 * 2.5) = 15 days
        assert_eq!(new.interval_days, 15);
        assert_eq!(new.repetitions, 3);
    }

    #[test]
    fn test_sm2_ef_clamped_to_minimum() {
        let state = Sm2State {
            easiness_factor: 1.3,
            interval_days: 1,
            repetitions: 1,
        };
        // Grade 0 should further decrease EF but clamp at 1.3
        let new = sm2_next_state(&state, 0);
        assert!(new.easiness_factor >= MIN_EF);
        // EF decrease: 1.3 + (0.1 - 5 * (0.08 + 5 * 0.02))
        // = 1.3 + (0.1 - 5 * 0.18) = 1.3 + (0.1 - 0.9) = 1.3 - 0.8 = 0.5 → clamped to 1.3
        assert!((new.easiness_factor - MIN_EF).abs() < 0.001);
    }

    #[test]
    fn test_sm2_grade_6_perfect_score() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 10,
            repetitions: 3,
        };
        let new = sm2_next_state(&state, 6);
        // Grade 6: EF = 2.5 + (0.1 - (-1) * (0.08 + (-1) * 0.02))
        // = 2.5 + (0.1 - (-1) * (0.08 - 0.02))
        // = 2.5 + (0.1 - (-1) * 0.06)
        // = 2.5 + (0.1 + 0.06) = 2.5 + 0.16 = 2.66
        assert!((new.easiness_factor - 2.66).abs() < 0.001);
        // Interval = round(10 * 2.5) = 25
        assert_eq!(new.interval_days, 25);
        assert_eq!(new.repetitions, 4);
    }

    #[test]
    fn test_sm2_grade_clamped_to_max() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 1,
            repetitions: 0,
        };
        // Grade > 6 should be clamped to 6
        let new = sm2_next_state(&state, 255);
        // Should behave like grade 6
        assert!((new.easiness_factor - 2.66).abs() < 0.001);
    }

    #[test]
    fn test_sm2_consecutive_perfect_reviews() {
        let mut state = Sm2State {
            easiness_factor: DEFAULT_EF,
            interval_days: 0,
            repetitions: 0,
        };

        // Review 1 (grade 5): interval = 1, reps = 1
        state = sm2_next_state(&state, 5);
        assert_eq!(state.interval_days, 1);
        assert_eq!(state.repetitions, 1);

        // Review 2 (grade 5): interval = 6, reps = 2
        state = sm2_next_state(&state, 5);
        assert_eq!(state.interval_days, 6);
        assert_eq!(state.repetitions, 2);

        // Review 3 (grade 5): EF was 2.7 after review 2, interval = round(6 * 2.7) = round(16.2) = 16, reps = 3
        state = sm2_next_state(&state, 5);
        assert_eq!(state.interval_days, 16);
        assert_eq!(state.repetitions, 3);

        // Review 4 (grade 5): EF is 2.8 after review 3, interval = round(16 * 2.8) = round(44.8) = 45, reps = 4
        state = sm2_next_state(&state, 5);
        assert_eq!(state.interval_days, 45);
        assert_eq!(state.repetitions, 4);

        // Verify EF grew monotonically
        assert!(state.easiness_factor > 2.6);
    }

    #[test]
    fn test_sm2_failure_after_success_resets() {
        let mut state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 6,
            repetitions: 2,
        };

        // Fail with grade 1
        state = sm2_next_state(&state, 1);
        assert_eq!(state.repetitions, 0);
        assert_eq!(state.interval_days, 1);

        // Now re-succeed with grade 4 → back to first interval
        state = sm2_next_state(&state, 4);
        assert_eq!(state.repetitions, 1);
        assert_eq!(state.interval_days, 1);

        // Re-succeed again → second interval
        state = sm2_next_state(&state, 4);
        assert_eq!(state.repetitions, 2);
        assert_eq!(state.interval_days, 6);
    }

    #[test]
    fn test_sm2_ef_decreases_on_low_grades() {
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 10,
            repetitions: 5,
        };
        let new = sm2_next_state(&state, 0);
        // Grade 0 should result in EF < original
        assert!(new.easiness_factor < state.easiness_factor);
    }

    // ---- compute_next_review_at tests ----

    #[test]
    fn test_compute_next_review_at_zero_days() {
        let now = 1_000_000_000_000i64;
        let next = compute_next_review_at(now, 0);
        assert_eq!(next, now);
    }

    #[test]
    fn test_compute_next_review_at_one_day() {
        let now = 0i64;
        let next = compute_next_review_at(now, 1);
        assert_eq!(next, 86_400_000_000i64);
    }

    #[test]
    fn test_compute_next_review_at_multi_day() {
        let now = 1_000_000_000_000i64;
        let next = compute_next_review_at(now, 7);
        assert_eq!(next, now + 7 * 86_400_000_000i64);
    }

    #[test]
    fn test_compute_next_review_at_large_interval() {
        let now = 0i64;
        let next = compute_next_review_at(now, 365);
        assert_eq!(next, 365 * 86_400_000_000i64);
    }

    // ---- ReviewItem struct tests ----

    #[test]
    fn test_review_item_default_construction() {
        let item = ReviewItem {
            id: "ri_001".to_string(),
            workspace_id: "ws_001".to_string(),
            memory_id: "mem_001".to_string(),
            user_id: "user_001".to_string(),
            easiness_factor: DEFAULT_EF,
            interval_days: 0,
            repetitions: 0,
            next_review_at: 1_000_000,
            last_reviewed_at: 1_000_000,
            created_at: 1_000_000,
            grade_sum: 0,
            grade_count: 0,
            is_active: true,
        };
        assert_eq!(item.id, "ri_001");
        assert_eq!(item.easiness_factor, 2.5);
        assert_eq!(item.interval_days, 0);
        assert_eq!(item.repetitions, 0);
        assert!(item.is_active);
        assert_eq!(item.grade_sum, 0);
        assert_eq!(item.grade_count, 0);
    }

    #[test]
    fn test_review_item_after_review() {
        let item = ReviewItem {
            id: "ri_002".to_string(),
            workspace_id: "ws_001".to_string(),
            memory_id: "mem_002".to_string(),
            user_id: "user_001".to_string(),
            easiness_factor: 2.5,
            interval_days: 6,
            repetitions: 2,
            next_review_at: 2_000_000,
            last_reviewed_at: 1_000_000,
            created_at: 1_000_000,
            grade_sum: 9,
            grade_count: 2,
            is_active: true,
        };
        assert_eq!(item.repetitions, 2);
        assert_eq!(item.interval_days, 6);
        assert_eq!(item.grade_sum, 9);
        assert_eq!(item.grade_count, 2);
    }

    #[test]
    fn test_review_item_inactive() {
        let item = ReviewItem {
            id: "ri_inactive".to_string(),
            workspace_id: "ws_001".to_string(),
            memory_id: "mem_003".to_string(),
            user_id: "user_001".to_string(),
            easiness_factor: 1.5,
            interval_days: 30,
            repetitions: 10,
            next_review_at: 0,
            last_reviewed_at: 50_000_000,
            created_at: 0,
            grade_sum: 45,
            grade_count: 10,
            is_active: false,
        };
        assert!(!item.is_active);
    }

    #[test]
    fn test_review_item_serde_roundtrip() {
        let item = ReviewItem {
            id: "ri_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            memory_id: "mem_serde".to_string(),
            user_id: "user_serde".to_string(),
            easiness_factor: 2.3,
            interval_days: 15,
            repetitions: 3,
            next_review_at: 10_000_000,
            last_reviewed_at: 5_000_000,
            created_at: 0,
            grade_sum: 12,
            grade_count: 3,
            is_active: true,
        };
        let json = serde_json::to_string(&item).expect("serialize");
        let deserialized: ReviewItem = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, item.id);
        assert_eq!(deserialized.easiness_factor, item.easiness_factor);
        assert_eq!(deserialized.interval_days, item.interval_days);
        assert_eq!(deserialized.repetitions, item.repetitions);
        assert_eq!(deserialized.grade_sum, item.grade_sum);
        assert_eq!(deserialized.grade_count, item.grade_count);
        assert_eq!(deserialized.is_active, item.is_active);
    }

    // ---- ReviewResult struct tests ----

    #[test]
    fn test_review_result_construction() {
        let result = ReviewResult {
            id: "rr_001".to_string(),
            workspace_id: "ws_001".to_string(),
            user_id: "user_001".to_string(),
            items_json: "[]".to_string(),
            due_count: 0,
            created_at: 1_000_000,
        };
        assert_eq!(result.id, "rr_001");
        assert_eq!(result.due_count, 0);
        assert_eq!(result.items_json, "[]");
    }

    #[test]
    fn test_review_result_with_items() {
        let items = vec![
            ReviewItem {
                id: "ri_001".to_string(),
                workspace_id: "ws_001".to_string(),
                memory_id: "mem_001".to_string(),
                user_id: "user_001".to_string(),
                easiness_factor: 2.5,
                interval_days: 1,
                repetitions: 1,
                next_review_at: 1_000,
                last_reviewed_at: 0,
                created_at: 0,
                grade_sum: 4,
                grade_count: 1,
                is_active: true,
            },
        ];
        let json = serde_json::to_string(&items).expect("serialize");
        let result = ReviewResult {
            id: "rr_items".to_string(),
            workspace_id: "ws_001".to_string(),
            user_id: "user_001".to_string(),
            items_json: json,
            due_count: 1,
            created_at: 1_000_000,
        };
        assert_eq!(result.due_count, 1);
        let deserialized: Vec<ReviewItem> =
            serde_json::from_str(&result.items_json).expect("deserialize");
        assert_eq!(deserialized.len(), 1);
        assert_eq!(deserialized[0].id, "ri_001");
    }

    #[test]
    fn test_review_result_serde_roundtrip() {
        let result = ReviewResult {
            id: "rr_serde".to_string(),
            workspace_id: "ws_serde".to_string(),
            user_id: "user_serde".to_string(),
            items_json: r#"[]"#.to_string(),
            due_count: 0,
            created_at: 0,
        };
        let json = serde_json::to_string(&result).expect("serialize");
        let deserialized: ReviewResult = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(deserialized.id, result.id);
        assert_eq!(deserialized.workspace_id, result.workspace_id);
        assert_eq!(deserialized.due_count, result.due_count);
    }

    // ---- Edge case tests ----

    #[test]
    fn test_sm2_minimum_interval_on_large_ef() {
        // Even with very high EF, the interval calculation should never
        // produce an interval below 1 day after rounding.
        let state = Sm2State {
            easiness_factor: 1.3,
            interval_days: 1,
            repetitions: 10,
        };
        let new = sm2_next_state(&state, 4);
        // round(1 * 1.3) = 1
        assert_eq!(new.interval_days, 1);
        assert!(new.interval_days >= 1);
    }

    #[test]
    fn test_sm2_max_grade_consistency() {
        // Verify that grade 6 always produces higher EF than grade 5
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 10,
            repetitions: 5,
        };
        let g5 = sm2_next_state(&state, 5);
        let g6 = sm2_next_state(&state, 6);
        assert!(g6.easiness_factor > g5.easiness_factor);
    }

    #[test]
    fn test_sm2_min_grade_consistency() {
        // Grade 0 should decrease EF more than grade 1
        let state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 10,
            repetitions: 5,
        };
        let g0 = sm2_next_state(&state, 0);
        let g1 = sm2_next_state(&state, 1);
        // Both reset, but EF decrease should be larger for grade 0
        assert!(g0.easiness_factor <= g1.easiness_factor);
    }

    #[test]
    fn test_review_item_zero_grade_stats() {
        let item = ReviewItem {
            id: "ri_stats".to_string(),
            workspace_id: "ws".to_string(),
            memory_id: "mem".to_string(),
            user_id: "user".to_string(),
            easiness_factor: 2.5,
            interval_days: 0,
            repetitions: 0,
            next_review_at: 0,
            last_reviewed_at: 0,
            created_at: 0,
            grade_sum: 0,
            grade_count: 0,
            is_active: true,
        };
        assert_eq!(item.grade_sum, 0);
        assert_eq!(item.grade_count, 0);
        // Average grade is undefined (0/0), but shouldn't panic
        let avg = if item.grade_count > 0 {
            item.grade_sum as f64 / item.grade_count as f64
        } else {
            0.0
        };
        assert_eq!(avg, 0.0);
    }

    #[test]
    fn test_compute_next_review_at_negative_now() {
        let now = -86_400_000_000i64;
        let next = compute_next_review_at(now, 1);
        assert_eq!(next, 0);
    }

    #[test]
    fn test_sm2_after_many_repetitions() {
        // Simulate a long-running review history
        let mut state = Sm2State {
            easiness_factor: 2.5,
            interval_days: 180,
            repetitions: 10,
        };
        // Grade 4 (good) on a mature item
        state = sm2_next_state(&state, 4);
        assert_eq!(state.repetitions, 11);
        // interval = round(180 * 2.5) = 450
        assert_eq!(state.interval_days, 450);
        // EF increased slightly
        assert!((state.easiness_factor - 2.5).abs() < 0.001);
    }
}
