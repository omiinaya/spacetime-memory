use spacetimedb::*;

use crate::{now_micros, uuid_v4_uniq};
use crate::memory::memory;

// ---------------------------------------------------------------------------
// Result tables — compute-and-store pattern (see consolidation.rs)
// ---------------------------------------------------------------------------

/// A temporal cluster result — memories grouped by time proximity.
#[table(accessor = temporal_cluster_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct TemporalClusterResult {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// Unix epoch seconds of the bucket start
    pub start_time: i64,
    /// Unix epoch seconds of the bucket end
    pub end_time: i64,
    /// Number of memories in this cluster
    pub count: u64,
    /// JSON array of memory IDs
    pub memory_ids: String,
    /// JSON array of top summary terms (max 5)
    pub summary_terms: String,
    pub created_at: i64,
}

/// An entity co‑occurrence result — two entity names that frequently appear
/// together across memories in the workspace.
#[table(accessor = entity_cooccurrence_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct EntityCooccurrenceResult {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// First entity name
    pub entity_a: String,
    /// Second entity name
    pub entity_b: String,
    /// Number of memories where both entities co‑occur
    pub count: u64,
    /// Strength 0.0–1.0 (Jaccard-like: count / total memories in workspace)
    pub strength: f64,
    pub created_at: i64,
}

/// A topic cluster result — groups of memories sharing common terms.
#[table(accessor = topic_cluster_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct TopicClusterResult {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The topic label (most common term for this cluster)
    pub topic: String,
    /// Number of memories in this topic cluster
    pub count: u64,
    /// JSON array of memory IDs in this cluster
    pub memory_ids: String,
    /// JSON array of top terms for this topic (max 10)
    pub top_terms: String,
    /// Average confidence of memories in this cluster
    pub avg_confidence: f64,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Simple tokenizer matching the client-side pattern detection.
fn tokenize(text: &str) -> Vec<String> {
    use regex::Regex;
    // Lazy‑static regex compiled once — the literal is valid so this never fails
    let re = Regex::new(r"[a-zA-Z0-9_]+").expect("hardcoded regex is valid");
    re.find_iter(text)
        .map(|m| m.as_str().to_lowercase())
        .filter(|t| t.len() >= 3)
        .collect()
}

/// Extract the entity names from a Memory's `entities_json` field.
/// Expected format: JSON array of `{"type": "...", "name": "..."}` objects.
fn extract_entities_from_json(entities_json: &str) -> Vec<String> {
    if entities_json.is_empty() || entities_json == "[]" {
        return Vec::new();
    }
    match serde_json::from_str::<Vec<serde_json::Value>>(entities_json) {
        Ok(entries) => entries
            .iter()
            .filter_map(|v| {
                v.get("name")
                    .and_then(|n| n.as_str())
                    .map(|s| s.to_lowercase())
            })
            .collect(),
        Err(_) => Vec::new(),
    }
}

// ---------------------------------------------------------------------------
// Reducer: detect_temporal_clusters
// ---------------------------------------------------------------------------

