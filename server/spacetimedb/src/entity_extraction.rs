//! Zero-LLM entity extraction from memory content.
//!
//! GBrain-style regex-based extraction: finds person names, company names,
//! and creates entity_link records + kg_edges between co-mentioned entities.
//!
//! Called automatically from ``store_memory`` — no separate reducer needed
//! in normal operation.  The ``extract_entities`` reducer is public for
//! manual re-extraction of existing memories.

use spacetimedb::*;

use crate::auth::require_auth;
use crate::entity_linking::{entity_link, EntityLink};
use crate::knowledge_graph::{kg_edge, kg_node, KgEdge, KgNode};
use crate::workspace::check_space_access;
use crate::{now_micros, uuid_v4};

// ---------------------------------------------------------------------------
// Pattern matching (no regex crate — SpacetimeDB WASM constraint)
// ---------------------------------------------------------------------------

/// Known company suffixes (case-insensitive match).
const COMPANY_SUFFIXES: &[&str] = &[
    "Inc", "Corp", "LLC", "Ltd", "GmbH", "SaaS",
    "AI", "Labs", "Technologies", "Ventures", "Capital",
    "Partners", "Group", "Holdings", "Enterprises", "Studios",
    "Software", "Systems", "Networks", "Analytics", "Robotics",
];

/// Return whether a word looks like a company suffix.
fn is_company_suffix(word: &str) -> bool {
    COMPANY_SUFFIXES
        .iter()
        .any(|s| word.eq_ignore_ascii_case(s))
}

/// Check that a string looks like a proper name (starts uppercase, rest lowercase).
fn is_proper_word(s: &str) -> bool {
    let mut chars = s.chars();
    match chars.next() {
        Some(c) if c.is_ascii_uppercase() => chars.all(|c| c.is_ascii_lowercase()),
        _ => false,
    }
}

/// Score how likely a candidate is to be a real entity (not a common word).
fn entity_score(word: &str) -> i32 {
    let lower = word.to_lowercase();
    let noise: &[&str] = &[
        "the", "and", "for", "with", "this", "that", "from", "have",
        "been", "was", "are", "has", "had", "not", "but", "its", "his",
        "her", "she", "they", "will", "would", "could", "should", "there",
        "their", "about", "which", "when", "where", "what", "into", "over",
    ];
    if noise.contains(&lower.as_str()) {
        return 0;
    }
    if lower.len() < 3 {
        return 0;
    }
    1
}

// ---------------------------------------------------------------------------
// Extraction
// ---------------------------------------------------------------------------

/// Extracted entity mention.
#[derive(Debug, Clone)]
struct Mention {
    name: String,
    entity_type: String, // "person" or "company"
}

/// Extract person names from text (two-word capitalized pairs like "Garry Tan").
fn extract_people(text: &str) -> Vec<Mention> {
    let mut people = Vec::new();
    let words: Vec<&str> = text.split_whitespace().collect();

    for window in words.windows(2) {
        if is_proper_word(window[0]) && is_proper_word(window[1]) {
            let name = format!("{} {}", window[0], window[1]);
            // Filter obvious false positives
            if entity_score(window[0]) > 0 && entity_score(window[1]) > 0 {
                // Avoid "I The", "A New" patterns
                if window[0].len() > 1 && window[1].len() > 2 {
                    people.push(Mention {
                        name,
                        entity_type: "person".into(),
                    });
                }
            }
        }
    }
    people
}

/// Extract company names from text (capitalized sequence ending in known suffix).
fn extract_companies(text: &str) -> Vec<Mention> {
    let mut companies = Vec::new();
    let words: Vec<&str> = text.split_whitespace().collect();

    for (i, word) in words.iter().enumerate() {
        let stripped = word.trim_end_matches(|c: char| c == '.' || c == ',');
        if is_company_suffix(stripped) && i > 0 {
            // Walk backward to find the full company name
            let start = (0..i)
                .rev()
                .take_while(|&j| {
                    let w = words[j].trim_end_matches(|c: char| c == ',' || c == '.');
                    w.chars().next().map_or(false, |c| c.is_ascii_uppercase())
                })
                .last()
                .unwrap_or(i.saturating_sub(1));

            let name_words: Vec<&str> = words[start..=i]
                .iter()
                .map(|w| w.trim_end_matches(|c: char| c == ',' || c == '.'))
                .collect();

            if name_words.len() >= 2 {
                let name = name_words.join(" ");
                companies.push(Mention {
                    name,
                    entity_type: "company".into(),
                });
            }
        }
    }
    companies
}

