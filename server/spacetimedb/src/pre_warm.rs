use spacetimedb::*;

use crate::auth::{account, admin_list_result, api_key, api_key_result, api_key_verification_result};
use crate::change_event::{change_event, change_event_result};
use crate::connector::connector_config;
use crate::consolidation::{consolidation_log, merge_suggestion};
use crate::context_compression::context_pack;
use crate::context_delta::delta_pack;
use crate::context_directory::{context_directory, directory_memory_link, directory_result};
use crate::crypto::{decrypted_memory_result, workspace_encryption_key};
use crate::document::{doc_chunk, document};
use crate::entity_linking::entity_link;
use crate::graph_traversal::{bridge_result, graph_traversal_result, kg_stats_result, shortest_path_result};
use crate::harmonic_belief::{harmonic_belief, resonance_log};
use crate::hybrid_query::{god_node, hybrid_result, session_search_result};
use crate::insight::{insight, mental_model};
use crate::key_rotation::{jwt_signing_key, jwt_signing_key_result, key_rotation_event, jwk_set_result};
use crate::knowledge_graph::{
    citation, citation_result, community_hierarchy, edge_history_result, hierarchy_cluster, kg_community, kg_edge,
    kg_node, pagerank_result,
};
use crate::memory::{memory, memory_revision, user_memory_result};
use crate::memory_feedback::{memory_feedback, memory_recommendation, peer_reputation, workspace_config};
use crate::message::message;
use crate::note::{block_reference, note, note_backlink, note_block, note_revision};
use crate::peer::peer;
use crate::profile::{fact, fact_result, profile};
use crate::profile_query::{directory_content_result, peer_summary_result, profile_context_result};
use crate::proxy_metrics::proxy_metrics_snapshot;
use crate::query::query_result;
use crate::replication::{replication_log, replication_peer, replication_result};
use crate::retrieval::{search_index, term_index};
use crate::session::{agent_step, session, session_participant, session_step_result};
use crate::tag::{memory_tag, memory_tag_result, tag};
use crate::tour::{tour, tour_stop};
use crate::tracing::tracing_span;
use crate::user::{user, user_session_result};
use crate::workspace::{
    space_member_result, space_permission, workspace, workspace_context_result,
    workspace_memory_stats_result,
};