/// Find temporal clusters — groups of memories stored close together in time.
///
/// Uses 30‑minute buckets (matching the client‑side default). Bounded by
/// `crate::MAX_RESULTS`. Clears previous results for the workspace before
/// writing new ones (compute‑and‑store pattern).
#[reducer]
pub fn detect_temporal_clusters(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);
    const BUCKET_SECS: i64 = 30 * 60; // 30 minutes

    // ── Collect active memories for this workspace ───────────────────────
    let memories: Vec<(String, String, i64)> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .map(|m| (m.id.clone(), m.content.clone(), m.created_at))
        .collect();

    if memories.is_empty() {
        // Still clean up stale results
        cleanup_temporal_clusters(ctx, &workspace_id);
        return Ok(());
    }

    // ── Bucket by time ───────────────────────────────────────────────────
    use std::collections::HashMap;
    let mut buckets: HashMap<i64, Vec<(String, String)>> = HashMap::new();
    for (id, content, ts) in &memories {
        // Convert from micros to seconds for bucket maths
        let ts_secs = ts / 1_000_000;
        let bucket_key = ts_secs / BUCKET_SECS;
        buckets
            .entry(bucket_key)
            .or_default()
            .push((id.clone(), content.clone()));
    }

    // ── Build clusters (min cluster size = 2) ────────────────────────────
    let mut clusters: Vec<TemporalClusterResult> = Vec::new();
    for (bucket_key, items) in &buckets {
        if items.len() < 2 {
            continue;
        }
        let start_time = bucket_key * BUCKET_SECS;
        let end_time = start_time + BUCKET_SECS;

        // Extract top‑5 summary terms
        let mut term_counts: HashMap<String, usize> = HashMap::new();
        for (_, content) in items {
            let tokens = tokenize(content);
            let unique: std::collections::HashSet<&str> =
                tokens.iter().map(|s| s.as_str()).collect();
            for t in unique {
                *term_counts.entry(t.to_string()).or_insert(0) += 1;
            }
        }
        let mut terms: Vec<(String, usize)> = term_counts.into_iter().collect();
        terms.sort_by_key(|b| std::cmp::Reverse(b.1));
        let summary_terms: Vec<String> = terms.into_iter().take(5).map(|(t, _)| t).collect();

        let memory_ids: Vec<String> = items.iter().map(|(id, _)| id.clone()).collect();

        clusters.push(TemporalClusterResult {
            id: uuid_v4_uniq(ctx, |id| ctx.db.temporal_cluster_result().id().find(id).is_none(), 3),
            workspace_id: workspace_id.clone(),
            start_time,
            end_time,
            count: memory_ids.len() as u64,
            memory_ids: serde_json::to_string(&memory_ids).unwrap_or_else(|_| "[]".to_string()),
            summary_terms: serde_json::to_string(&summary_terms).unwrap_or_else(|_| "[]".to_string()),
            created_at: now,
        });
    }

    // Sort by start_time descending (most recent first)
    clusters.sort_by_key(|b| std::cmp::Reverse(b.start_time));

    // ── Compute‑and‑store: clear old, write new ──────────────────────────
    cleanup_temporal_clusters(ctx, &workspace_id);
    for cluster in clusters {
        ctx.db.temporal_cluster_result().insert(cluster);
    }

    Ok(())
}

/// Delete all temporal cluster results for a workspace.
fn cleanup_temporal_clusters(ctx: &ReducerContext, workspace_id: &str) {
    let stale: Vec<String> = ctx
        .db
        .temporal_cluster_result()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id)
        .map(|r| r.id.clone())
        .collect();
    for sid in stale {
        ctx.db.temporal_cluster_result().id().delete(sid);
    }
}

// ---------------------------------------------------------------------------
// Reducer: detect_entity_cooccurrences
// ---------------------------------------------------------------------------

/// Find entity co‑occurrence patterns — pairs of entities that frequently
/// appear together in the same memory.
///
/// Reads entity references from `entities_json` (JSON array of
/// `{"type": "...", "name": "..."}` objects). Bounded by `crate::MAX_RESULTS`.
#[reducer]
pub fn detect_entity_cooccurrences(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);

    // ── Collect active memories with entity annotations ───────────────────
    let entity_memories: Vec<Vec<String>> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .map(|m| extract_entities_from_json(&m.entities_json))
        .filter(|entities| entities.len() >= 2)
        .collect();

    let total_docs = entity_memories.len();
    if total_docs < 2 {
        cleanup_entity_cooccurrences(ctx, &workspace_id);
        return Ok(());
    }

    // ── Count co‑occurrences ──────────────────────────────────────────────
    use std::collections::HashMap;
    let mut co_occur: HashMap<(String, String), u64> = HashMap::new();

    for entities in &entity_memories {
        let mut sorted = entities.clone();
        sorted.sort();
        sorted.dedup();
        for i in 0..sorted.len() {
            for j in (i + 1)..sorted.len() {
                let pair = (sorted[i].clone(), sorted[j].clone());
                *co_occur.entry(pair).or_insert(0) += 1;
            }
        }
    }

    // ── Build results (min co‑occurrence count = 2) ────────────────────────
    let mut results: Vec<EntityCooccurrenceResult> = Vec::new();
    for ((entity_a, entity_b), count) in co_occur {
        if count < 2 {
            continue;
        }
        let strength = count as f64 / total_docs as f64;
        results.push(EntityCooccurrenceResult {
            id: uuid_v4_uniq(ctx, |id| ctx.db.entity_cooccurrence_result().id().find(id).is_none(), 3),
            workspace_id: workspace_id.clone(),
            entity_a,
            entity_b,
            count,
            strength: (strength * 1000.0).round() / 1000.0, // 3 decimal places
            created_at: now,
        });
    }

    results.sort_by_key(|b| std::cmp::Reverse(b.count));

    // ── Compute‑and‑store: clear old, write new ──────────────────────────
    cleanup_entity_cooccurrences(ctx, &workspace_id);
    for r in results {
        ctx.db.entity_cooccurrence_result().insert(r);
    }

    Ok(())
}