/// Create or find entity records (entity_link + kg_node) for a mention.
/// Returns the kg_node ID for edge creation.
fn ensure_entity(
    ctx: &ReducerContext,
    workspace_id: &str,
    mention: &Mention,
    now: i64,
) -> String {
    // Check existing entity_link by exact name match
    let mut link_id: Option<String> = None;
    for existing in ctx.db.entity_link().iter().take(crate::MAX_RESULTS) {
        if existing.workspace_id == workspace_id && existing.entity_name == mention.name {
            link_id = Some(existing.id.clone());
            break;
        }
    }

    // Check existing kg_node by label match
    for existing in ctx.db.kg_node().iter().take(crate::MAX_RESULTS) {
        if existing.workspace_id == workspace_id && existing.label == mention.name {
            // Found existing node — ensure entity_link exists too
            if link_id.is_none() {
                let eid = uuid_v4(ctx);
                let link = EntityLink {
                    id: eid.clone(),
                    workspace_id: workspace_id.into(),
                    entity_name: mention.name.clone(),
                    entity_type: mention.entity_type.clone(),
                    aliases_json: "[]".into(),
                    description: "auto-extracted".into(),
                    created_at: now,
                };
                ctx.db.entity_link().insert(link);
            }
            return existing.id;
        }
    }

    // Create new entity_link if needed
    let needs_link = link_id.is_none();
    let eid = if let Some(id) = link_id { id } else { uuid_v4(ctx) };
    if needs_link {
        let link = EntityLink {
            id: eid.clone(),
            workspace_id: workspace_id.into(),
            entity_name: mention.name.clone(),
            entity_type: mention.entity_type.clone(),
            aliases_json: "[]".into(),
            description: "auto-extracted".into(),
            created_at: now,
        };
        ctx.db.entity_link().insert(link);
    }

    // Create new kg_node
    let nid = uuid_v4(ctx);
    let node = KgNode {
        id: nid.clone(),
        workspace_id: workspace_id.into(),
        label: mention.name.clone(),
        node_type: mention.entity_type.clone(),
        summary: format!("auto-extracted {}", mention.entity_type),
        metadata_json: "{}".into(),
        source_memory_id: String::new(),
        community_id: 0,
        embedding_json: "[]".into(),
        created_at: now,
    };
    ctx.db.kg_node().insert(node);
    nid
}

/// Create an edge between two entities in the knowledge graph.
fn create_edge(
    ctx: &ReducerContext,
    workspace_id: &str,
    source_id: &str,
    target_id: &str,
    relation: &str,
    now: i64,
) {
    let id = uuid_v4(ctx);
    let edge = KgEdge {
        id,
        workspace_id: workspace_id.into(),
        source_node_id: source_id.into(),
        target_node_id: target_id.into(),
        relation: relation.into(),
        weight: 0.5,
        confidence: "LOW".into(),
        metadata_json: "{}".into(),
        source_memory_id: String::new(),
        created_at: now,
        valid_at: now,
        invalid_at: 0,
        version: 1,
        edge_group_id: "".into(),
    };
    ctx.db.kg_edge().insert(edge);
}

// ---------------------------------------------------------------------------
// Public reducer
// ---------------------------------------------------------------------------

/// Extract entities from text and link them in the entity graph.
///
/// Called automatically from ``store_memory``.  Also exposed as a public
/// reducer for re-extraction of existing memories.
///
/// Args:
///     workspace_id: Target workspace.
///     content: The text to scan for entity mentions.
#[reducer]
pub fn extract_entities(
    ctx: &ReducerContext,
    workspace_id: String,
    content: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);

    let people = extract_people(&content);
    let companies = extract_companies(&content);
    let all_mentions: Vec<Mention> = people
        .into_iter()
        .chain(companies.into_iter())
        .collect();

    if all_mentions.is_empty() {
        return Ok(());
    }

    // Ensure entity_link records for each mention
    let mut entity_ids: Vec<(String, String)> = Vec::new(); // (id, entity_type)
    for mention in &all_mentions {
        let eid = ensure_entity(ctx, &workspace_id, mention, now);
        entity_ids.push((eid, mention.entity_type.clone()));
    }

    // Create co-mention edges between entities found in the same text
    for i in 0..entity_ids.len() {
        for j in (i + 1)..entity_ids.len() {
            let relation = match (entity_ids[i].1.as_str(), entity_ids[j].1.as_str()) {
                ("person", "company") => "mentioned_with_company",
                ("company", "person") => "mentioned_with_person",
                ("person", "person") => "co_mentioned_person",
                _ => "co_mentioned",
            };
            create_edge(
                ctx,
                &workspace_id,
                &entity_ids[i].0,
                &entity_ids[j].0,
                relation,
                now,
            );
        }
    }

    log::info!(
        "extract_entities: {} mentions → {} edges for workspace {}",
        all_mentions.len(),
        entity_ids.len().saturating_sub(1) * entity_ids.len() / 2,
        &workspace_id[..16.min(workspace_id.len())],
    );
    Ok(())
}
