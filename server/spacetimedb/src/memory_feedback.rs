use spacetimedb::*;

use crate::{memory::memory, now_micros, uuid_v4};

/// Records user feedback on a memory for trust scoring.
#[table(accessor = memory_feedback, public)]
#[derive(Debug, Clone)]
pub struct MemoryFeedback {
    #[primary_key]
    pub id: String,
    /// The memory this feedback applies to
    pub memory_id: String,
    /// "helpful" or "unhelpful"
    pub rating: String,
    /// The peer who submitted the feedback
    pub peer_id: String,
    pub created_at: i64,
}

/// Rate a memory: records feedback and adjusts its trust_score.
#[reducer]
pub fn rate_memory(
    ctx: &ReducerContext,
    memory_id: String,
    rating: String,
    peer_id: String,
) -> Result<(), String> {
    // Validate rating
    if rating != "helpful" && rating != "unhelpful" {
        return Err(format!(
            "Invalid rating '{}'. Must be 'helpful' or 'unhelpful'",
            rating
        ));
    }

    // Find the memory
    let mut mem = ctx
        .db
        .memory()
        .id()
        .find(&memory_id)
        .ok_or_else(|| format!("Memory '{}' not found", memory_id))?;

    // Record the feedback
    let feedback = MemoryFeedback {
        id: uuid_v4(ctx),
        memory_id: memory_id.clone(),
        rating: rating.clone(),
        peer_id,
        created_at: now_micros(ctx),
    };
    ctx.db.memory_feedback().insert(feedback);

    // Update trust_score (+0.05 helpful, -0.05 unhelpful, clamped 0.0–1.0)
    let delta = if rating == "helpful" { 0.05 } else { -0.05 };
    let new_score = (mem.trust_score + delta).clamp(0.0, 1.0);
    mem.trust_score = new_score;
    mem.feedback_count += 1;
    mem.updated_at = now_micros(ctx);

    ctx.db.memory().id().update(mem);
    Ok(())
}