/// Delete all entity co‑occurrence results for a workspace.
fn cleanup_entity_cooccurrences(ctx: &ReducerContext, workspace_id: &str) {
    let stale: Vec<String> = ctx
        .db
        .entity_cooccurrence_result()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id)
        .map(|r| r.id.clone())
        .collect();
    for sid in stale {
        ctx.db.entity_cooccurrence_result().id().delete(sid);
    }
}

// ---------------------------------------------------------------------------
// Reducer: detect_topic_clusters
// ---------------------------------------------------------------------------

/// Find topic clusters — groups of memories organised by shared term frequency.
///
/// Identifies the top‑N most frequent terms across all memories, then groups
/// memories that contain each top term. Bounded by `crate::MAX_RESULTS`.
#[reducer]
pub fn detect_topic_clusters(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);

    // ── Collect active memories for this workspace ───────────────────────
    let memories: Vec<(String, String, f64)> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .map(|m| (m.id.clone(), m.content.clone(), m.confidence))
        .collect();

    if memories.is_empty() {
        cleanup_topic_clusters(ctx, &workspace_id);
        return Ok(());
    }

    // ── Compute term frequency across documents ──────────────────────────
    use std::collections::HashMap;
    let mut doc_freq: HashMap<String, usize> = HashMap::new();
    let mut mem_by_term: HashMap<String, Vec<(String, f64)>> = HashMap::new();

    for (id, content, confidence) in &memories {
        let tokens = tokenize(content);
        let unique: std::collections::HashSet<&str> =
            tokens.iter().map(|s| s.as_str()).collect();
        for t in unique {
            *doc_freq.entry(t.to_string()).or_insert(0) += 1;
            mem_by_term
                .entry(t.to_string())
                .or_default()
                .push((id.clone(), *confidence));
        }
    }

    // ── Select top terms (min doc frequency = 2) as topic candidates ─────
    let mut term_list: Vec<(String, usize)> = doc_freq.into_iter().collect();
    term_list.sort_by_key(|b| std::cmp::Reverse(b.1));
    // Top 15 terms that appear in at least 2 documents
    let top_terms: Vec<(String, usize)> = term_list
        .into_iter()
        .filter(|(_, count)| *count >= 2)
        .take(15)
        .collect();

    if top_terms.is_empty() {
        cleanup_topic_clusters(ctx, &workspace_id);
        return Ok(());
    }

    // ── Build topic clusters (each cluster = memories sharing a top term) ─────
    let mut clusters: Vec<TopicClusterResult> = Vec::new();
    for (topic, _) in &top_terms {
        if let Some(mems) = mem_by_term.get(topic) {
            let total_conf: f64 = mems.iter().map(|(_, c)| c).sum();
            let avg_conf = total_conf / mems.len() as f64;
            let mem_ids: Vec<String> = mems.iter().map(|(id, _)| id.clone()).collect();

            // Top terms for this cluster: which terms co‑occur most with this topic
            let mut cluster_term_counts: HashMap<String, usize> = HashMap::new();
            for (mem_id, _) in mems {
                if let Some((_, content, _)) = memories.iter().find(|(id, _, _)| id == mem_id) {
                    let tokens = tokenize(content);
                    for t in tokens {
                        *cluster_term_counts.entry(t).or_insert(0) += 1;
                    }
                }
            }
            let mut sorted_terms: Vec<(String, usize)> = cluster_term_counts.into_iter().collect();
            sorted_terms.sort_by_key(|b| std::cmp::Reverse(b.1));
            let top_cluster_terms: Vec<String> = sorted_terms
                .into_iter()
                .take(10)
                .map(|(t, _)| t)
                .collect();

            // Only create a cluster if it has at least 2 memories
            if mem_ids.len() >= 2 {
                clusters.push(TopicClusterResult {
                    id: uuid_v4_uniq(ctx, |id| ctx.db.topic_cluster_result().id().find(id).is_none(), 3),
                    workspace_id: workspace_id.clone(),
                    topic: topic.clone(),
                    count: mem_ids.len() as u64,
                    memory_ids: serde_json::to_string(&mem_ids).unwrap_or_else(|_| "[]".to_string()),
                    top_terms: serde_json::to_string(&top_cluster_terms).unwrap_or_else(|_| "[]".to_string()),
                    avg_confidence: (avg_conf * 1000.0).round() / 1000.0,
                    created_at: now,
                });
            }
        }
    }

    // Sort by count descending (largest clusters first)
    clusters.sort_by_key(|b| std::cmp::Reverse(b.count));

    // ── Compute‑and‑store: clear old, write new ──────────────────────────
    cleanup_topic_clusters(ctx, &workspace_id);
    for cluster in clusters {
        ctx.db.topic_cluster_result().insert(cluster);
    }

    Ok(())
}

