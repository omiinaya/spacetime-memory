//! Lightweight HNSW (Hierarchical Navigable Small World) index for vector search.
//!
//! Pure Rust implementation with zero external dependencies beyond serde.
//! Provides approximate nearest neighbor search over f32 embeddings.
//!
//! Reference: https://arxiv.org/abs/1603.09320

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// Maximum number of connections per element per layer (M)
const M: usize = 16;

/// Number of candidates to consider during construction (ef_construction)
const EF_CONSTRUCTION: usize = 200;

/// Number of candidates to consider during search (ef_search)
const EF_SEARCH: usize = 100;

/// Level generation multiplier (1 / ln(M))
// ln(16) ≈ 2.7726, so ML = 1/ln(M) ≈ 0.3607

/// Maximum number of levels
const MAX_LEVELS: usize = 16;

// ---------------------------------------------------------------------------
// Simple xorshift64 PRNG (no external dependency)
// ---------------------------------------------------------------------------

struct SimpleRng(u64);

impl SimpleRng {
    fn new() -> Self {
        Self(0x9e3779b97f4a7c15)
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }

    fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / 9007199254740992.0)
    }
}

/// Generate a random level for a new element.
fn random_level() -> usize {
    let mut rng = SimpleRng::new();
    let r: f64 = rng.next_f64();
    let level = (-r.ln() * 0.36067376022224085).floor() as usize;
    level.min(MAX_LEVELS)
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/// A single vector entry in the HNSW graph.
#[derive(Clone, Serialize, Deserialize)]
pub struct HnswEntry {
    /// Unique entity ID for this vector
    pub entity_id: String,
    /// The embedding vector
    pub vector: Vec<f32>,
    /// Hierarchical neighbor lists: layers[level] = Vec<node_id>
    pub layers: Vec<Vec<usize>>,
}

/// The HNSW graph index.
#[derive(Serialize, Deserialize)]
pub struct HnswGraph {
    /// All entries indexed by their node ID
    pub entries: Vec<HnswEntry>,
    /// Map from entity_id -> node_id for fast lookup
    pub entity_to_node: HashMap<String, usize>,
    /// The entry point (top-level node)
    pub entry_point: Option<usize>,
    /// Current maximum level in the graph
    pub max_level: usize,
}

#[allow(dead_code)]
impl HnswGraph {
    /// Create a new empty HNSW graph.
    pub fn new() -> Self {
        Self {
            entries: Vec::new(),
            entity_to_node: HashMap::new(),
            entry_point: None,
            max_level: 0,
        }
    }

    /// Insert or update a vector in the HNSW graph.
    /// Returns the node ID.
    pub fn insert(&mut self, entity_id: &str, vector: Vec<f32>) -> usize {
        if let Some(&node_id) = self.entity_to_node.get(entity_id) {
            self.entries[node_id].vector = vector;
            return node_id;
        }

        let node_id = self.entries.len();
        let level = random_level();

        let entry = HnswEntry {
            entity_id: entity_id.to_string(),
            vector,
            layers: vec![Vec::new(); level + 1],
        };

        self.entries.push(entry);
        self.entity_to_node.insert(entity_id.to_string(), node_id);

        if self.entry_point.is_none() || level > self.max_level {
            if level > self.max_level {
                self.max_level = level;
            }
            self.entry_point = Some(node_id);
            return node_id;
        }

        let mut curr = self.entry_point.unwrap();
        if level < self.max_level {
            for lvl in (level + 1..=self.max_level).rev() {
                let mut changed = true;
                while changed {
                    changed = false;
                    let curr_vec = &self.entries[curr].vector.clone();
                    if lvl < self.entries[curr].layers.len() {
                        let neighbors = self.entries[curr].layers[lvl].clone();
                        for &neighbor in &neighbors {
                            let d = euclidean_distance(
                                &self.entries[neighbor].vector,
                                &self.entries[node_id].vector,
                            );
                            let curr_d = euclidean_distance(curr_vec, &self.entries[node_id].vector);
                            if d < curr_d {
                                curr = neighbor;
                                changed = true;
                                break;
                            }
                        }
                    }
                }
            }
        }

        for lvl in (0..=level.min(self.max_level)).rev() {
            let candidates = self.search_layer(curr, &self.entries[node_id].vector, lvl, EF_CONSTRUCTION);
            let neighbors = Self::select_neighbors(candidates, if lvl == 0 { M * 2 } else { M });

            for &neighbor_id in &neighbors {
                if lvl < self.entries[neighbor_id].layers.len() {
                    self.entries[node_id].layers[lvl].push(neighbor_id);
                    self.entries[neighbor_id].layers[lvl].push(node_id);
                }
            }

            if !neighbors.is_empty() {
                curr = neighbors[0];
            }
        }

        node_id
    }

    /// Delete an entry by entity_id.
    pub fn delete(&mut self, entity_id: &str) -> bool {
        if let Some(node_id) = self.entity_to_node.remove(entity_id) {
            for (neighbor_id, entry) in self.entries.iter_mut().enumerate() {
                if neighbor_id == node_id {
                    continue;
                }
                for layer in &mut entry.layers {
                    layer.retain(|&x| x != node_id);
                }
            }
            if let Some(entry) = self.entries.get_mut(node_id) {
                entry.layers.clear();
            }
            if self.entry_point == Some(node_id) {
                self.entry_point = self.entries.iter().enumerate()
                    .find(|(id, e)| *id != node_id && !e.layers.is_empty())
                    .map(|(id, _)| id);
                if let Some(ep) = self.entry_point {
                    self.max_level = self.entries[ep].layers.len().saturating_sub(1);
                }
            }
            true
        } else {
            false
        }
    }

    /// Search for the k nearest neighbors of a query vector.
    pub fn search(&self, query: &[f32], k: usize) -> Vec<(String, f32)> {
        if self.entries.is_empty() || self.entry_point.is_none() {
            return Vec::new();
        }

        let ef = EF_SEARCH.max(k);
        let ep = self.entry_point.unwrap();

        let mut curr = ep;
        for lvl in (1..=self.max_level).rev() {
            if lvl >= self.entries[curr].layers.len() {
                continue;
            }
            let mut changed = true;
            while changed {
                changed = false;
                let neighbors = self.entries[curr].layers[lvl].clone();
                for &neighbor in &neighbors {
                    let d = euclidean_distance(&self.entries[neighbor].vector, query);
                    let curr_d = euclidean_distance(&self.entries[curr].vector, query);
                    if d < curr_d {
                        curr = neighbor;
                        changed = true;
                        break;
                    }
                }
            }
        }

        self.search_layer(curr, query, 0, ef)
            .into_iter()
            .map(|node_id| {
                let d = euclidean_distance(&self.entries[node_id].vector, query);
                (self.entries[node_id].entity_id.clone(), d)
            })
            .take(k)
            .collect()
    }

    /// Search a single layer, returning up to `ef` candidate node IDs.
    fn search_layer(&self, entry_point: usize, query: &[f32], layer: usize, ef: usize) -> Vec<usize> {
        let mut visited: std::collections::HashSet<usize> = std::collections::HashSet::new();
        let mut candidates: Vec<(f32, usize)> = Vec::new();
        let mut results: Vec<(f32, usize)> = Vec::new();

        let d = euclidean_distance(&self.entries[entry_point].vector, query);
        candidates.push((d, entry_point));
        visited.insert(entry_point);

        while !candidates.is_empty() {
            // Find closest candidate to query
            let mut best_idx = 0;
            let mut best_dist = candidates[0].0;
            for (idx, &(d, _)) in candidates.iter().enumerate() {
                if d < best_dist {
                    best_dist = d;
                    best_idx = idx;
                }
            }
            let (cand_dist, cand_id) = candidates.remove(best_idx);

            if results.len() >= ef {
                let furthest = results.last().map(|&(d, _)| d).unwrap_or(f32::MAX);
                if cand_dist > furthest {
                    break;
                }
            }

            results.push((cand_dist, cand_id));
            results.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
            results.truncate(ef);

            if layer < self.entries[cand_id].layers.len() {
                for &neighbor_id in &self.entries[cand_id].layers[layer] {
                    if visited.insert(neighbor_id) {
                        let d = euclidean_distance(&self.entries[neighbor_id].vector, query);
                        candidates.push((d, neighbor_id));
                    }
                }
            }
        }

        results.into_iter().map(|(_, id)| id).collect()
    }

    /// Select the top-k candidates.
    fn select_neighbors(mut candidates: Vec<usize>, k: usize) -> Vec<usize> {
        if candidates.len() > k {
            candidates.truncate(k);
        }
        candidates
    }

    /// Get the number of entries.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Check if empty.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

/// Compute Euclidean distance between two vectors.
fn euclidean_distance(a: &[f32], b: &[f32]) -> f32 {
    a.iter()
        .zip(b.iter())
        .map(|(x, y)| (x - y) * (x - y))
        .sum::<f32>()
        .sqrt()
}