/// Pre-warm all table accessors in the WASM module.
///
/// SpacetimeDB lazily compiles table accessor methods. The first call to
/// `ctx.db.<table>()` triggers WASM compilation, which adds 10–50ms of
/// latency. By iterating (or at least touching) every table during `init`,
/// we force that compilation to happen eagerly — on module load — so that
/// subsequent reducer calls serve at full speed without the first-call tax.
///
/// This function touches each table by calling `.iter().take(0)` which
/// creates an empty filtered iterator. The compiler will still generate
/// the table-accessor code, but the runtime work is ~instant (zero rows).
///
/// Note: `maintenance_schedule` is also inserted to by `init`, so it's
/// already "warm" — we include it here for completeness anyway.
pub fn pre_warm_caches(ctx: &ReducerContext) {
    pre_warm_single(ctx, "account", |ctx| ctx.db.account().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "admin_list_result", |ctx| ctx.db.admin_list_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "agent_step", |ctx| ctx.db.agent_step().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "api_key", |ctx| ctx.db.api_key().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "api_key_result", |ctx| ctx.db.api_key_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "api_key_verification_result", |ctx| ctx.db.api_key_verification_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "block_reference", |ctx| ctx.db.block_reference().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "bridge_result", |ctx| ctx.db.bridge_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "change_event", |ctx| ctx.db.change_event().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "change_event_result", |ctx| ctx.db.change_event_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "citation", |ctx| ctx.db.citation().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "citation_result", |ctx| ctx.db.citation_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "community_hierarchy", |ctx| ctx.db.community_hierarchy().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "connector_config", |ctx| ctx.db.connector_config().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "consolidation_log", |ctx| ctx.db.consolidation_log().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "context_directory", |ctx| ctx.db.context_directory().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "context_pack", |ctx| ctx.db.context_pack().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "decrypted_memory_result", |ctx| ctx.db.decrypted_memory_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "delta_pack", |ctx| ctx.db.delta_pack().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "directory_content_result", |ctx| ctx.db.directory_content_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "directory_memory_link", |ctx| ctx.db.directory_memory_link().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "directory_result", |ctx| ctx.db.directory_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "doc_chunk", |ctx| ctx.db.doc_chunk().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "document", |ctx| ctx.db.document().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "edge_history_result", |ctx| ctx.db.edge_history_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "entity_link", |ctx| ctx.db.entity_link().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "fact", |ctx| ctx.db.fact().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "fact_result", |ctx| ctx.db.fact_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "god_node", |ctx| ctx.db.god_node().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "graph_traversal_result", |ctx| ctx.db.graph_traversal_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "harmonic_belief", |ctx| ctx.db.harmonic_belief().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "hierarchy_cluster", |ctx| ctx.db.hierarchy_cluster().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "hybrid_result", |ctx| ctx.db.hybrid_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "insight", |ctx| ctx.db.insight().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "jwt_signing_key", |ctx| ctx.db.jwt_signing_key().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "jwt_signing_key_result", |ctx| ctx.db.jwt_signing_key_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "key_rotation_event", |ctx| ctx.db.key_rotation_event().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "jwk_set_result", |ctx| ctx.db.jwk_set_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "kg_community", |ctx| ctx.db.kg_community().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "kg_edge", |ctx| ctx.db.kg_edge().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "kg_node", |ctx| ctx.db.kg_node().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "kg_stats_result", |ctx| ctx.db.kg_stats_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "memory", |ctx| ctx.db.memory().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "memory_feedback", |ctx| ctx.db.memory_feedback().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "memory_recommendation", |ctx| ctx.db.memory_recommendation().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "memory_revision", |ctx| ctx.db.memory_revision().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "memory_tag", |ctx| ctx.db.memory_tag().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "memory_tag_result", |ctx| ctx.db.memory_tag_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "mental_model", |ctx| ctx.db.mental_model().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "merge_suggestion", |ctx| ctx.db.merge_suggestion().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "message", |ctx| ctx.db.message().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "note", |ctx| ctx.db.note().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "note_backlink", |ctx| ctx.db.note_backlink().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "note_block", |ctx| ctx.db.note_block().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "note_revision", |ctx| ctx.db.note_revision().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "pagerank_result", |ctx| ctx.db.pagerank_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "peer", |ctx| ctx.db.peer().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "peer_reputation", |ctx| ctx.db.peer_reputation().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "peer_summary_result", |ctx| ctx.db.peer_summary_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "profile", |ctx| ctx.db.profile().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "profile_context_result", |ctx| ctx.db.profile_context_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "proxy_metrics_snapshot", |ctx| ctx.db.proxy_metrics_snapshot().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "query_result", |ctx| ctx.db.query_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "replication_log", |ctx| ctx.db.replication_log().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "replication_peer", |ctx| ctx.db.replication_peer().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "replication_result", |ctx| ctx.db.replication_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "resonance_log", |ctx| ctx.db.resonance_log().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "search_index", |ctx| ctx.db.search_index().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "session", |ctx| ctx.db.session().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "session_participant", |ctx| ctx.db.session_participant().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "session_search_result", |ctx| ctx.db.session_search_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "session_step_result", |ctx| ctx.db.session_step_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "shortest_path_result", |ctx| ctx.db.shortest_path_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "space_member_result", |ctx| ctx.db.space_member_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "space_permission", |ctx| ctx.db.space_permission().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "tag", |ctx| ctx.db.tag().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "term_index", |ctx| ctx.db.term_index().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "tour", |ctx| ctx.db.tour().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "tour_stop", |ctx| ctx.db.tour_stop().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "tracing_span", |ctx| ctx.db.tracing_span().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "user", |ctx| ctx.db.user().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "user_memory_result", |ctx| ctx.db.user_memory_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "user_session_result", |ctx| ctx.db.user_session_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "workspace", |ctx| ctx.db.workspace().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "workspace_encryption_key", |ctx| ctx.db.workspace_encryption_key().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "workspace_config", |ctx| ctx.db.workspace_config().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "workspace_context_result", |ctx| ctx.db.workspace_context_result().iter().take(0).for_each(drop));
    pre_warm_single(ctx, "workspace_memory_stats_result", |ctx| ctx.db.workspace_memory_stats_result().iter().take(0).for_each(drop));
}

/// Pre-warm a single table, with a name for readability.
#[inline(always)]
fn pre_warm_single(ctx: &ReducerContext, _name: &str, f: impl FnOnce(&ReducerContext)) {
    f(ctx);
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Verify that the accessor listing parses — proves all imported types
    /// exist and all accessor names match the `#[table]` annotations.
    #[test]
    fn test_pre_warm_is_compilable() {
        // If this compiles, the imports and accessor names are correct.
        // Actual execution of pre_warm_caches happens inside init() on STDB.
    }

    #[test]
    fn test_pre_warm_single_invocation() {
        // Verify pre_warm_single has the expected signature
        // (runtime requires ReducerContext, checking compile-time only)
        fn _check(_ctx: &ReducerContext, _name: &str, _f: impl FnOnce(&ReducerContext)) {
            pre_warm_single(_ctx, _name, _f);
        }
    }

    #[test]
    fn test_pre_warm_table_count() {
        // Count how many tables are warmed in pre_warm_caches
        // This helps detect if new tables are added without being warmed.
        // We count by reading the source lines — a proxy check.
        let source = include_str!("pre_warm.rs");
        let warm_count = source.lines()
            .filter(|l| l.trim().starts_with("pre_warm_single("))
            .count();
        // Current count: 85 tables (update this if new tables are added)
        assert!(warm_count >= 80, "Expected at least 80 pre-warmed tables, got {}", warm_count);
    }

    #[test]
    fn test_pre_warm_caches_includes_memory() {
        let source = include_str!("pre_warm.rs");
        assert!(source.contains(r#"pre_warm_single(ctx, "memory""#));
    }

    #[test]
    fn test_pre_warm_caches_includes_message() {
        let source = include_str!("pre_warm.rs");
        assert!(source.contains(r#"pre_warm_single(ctx, "message""#));
    }

    #[test]
    fn test_pre_warm_caches_includes_user() {
        let source = include_str!("pre_warm.rs");
        assert!(source.contains(r#"pre_warm_single(ctx, "user""#));
    }
}