/// Delete all topic cluster results for a workspace.
fn cleanup_topic_clusters(ctx: &ReducerContext, workspace_id: &str) {
    let stale: Vec<String> = ctx
        .db
        .topic_cluster_result()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id)
        .map(|r| r.id.clone())
        .collect();
    for sid in stale {
        ctx.db.topic_cluster_result().id().delete(sid);
    }
}

// ---------------------------------------------------------------------------
// Anomaly detection — statistical outlier identification
// ---------------------------------------------------------------------------

/// An identified anomaly — a memory deviating from workspace norms.
#[table(accessor = anomaly_result)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AnomalyResult {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    /// The anomalous memory's ID
    pub memory_id: String,
    /// Type of anomaly: "confidence_outlier" | "length_outlier" | "entity_outlier"
    pub anomaly_type: String,
    /// The metric value that triggered (e.g., confidence score, content length)
    pub metric_value: f64,
    /// Z-score absolute value (how many std devs from mean)
    pub z_score: f64,
    /// Brief description of the anomaly
    pub description: String,
    pub created_at: i64,
}

/// Clear stale anomaly results for a workspace.
fn cleanup_anomalies(ctx: &ReducerContext, workspace_id: &str) {
    let stale: Vec<String> = ctx
        .db
        .anomaly_result()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|r| r.workspace_id == workspace_id)
        .map(|r| r.id.clone())
        .collect();
    for sid in stale {
        ctx.db.anomaly_result().id().delete(sid);
    }
}

/// Compute mean and standard deviation for a slice of f64 values.
/// Returns (mean, std_dev) — std_dev is 0.0 for n < 2.
fn mean_std(values: &[f64]) -> (f64, f64) {
    let n = values.len() as f64;
    if n < 2.0 {
        return (values.iter().sum::<f64>() / n.max(1.0), 0.0);
    }
    let mean = values.iter().sum::<f64>() / n;
    let variance = values.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / (n - 1.0);
    let std_dev = variance.sqrt();
    (mean, std_dev)
}

/// Detect statistical anomalies among active memories in a workspace.
///
/// Three types:
/// - **confidence_outlier**: memory confidence > 3σ from workspace mean
/// - **length_outlier**: content length > 3σ from workspace mean
/// - **entity_outlier**: unusually many or few entities (> 3σ)
///
/// Uses compute-and-store pattern, bounded by `crate::MAX_RESULTS`.
#[reducer]
pub fn detect_anomalies(ctx: &ReducerContext, workspace_id: String) -> Result<(), String> {
    let _admin = crate::auth::require_admin(ctx)?;
    let now = now_micros(ctx);

    // Collect active memories for this workspace
    let memories: Vec<(String, String, f64, i64, String)> = ctx
        .db
        .memory()
        .iter()
        .take(crate::MAX_RESULTS)
        .filter(|m| m.workspace_id == workspace_id && m.is_active)
        .map(|m| {
            let entities_count = if m.entities_json.is_empty() || m.entities_json == "[]" {
                0
            } else {
                serde_json::from_str::<Vec<serde_json::Value>>(&m.entities_json)
                    .map(|v| v.len())
                    .unwrap_or(0)
            };
            (m.id.clone(), m.content.clone(), m.confidence, entities_count as i64, m.entities_json.clone())
        })
        .collect();

    if memories.len() < 3 {
        // Not enough data for meaningful anomaly detection
        cleanup_anomalies(ctx, &workspace_id);
        return Ok(());
    }

    // Compute metrics
    let confidences: Vec<f64> = memories.iter().map(|m| m.2).collect();
    let lengths: Vec<f64> = memories.iter().map(|m| m.1.len() as f64).collect();
    let entity_counts: Vec<f64> = memories.iter().map(|m| m.3 as f64).collect();

    let (conf_mean, conf_std) = mean_std(&confidences);
    let (len_mean, len_std) = mean_std(&lengths);
    let (ent_mean, ent_std) = mean_std(&entity_counts);

    // Clear previous results
    cleanup_anomalies(ctx, &workspace_id);

    let mut anomaly_count = 0u32;

    for (mid, content, confidence, entity_count, _entities_json) in &memories {
        // Confidence outliers
        if conf_std > 0.01 {
            let conf_z = (confidence - conf_mean).abs() / conf_std;
            if conf_z > 3.0 {
                let desc = if *confidence > conf_mean {
                    format!("Unusually high confidence ({:.2}) vs workspace mean ({:.2})", confidence, conf_mean)
                } else {
                    format!("Unusually low confidence ({:.2}) vs workspace mean ({:.2})", confidence, conf_mean)
                };
                ctx.db.anomaly_result().insert(AnomalyResult {
                    id: crate::uuid_v4_uniq(ctx, |id| ctx.db.anomaly_result().id().find(id.clone()).is_none(), 3),
                    workspace_id: workspace_id.clone(),
                    memory_id: mid.clone(),
                    anomaly_type: "confidence_outlier".to_string(),
                    metric_value: *confidence,
                    z_score: conf_z,
                    description: desc,
                    created_at: now,
                });
                anomaly_count += 1;
            }
        }

        // Length outliers
        if len_std > 1.0 {
            let len_z = (content.len() as f64 - len_mean).abs() / len_std;
            if len_z > 3.0 {
                let desc = if content.len() as f64 > len_mean {
                    format!("Unusually long content ({} chars) vs workspace mean ({:.0} chars)", content.len(), len_mean)
                } else {
                    format!("Unusually short content ({} chars) vs workspace mean ({:.0} chars)", content.len(), len_mean)
                };
                ctx.db.anomaly_result().insert(AnomalyResult {
                    id: crate::uuid_v4_uniq(ctx, |id| ctx.db.anomaly_result().id().find(id.clone()).is_none(), 3),
                    workspace_id: workspace_id.clone(),
                    memory_id: mid.clone(),
                    anomaly_type: "length_outlier".to_string(),
                    metric_value: content.len() as f64,
                    z_score: len_z,
                    description: desc,
                    created_at: now,
                });
                anomaly_count += 1;
            }
        }

        // Entity count outliers
        if ent_std > 0.5 {
            let ent_z = (*entity_count as f64 - ent_mean).abs() / ent_std;
            if ent_z > 3.0 {
                let desc = if *entity_count as f64 > ent_mean {
                    format!("Unusually many entities ({}) vs workspace mean ({:.1})", entity_count, ent_mean)
                } else {
                    format!("Unusually few entities ({}) vs workspace mean ({:.1})", entity_count, ent_mean)
                };
                ctx.db.anomaly_result().insert(AnomalyResult {
                    id: crate::uuid_v4_uniq(ctx, |id| ctx.db.anomaly_result().id().find(id.clone()).is_none(), 3),
                    workspace_id: workspace_id.clone(),
                    memory_id: mid.clone(),
                    anomaly_type: "entity_outlier".to_string(),
                    metric_value: *entity_count as f64,
                    z_score: ent_z,
                    description: desc,
                    created_at: now,
                });
                anomaly_count += 1;
            }
        }

        // Cap total anomalies to avoid flooding the result table
        if anomaly_count >= 100 {
            break;
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // ── tokenize ──────────────────────────────────────────────────────────

    #[test]
    fn test_tokenize_basic() {
        let tokens = tokenize("hello world");
        assert_eq!(tokens, vec!["hello", "world"]);
    }

    #[test]
    fn test_tokenize_filter_short() {
        let tokens = tokenize("a an to the big cat");
        assert!(!tokens.contains(&"a".to_string()));
        assert!(!tokens.contains(&"an".to_string()));
        assert!(!tokens.contains(&"to".to_string()));
        assert!(tokens.contains(&"big".to_string()));
        assert!(tokens.contains(&"cat".to_string()));
    }

    #[test]
    fn test_tokenize_punctuation() {
        let tokens = tokenize("hello, world! how's it going?");
        assert!(tokens.contains(&"hello".to_string()));
        assert!(tokens.contains(&"world".to_string()));
    }

    #[test]
    fn test_tokenize_empty() {
        let tokens = tokenize("");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_tokenize_lowercase() {
        let tokens = tokenize("Hello WORLD");
        assert_eq!(tokens, vec!["hello", "world"]);
    }

    // ── extract_entities_from_json ────────────────────────────────────────

    #[test]
    fn test_extract_entities_empty() {
        assert!(extract_entities_from_json("").is_empty());
        assert!(extract_entities_from_json("[]").is_empty());
    }

    #[test]
    fn test_extract_entities_basic() {
        let json = r#"[{"type":"person","name":"Alice"},{"type":"concept","name":"RLHF"}]"#;
        let entities = extract_entities_from_json(json);
        assert_eq!(entities, vec!["alice", "rlhf"]);
    }

    #[test]
    fn test_extract_entities_missing_name() {
        let json = r#"[{"type":"person"}]"#;
        let entities = extract_entities_from_json(json);
        assert!(entities.is_empty());
    }

    #[test]
    fn test_extract_entities_invalid_json() {
        let entities = extract_entities_from_json("not json");
        assert!(entities.is_empty());
    }

    #[test]
    fn test_extract_entities_case_normalization() {
        let json = r#"[{"type":"person","name":"Alice Smith"},{"type":"org","name":"OpenAI"}]"#;
        let entities = extract_entities_from_json(json);
        assert_eq!(entities, vec!["alice smith", "openai"]);
    }

    // ── mean_std ──────────────────────────────────────────────────────────

    #[test]
    fn test_mean_std_constant_values() {
        // All values the same → std_dev = 0
        let (mean, std) = mean_std(&[5.0, 5.0, 5.0]);
        assert!((mean - 5.0).abs() < 1e-10);
        assert!((std - 0.0).abs() < 1e-10);
    }

    #[test]
    fn test_mean_std_normal_distribution() {
        let values = vec![1.0, 2.0, 3.0, 4.0, 5.0];
        let (mean, std) = mean_std(&values);
        assert!((mean - 3.0).abs() < 1e-10);
        // sample std dev = sqrt(2.5) ≈ 1.581
        assert!((std - 1.58113883).abs() < 1e-6);
    }

    #[test]
    fn test_mean_std_single_value() {
        let (mean, std) = mean_std(&[42.0]);
        assert!((mean - 42.0).abs() < 1e-10);
        assert!((std - 0.0).abs() < 1e-10);
    }

    #[test]
    fn test_mean_std_empty_slice() {
        let (mean, std) = mean_std(&[]);
        assert!((mean - 0.0).abs() < 1e-10);
        assert!((std - 0.0).abs() < 1e-10);
    }

    #[test]
    fn test_mean_std_two_values() {
        let values = vec![10.0, 20.0];
        let (mean, std) = mean_std(&values);
        assert!((mean - 15.0).abs() < 1e-10);
        assert!((std - 7.0710678118654755).abs() < 1e-6);
    }
}