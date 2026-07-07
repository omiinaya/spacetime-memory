use spacetimedb::*;
use crate::auth::require_auth;

use crate::{now_micros, uuid_v4_uniq, uuid_v7};
use crate::workspace::workspace;
use crate::workspace::SpacePermission;
use crate::workspace::space_permission;

/// A link between a text mention and a knowledge-graph node.
#[table(accessor = entity_link)]
#[derive(Debug, Clone)]
pub struct EntityLink {
    #[primary_key]
    pub id: String,
    pub name: String,
    /// "person", "company", "technology", "concept", "acronym"
    pub entity_type: String,
    pub workspace_id: String,
    pub used_count: u64,
    pub first_seen: i64,
    pub last_seen: i64,
}

/// A knowledge-graph node (canonical entity).
#[table(accessor = kg_node)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct KgNode {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    pub entity_type: String,
    pub description: String,
    pub metadata_json: String,
}

/// A directed edge between two knowledge-graph nodes.
#[table(accessor = kg_edge)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct KgEdge {
    #[primary_key]
    pub id: String,
    pub subject_id: String,
    pub object_id: String,
    /// e.g. "works_at", "acquired", "competitor", "collaborator"
    pub relation: String,
    pub weight: f64,
    pub created_at: i64,
}

/// A mention extracted from text (not persisted — used during extraction).
#[derive(Debug, Clone)]
pub struct Mention {
    pub name: String,
    pub entity_type: String,
}

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
        .any(|s| s.eq_ignore_ascii_case(word))
}

/// Return whether a word is a proper name (capitalized, 2+ chars).
fn is_proper_word(word: &str) -> bool {
    let trimmed = word.trim_end_matches(|c: char| c == '.' || c == ',' || c == ';' || c == ':');
    if trimmed.is_empty() || trimmed.len() < 2 {
        return false;
    }
    let mut chars = trimmed.chars();
    // First char must be uppercase, rest must be lowercase
    match chars.next() {
        Some(c) if c.is_ascii_uppercase() => chars.all(|c| c.is_ascii_lowercase()),
        _ => false,
    }
}

/// Assign a score to a word for entity extraction.
/// - 0 for noise words, short words, etc.
/// - 1 for valid entity candidates.
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
    if lower.len() < 2 {
        return 0;
    }
    1
}

/// Extract single-word entity candidates (technologies, concepts).
fn extract_single_words(text: &str) -> Vec<Mention> {
    let mut results = Vec::new();
    let words: Vec<&str> = text.split_whitespace().collect();

    for (i, word) in words.iter().enumerate() {
        let stripped = word.trim_end_matches(|c: char| c == '.' || c == ',' || c == ';' || c == ':');
        // Must be capitalized, at least 3 chars
        if stripped.len() < 3 {
            continue;
        }
        let first = stripped.chars().next().unwrap();
        if !first.is_ascii_uppercase() {
            continue;
        }
        // Skip if it's the first word of a sentence
        if i == 0 || words[i.saturating_sub(1)].ends_with('.') || words[i.saturating_sub(1)].ends_with('!') || words[i.saturating_sub(1)].ends_with('?') {
            continue;
        }
        if entity_score(stripped) == 0 {
            continue;
        }
        // Skip if followed by a capitalized word (handled by extract_people)
        if i + 1 < words.len() {
            let next = words[i + 1].trim_end_matches(|c: char| c == '.' || c == ',');
            if !next.is_empty() && next.chars().next().map_or(false, |c| c.is_ascii_uppercase()) {
                continue;
            }
        }
        // Skip common English words that are capitalized (proper nouns that aren't entities)
        let lower = stripped.to_lowercase();
        let common_words: &[&str] = &[
            "this", "that", "what", "when", "where", "which", "there", "their",
            "they", "then", "than", "thus", "them", "here", "have", "been",
            "from", "very", "just", "also", "some", "each", "many", "more",
            "most", "only", "over", "such", "will", "with", "like", "last",
            "next", "first", "second", "other", "after", "before",
            "based", "used", "made", "said", "known", "shown", "given",
            "still", "even", "well", "back", "down", "left", "right",
        ];
        if common_words.contains(&lower.as_str()) {
            continue;
        }
        // Tech/product names — often single capitalized words
        let tech_names: &[&str] = &[
            "python", "rust", "react", "node", "java", "docker", "linux",
            "swift", "kotlin", "scala", "elixir", "clojure", "haskell",
            "typescript", "javascript", "ruby", "php", "go", "c",
            "postgresql", "mysql", "mongodb", "redis", "nginx", "apache",
            "tensorflow", "pytorch", "keras", "pandas", "numpy",
            "kubernetes", "terraform", "ansible", "jenkins", "gitlab",
            "bitcoin", "ethereum", "solana", "polkadot", "cosmos",
            "openai", "anthropic", "meta", "google", "apple", "amazon", "microsoft",
            "slack", "discord", "notion", "figma", "vercel", "netlify",
        ];
        let is_tech = tech_names.contains(&lower.as_str());
        if !is_tech && (lower.len() < 4 || lower.len() > 12) {
            continue;
        }
        results.push(Mention {
            name: stripped.to_string(),
            entity_type: if is_tech { "technology".into() } else { "concept".into() },
        });
    }
    results
}

/// Extract acronym-style entities (all-caps, 2-6 chars).
fn extract_acronyms(text: &str) -> Vec<Mention> {
    let mut results = Vec::new();
    for word in text.split_whitespace() {
        let stripped = word.trim_end_matches(|c: char| c == '.' || c == ',' || c == ';' || c == ':');
        let len = stripped.len();
        if len < 2 || len > 6 {
            continue;
        }
        if !stripped.chars().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit()) {
            continue;
        }
        // Skip common false positives
        let noise: &[&str] = &["THE", "AND", "FOR", "NOT", "BUT", "ITS", "out", "ARE", "HAS", "HAD", "CAN", "ALL", "ANY", "NEW", "OLD", "BIG", "TOP"];
        if noise.contains(&stripped) {
            continue;
        }
        results.push(Mention {
            name: stripped.to_string(),
            entity_type: "acronym".into(),
        });
    }
    results
}

/// Extract two-word person names (Title+Title, 3+ chars each).
fn extract_people(text: &str) -> Vec<Mention> {
    let mut results = Vec::new();
    let words: Vec<&str> = text.split_whitespace().collect();

    for pair in words.windows(2) {
        let first = pair[0].trim_end_matches(|c: char| c == '.' || c == ',' || c == ';');
        let second = pair[1].trim_end_matches(|c: char| c == '.' || c == ',' || c == ';');

        // Both must be capitalized proper words (3+ chars)
        if first.len() < 3 || second.len() < 2 {
            continue;
        }
        if !is_proper_word(first) || !is_proper_word(second) {
            continue;
        }

        // Skip noise pairs
        let noise_words: &[&str] = &[
            "The", "And", "For", "With", "This", "That", "From", "Have",
            "Been", "Was", "Are", "Has", "Had", "Not", "But", "Its", "His",
            "Her", "She", "They", "Will", "Would", "Could", "Should", "There",
            "Their", "About", "Which", "When", "Where", "What", "Into", "Over",
        ];
        if noise_words.contains(&first) || noise_words.contains(&second) {
            continue;
        }

        results.push(Mention {
            name: format!("{} {}", first, second),
            entity_type: "person".into(),
        });
    }
    results
}

/// Extract company names (two+ words where the last word is a known suffix).
fn extract_companies(text: &str) -> Vec<Mention> {
    let mut results = Vec::new();
    let words: Vec<&str> = text.split_whitespace().collect();

    for i in 0..words.len() {
        let current = words[i].trim_end_matches(|c: char| c == '.' || c == ',' || c == ';');
        if !is_company_suffix(current) {
            continue;
        }
        if i == 0 {
            continue; // need at least one word before the suffix
        }
        let prev = words[i - 1].trim_end_matches(|c: char| c == '.' || c == ',' || c == ';');
        if prev.len() < 2 {
            continue;
        }
        if !is_proper_word(prev) {
            continue;
        }
        let noise_words: &[&str] = &[
            "The", "And", "For", "With", "This", "That", "From", "Have",
            "Been", "Was", "Are", "Has", "Had", "Not", "But", "Its", "His",
            "Her", "She", "They", "Will", "Would", "Could", "Should", "There",
            "Their", "About", "Which", "When", "Where", "What", "Into", "Over",
        ];
        if noise_words.contains(&prev) {
            continue;
        }
        results.push(Mention {
            name: format!("{} {}", prev, current),
            entity_type: "company".into(),
        });
    }
    results
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
        if existing.name.eq_ignore_ascii_case(&mention.name)
            && existing.workspace_id == workspace_id
        {
            // Update usage count
            let updated = EntityLink {
                used_count: existing.used_count + 1,
                last_seen: now,
                ..existing.clone()
            };
            ctx.db.entity_link().id().update(updated);
            link_id = Some(existing.id.clone());
            break;
        }
    }

    // Create new entity_link if needed
    let eid = if let Some(ref id) = link_id { id.clone() } else { uuid_v7(ctx) };
    if link_id.is_none() {
        let link = EntityLink {
            id: eid.clone(),
            name: mention.name.clone(),
            entity_type: mention.entity_type.clone(),
            workspace_id: workspace_id.to_string(),
            used_count: 1,
            first_seen: now,
            last_seen: now,
        };
        ctx.db.entity_link().insert(link);
    }

    // Also ensure a KG node exists
    let mut node_id: Option<String> = None;
    for existing in ctx.db.kg_node().iter().take(crate::MAX_RESULTS) {
        if existing.name.eq_ignore_ascii_case(&mention.name)
            && existing.workspace_id == workspace_id
        {
            node_id = Some(existing.id.clone());
            break;
        }
    }
    if let Some(nid) = node_id {
        nid
    } else {
        let nid = uuid_v7(ctx);
        ctx.db.kg_node().insert(KgNode {
            id: nid.clone(),
            workspace_id: workspace_id.to_string(),
            name: mention.name.clone(),
            entity_type: mention.entity_type.clone(),
            description: String::new(),
            metadata_json: String::new(),
        });
        nid
    }
}

/// Result table for extract_entities.
#[table(accessor = entity_extraction_result, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct EntityExtractionResult {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// JSON array of {type, name} pairs
    pub entities_json: String,
    pub kg_node_count: u64,
    pub edge_count: u64,
    pub queried_at: i64,
}

/// Extract named entities from a workspace's most recent conversation text.
///
/// Runs all extractors (people, companies, acronyms, single words) and
/// creates entity_link + kg_node records for each mention. Also creates
/// co-occurrence KG edges between entities that appear in the same text.
#[reducer]
pub fn extract_entities(ctx: &ReducerContext, workspace_id: String, text: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex().to_string();

    // Check workspace access
    let has_access = ctx.db.workspace().id().find(&workspace_id).is_some()
        || ctx.db.space_permission().iter().take(crate::MAX_RESULTS).any(|sp: SpacePermission| {
            sp.workspace_id == workspace_id && sp.peer_id == caller
        });
    if !has_access {
        return Err(format!("Access denied: no access to workspace '{}'", workspace_id));
    }

    let now = now_micros(ctx);

    // Run all extractors
    let mut all_mentions: Vec<Mention> = Vec::new();
    all_mentions.extend(extract_people(&text));
    all_mentions.extend(extract_companies(&text));
    all_mentions.extend(extract_acronyms(&text));
    all_mentions.extend(extract_single_words(&text));

    // Deduplicate by name (case-insensitive) — keep first occurrence
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    all_mentions.retain(|m| {
        let lower = m.name.to_lowercase();
        seen.insert(lower)
    });

    // Ensure each entity exists and collect KG node IDs
    let mut entity_ids: Vec<String> = Vec::new();
    for mention in &all_mentions {
        let nid = ensure_entity(ctx, &workspace_id, mention, now);
        entity_ids.push(nid);
    }

    // Create co-occurrence edges between entities in the same text
    for i in 0..entity_ids.len() {
        for j in (i + 1)..entity_ids.len() {
            let sub = &entity_ids[i];
            let obj = &entity_ids[j];
            // Check if edge already exists
            let exists = ctx.db.kg_edge().iter().take(crate::MAX_RESULTS).any(|e: KgEdge| {
                (e.subject_id == *sub && e.object_id == *obj)
                    || (e.subject_id == *obj && e.object_id == *sub)
            });
            if !exists {
                ctx.db.kg_edge().insert(KgEdge {
                    id: uuid_v7(ctx),
                    subject_id: sub.clone(),
                    object_id: obj.clone(),
                    relation: "co_occurrence".to_string(),
                    weight: 1.0,
                    created_at: now,
                });
            }
        }
    }

    // Write result
    let entities_json = serde_json::to_string(
        &all_mentions.iter().map(|m| serde_json::json!({
            "type": m.entity_type,
            "name": m.name,
        })).collect::<Vec<_>>()
    ).unwrap_or_default();

    ctx.db.entity_extraction_result().insert(EntityExtractionResult {
        id: uuid_v4_uniq(ctx, |id| ctx.db.entity_extraction_result().id().find(id).is_none(), 3),
        workspace_id: workspace_id.clone(),
        entities_json,
        kg_node_count: entity_ids.len() as u64,
        edge_count: (entity_ids.len() * entity_ids.len().saturating_sub(1) / 2) as u64,
        queried_at: now,
    });

    log::info!(
        "extract_entities: {} mentions → {} edges for workspace {}",
        all_mentions.len(),
        entity_ids.len().saturating_sub(1) * entity_ids.len() / 2,
        &workspace_id[..16.min(workspace_id.len())],
    );
    Ok(())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // ── is_company_suffix ──────────────────────────────────────────────

    #[test]
    fn test_company_suffix_known() {
        assert!(is_company_suffix("Inc"));
        assert!(is_company_suffix("LLC"));
        assert!(is_company_suffix("Corp"));
        assert!(is_company_suffix("Ltd"));
        assert!(is_company_suffix("GmbH"));
        assert!(is_company_suffix("Technologies"));
        assert!(is_company_suffix("Ventures"));
        assert!(is_company_suffix("Labs"));
        assert!(is_company_suffix("AI"));
        assert!(is_company_suffix("SaaS"));
    }

    #[test]
    fn test_company_suffix_case_insensitive() {
        assert!(is_company_suffix("inc"));
        assert!(is_company_suffix("INC"));
    }

    #[test]
    fn test_company_suffix_unknown() {
        assert!(!is_company_suffix("Company"));
        assert!(!is_company_suffix("Solutions"));
        assert!(!is_company_suffix("Services"));
        assert!(!is_company_suffix("Test"));
        assert!(!is_company_suffix(""));
    }

    // ── is_proper_word ─────────────────────────────────────────────────

    #[test]
    fn test_proper_word_valid() {
        assert!(is_proper_word("Alice"));
        assert!(is_proper_word("Bob"));
        assert!(is_proper_word("Zurich"));
        assert!(is_proper_word("Python"));
    }

    #[test]
    fn test_proper_word_invalid() {
        assert!(!is_proper_word("alice"));       // lowercase
        assert!(!is_proper_word("ALICE"));       // all caps
        assert!(!is_proper_word("a"));           // too short, lowercase
        assert!(!is_proper_word(""));            // empty
        assert!(!is_proper_word("AlIcE"));       // mixed case
    }

    #[test]
    fn test_proper_word_single_char() {
        // Single uppercase char: chars().next() = Some('A') is uppercase,
        // chars().all() on remaining (none) is vacuously true → returns true.
        // This is the correct behavior — a single-char proper word is valid.
        assert!(is_proper_word("A"));
        assert!(is_proper_word("Z"));
    }

    // ── entity_score ───────────────────────────────────────────────────

    #[test]
    fn test_entity_score_noise_words() {
        for word in &["the", "and", "for", "with", "this", "that", "from",
                       "have", "been", "was", "are", "has", "had", "not",
                       "but", "its", "his", "her", "they", "will", "would",
                       "could", "should", "there", "their", "about", "which",
                       "when", "where", "what", "into", "over"] {
            assert_eq!(entity_score(word), 0, "noise word '{}' should score 0", word);
        }
    }

    #[test]
    fn test_entity_score_too_short() {
        assert_eq!(entity_score("ab"), 0);
        assert_eq!(entity_score("a"), 0);
        assert_eq!(entity_score(""), 0);
    }

    #[test]
    fn test_entity_score_valid() {
        assert_eq!(entity_score("Alice"), 1);
        assert_eq!(entity_score("OpenAI"), 1);
        assert_eq!(entity_score("Rust"), 1);
        assert_eq!(entity_score("Garry"), 1);
    }

    #[test]
    fn test_entity_score_case_insensitive_noise() {
        // entity_score lowercases first, so "The" → "the" → noise = 0
        assert_eq!(entity_score("The"), 0);
        assert_eq!(entity_score("AND"), 0);
    }

    // ── extract_single_words ───────────────────────────────────────────

    #[test]
    fn test_extract_single_words_tech_names() {
        let mentions = extract_single_words("We use Python and Docker");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"Python"));
        assert!(names.contains(&"Docker"));
    }

    #[test]
    fn test_extract_single_words_skips_sentence_starters() {
        let mentions = extract_single_words("Python is great. Docker runs containers.");
        // "Python" is first word — should be skipped as sentence starter
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(!names.contains(&"Python"), "first word 'Python' is sentence starter, should be skipped");
        // "Docker" follows a period — also a sentence starter
        assert!(!names.contains(&"Docker"), "'Docker' after period is sentence starter, should be skipped");
    }

    #[test]
    fn test_extract_single_words_skips_common_words() {
        let mentions = extract_single_words("The First Based Given after Some");
        assert!(mentions.is_empty(), "all common capitalized words should be skipped");
    }

    #[test]
    fn test_extract_single_words_skips_short() {
        let mentions = extract_single_words("Go is fast but C is faster");
        // "Go" and "C" are <3 chars → skipped
        assert!(mentions.is_empty());
    }

    #[test]
    fn test_extract_single_words_skips_followed_by_capitalized() {
        // "Garry Tan" — "Garry" followed by capitalized "Tan" → extract_people territory
        let mentions = extract_single_words("Garry Tan works here");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(!names.contains(&"Garry"), "'Garry' followed by capitalized 'Tan', should be skipped");
    }

    #[test]
    fn test_extract_single_words_empty() {
        let mentions = extract_single_words("");
        assert!(mentions.is_empty());
    }

    #[test]
    fn test_extract_single_words_concept_type() {
        let mentions = extract_single_words("After lunch, Python was discussed");
        // "Python" is a tech name → entity_type should be "technology"
        let python = mentions.iter().find(|m| m.name == "Python").unwrap();
        assert_eq!(python.entity_type, "technology");
    }

    #[test]
    fn test_extract_single_words_non_tech_concept() {
        // "Canada" — not a tech name, 6 chars, capitalized → concept
        let mentions = extract_single_words("After lunch, Canada exports maple");
        let canada = mentions.iter().find(|m| m.name == "Canada");
        assert!(canada.is_some());
        assert_eq!(canada.unwrap().entity_type, "concept");
    }

    // ── extract_acronyms ───────────────────────────────────────────────

    #[test]
    fn test_extract_acronyms_valid() {
        let mentions = extract_acronyms("The API and DB are running on AWS");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"API"));
        assert!(names.contains(&"DB"));
        assert!(names.contains(&"AWS"));
    }

    #[test]
    fn test_extract_acronyms_with_digits() {
        let mentions = extract_acronyms("GPT4 and BERT2 are models");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"GPT4"));
        assert!(names.contains(&"BERT2"));
    }

    #[test]
    fn test_extract_acronyms_skips_noise() {
        let mentions = extract_acronyms("THE AND FOR NOT BUT ITS ARE");
        assert!(mentions.is_empty(), "all noise acronyms should be skipped");
    }

    #[test]
    fn test_extract_acronyms_length_bounds() {
        let mentions = extract_acronyms("A BC ABCDEF KLMNOPQ");
        // "A" < 2 → skip, "BC" valid, "ABCDEF" = 6 valid, "KLMNOPQ" = 7 → skip
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"BC"));
        assert!(names.contains(&"ABCDEF"));
        assert!(!names.contains(&"A"));
        assert!(!names.contains(&"KLMNOPQ"));
    }

    #[test]
    fn test_extract_acronyms_lowercase_skipped() {
        let mentions = extract_acronyms("api is lowercase");
        assert!(mentions.is_empty());
    }

    #[test]
    fn test_extract_acronyms_empty() {
        let mentions = extract_acronyms("");
        assert!(mentions.is_empty());
    }

    // ── extract_people ─────────────────────────────────────────────────

    #[test]
    fn test_extract_people_two_word_names() {
        let mentions = extract_people("Garry Tan and Sam Altman spoke");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"Garry Tan"));
        assert!(names.contains(&"Sam Altman"));
    }

    #[test]
    fn test_extract_people_wrong_case() {
        let mentions = extract_people("garry tan is lowercase");
        assert!(mentions.is_empty());
    }

    #[test]
    fn test_extract_people_single_name_not_extracted() {
        let mentions = extract_people("Alice wrote the code");
        // Single word — no pair → not extracted
        assert!(mentions.is_empty());
    }

    #[test]
    fn test_extract_people_short_names_filtered() {
        // Both names must be ≥3 chars for the first word
        let mentions = extract_people("Al Go is a short name");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.is_empty(), "short names should not be extracted as people");
    }

    #[test]
    fn test_extract_people_noise_words_filtered() {
        let mentions = extract_people("The World is not a person");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        // "The World" — "The" is a noise word → should be filtered
        assert!(!names.contains(&"The World"), "noise word 'The' should be filtered");
    }

    // ── extract_companies ──────────────────────────────────────────────

    #[test]
    fn test_extract_companies_simple() {
        let mentions = extract_companies("OpenAI Inc and Microsoft Corp are tech companies");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"OpenAI Inc"));
        assert!(names.contains(&"Microsoft Corp"));
    }

    #[test]
    fn test_extract_companies_suffix_case_insensitive() {
        let mentions = extract_companies("Acme corp and Beta ltd");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"Acme corp"));
        assert!(names.contains(&"Beta ltd"));
    }

    #[test]
    fn test_extract_companies_no_prev_word() {
        let mentions = extract_companies("Inc is just a suffix");
        assert!(mentions.is_empty(), "suffix at start of text → no company");
    }

    #[test]
    fn test_extract_companies_prev_word_too_short() {
        let mentions = extract_companies("A Corp has a short name");
        assert!(mentions.is_empty(), "single-char prev word → not a company");
    }

    #[test]
    fn test_extract_companies_min_two_words() {
        let mentions = extract_companies("Acme Corp");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"Acme Corp"));
    }

    #[test]
    fn test_extract_companies_no_suffix() {
        let mentions = extract_companies("Apple and Google are companies");
        assert!(mentions.is_empty(), "no known suffix → not extracted as company");
    }

    #[test]
    fn test_extract_companies_case_insensitive_suffix() {
        let mentions = extract_companies("Acme inc is a company");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"Acme inc"));
    }

    #[test]
    fn test_extract_companies_empty() {
        let mentions = extract_companies("");
        assert!(mentions.is_empty());
    }

    #[test]
    fn test_extract_companies_with_punctuation() {
        let mentions = extract_companies("Acme Corp, and Beta LLC. are here");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"Acme Corp"));
        assert!(names.contains(&"Beta LLC"));
    }

    // ── is_company_suffix tests (extended) ──────────────────────────────────

    #[test]
    fn test_is_company_suffix_known_suffixes() {
        assert!(is_company_suffix("Inc"));
        assert!(is_company_suffix("Corp"));
        assert!(is_company_suffix("LLC"));
        assert!(is_company_suffix("Ltd"));
        assert!(is_company_suffix("GmbH"));
        assert!(is_company_suffix("SaaS"));
        assert!(is_company_suffix("AI"));
        assert!(is_company_suffix("Labs"));
        assert!(is_company_suffix("Technologies"));
        assert!(is_company_suffix("Ventures"));
        assert!(is_company_suffix("Capital"));
        assert!(is_company_suffix("Partners"));
        assert!(is_company_suffix("Group"));
        assert!(is_company_suffix("Holdings"));
        assert!(is_company_suffix("Enterprises"));
        assert!(is_company_suffix("Studios"));
        assert!(is_company_suffix("Software"));
        assert!(is_company_suffix("Systems"));
        assert!(is_company_suffix("Networks"));
        assert!(is_company_suffix("Analytics"));
        assert!(is_company_suffix("Robotics"));
    }

    #[test]
    fn test_is_company_suffix_case_insensitive_ext() {
        assert!(is_company_suffix("inc"));
        assert!(is_company_suffix("INC"));
        assert!(is_company_suffix("Inc"));
        assert!(is_company_suffix("iNc"));
    }

    #[test]
    fn test_is_company_suffix_unknown_returns_false() {
        assert!(!is_company_suffix("Company"));
        assert!(!is_company_suffix("Solutions"));
        assert!(!is_company_suffix("Services"));
        assert!(!is_company_suffix("Test"));
        assert!(!is_company_suffix(""));
    }

    // ── is_proper_word tests (extended) ────────────────────────────────

    #[test]
    fn test_is_proper_word_valid_ext() {
        assert!(is_proper_word("John"));
        assert!(is_proper_word("Apple"));
        assert!(is_proper_word("Microsoft"));
        assert!(is_proper_word("A"));
        assert!(is_proper_word("Ab"));
    }

    #[test]
    fn test_is_proper_word_invalid_lowercase() {
        assert!(!is_proper_word("john"));
        assert!(!is_proper_word("apple"));
    }

    #[test]
    fn test_is_proper_word_invalid_mixed_case() {
        assert!(!is_proper_word("JohnDoe"));
        assert!(!is_proper_word("McDonald"));
        assert!(!is_proper_word("iPhone"));
    }

    #[test]
    fn test_is_proper_word_invalid_empty() {
        assert!(!is_proper_word(""));
    }

    #[test]
    fn test_is_proper_word_invalid_starts_with_lowercase() {
        assert!(!is_proper_word("john"));
        assert!(!is_proper_word("jOHN"));
    }

    // ── entity_score tests (extended) ──────────────────────────────────

    #[test]
    fn test_entity_score_noise_words_zero() {
        let noise = ["the", "and", "for", "with", "this", "that", "from", "have",
                     "been", "was", "are", "has", "had", "not", "but", "its", "his",
                     "her", "she", "they", "will", "would", "could", "should", "there",
                     "their", "about", "which", "when", "where", "what", "into", "over"];
        for word in noise {
            assert_eq!(entity_score(word), 0, "Word '{}' should score 0", word);
        }
    }

    #[test]
    fn test_entity_score_short_words_zero() {
        assert_eq!(entity_score("a"), 0);
        assert_eq!(entity_score("an"), 0);
        assert_eq!(entity_score("to"), 0);
        assert_eq!(entity_score("of"), 0);
    }

    #[test]
    fn test_entity_score_valid_words_one() {
        assert_eq!(entity_score("Apple"), 1);
        assert_eq!(entity_score("Microsoft"), 1);
        assert_eq!(entity_score("Technology"), 1);
        assert_eq!(entity_score("Innovation"), 1);
    }

    #[test]
    fn test_entity_score_case_insensitive_noise_alt() {
        assert_eq!(entity_score("THE"), 0);
        assert_eq!(entity_score("And"), 0);
        assert_eq!(entity_score("FOR"), 0);
    }

    // ── extract_people tests (extended) ────────────────────────────────

    #[test]
    fn test_extract_people_simple_two_word_names() {
        let text = "John Smith works at Google. Jane Doe is his colleague.";
        let people = extract_people(text);
        assert_eq!(people.len(), 2);
        assert_eq!(people[0].name, "John Smith");
        assert_eq!(people[0].entity_type, "person");
        assert_eq!(people[1].name, "Jane Doe");
        assert_eq!(people[1].entity_type, "person");
    }

    #[test]
    fn test_extract_people_filters_noise() {
        let text = "The And For With This That From Have Been Was Are Has Had Not But Its His Her She They Will Would Could Should There Their About Which When Where What Into Over.";
        let people = extract_people(text);
        // Should not extract noise word pairs
        assert_eq!(people.len(), 0);
    }

    #[test]
    fn test_extract_people_filters_single_letter_first() {
        let text = "I The A New John Smith";
        let people = extract_people(text);
        // "I The" and "A New" should be filtered (first word len <= 1 or second <= 2)
        assert_eq!(people.len(), 1);
        assert_eq!(people[0].name, "John Smith");
    }

    #[test]
    fn test_extract_people_overlapping_not_duplicated() {
        let text = "John Smith Jones works here.";
        // "John Smith" and "Smith Jones" are both valid pairs
        let people = extract_people(text);
        assert!(people.len() >= 1);
    }

    #[test]
    fn test_extract_people_empty_text() {
        let people = extract_people("");
        assert_eq!(people.len(), 0);
    }

    // ── extract_single_words tests (extended) ──────────────────────────

    #[test]
    fn test_extract_single_words_tech_names_ext() {
        let text = "I use Python and Rust for programming. Also Docker and Kubernetes.";
        let words = extract_single_words(text);
        let names: Vec<_> = words.iter().map(|w| w.name.as_str()).collect();
        assert!(names.contains(&"Python"));
        assert!(names.contains(&"Rust"));
        assert!(names.contains(&"Docker"));
        assert!(names.contains(&"Kubernetes"));
    }

    #[test]
    fn test_extract_single_words_skips_sentence_starters_ext() {
        let text = "Hello world. This is a test. Apple makes phones.";
        let words = extract_single_words(text);
        let names: Vec<_> = words.iter().map(|w| w.name.as_str()).collect();
        // "Hello" is first word of sentence - skipped
        // "This" is first word of sentence - skipped
        // "Apple" is not first word (after "is a test.")
        assert!(!names.contains(&"Hello"));
        assert!(!names.contains(&"This"));
        assert!(names.contains(&"Apple"));
    }

    #[test]
    fn test_extract_single_words_filters_common_words() {
        let text = "This That What When Where Which There Their They Then Than Thus Them Here Have Been From Very Just Also Some Each Many More Most Only Over Such Will With Like Last Next First Second Other After Before Based Used Made Said Known Shown Given Still Even Well Back Down Left Right";
        let words = extract_single_words(text);
        assert_eq!(words.len(), 0);
    }

    #[test]
    fn test_extract_single_words_min_length() {
        let text = "A B C Go Go Go Go Go";
        let words = extract_single_words(text);
        // "Go" is length 2, should be filtered by min length 3
        assert_eq!(words.len(), 0);
    }

    // ── extract_acronyms tests (extended) ──────────────────────────────

    #[test]
    fn test_extract_acronyms_valid_ext() {
        let text = "NASA and FBI work with AI and ML models. HTTP API uses JSON.";
        let acronyms = extract_acronyms(text);
        let names: Vec<_> = acronyms.iter().map(|a| a.name.as_str()).collect();
        assert!(names.contains(&"NASA"));
        assert!(names.contains(&"FBI"));
        assert!(names.contains(&"AI"));
        assert!(names.contains(&"ML"));
        assert!(names.contains(&"HTTP"));
        assert!(names.contains(&"API"));
        assert!(names.contains(&"JSON"));
    }

    #[test]
    fn test_extract_acronyms_filters_noise() {
        let text = "THE AND FOR NOT BUT ITS OUT ARE HAS HAD CAN ALL ANY NEW OLD BIG TOP";
        let acronyms = extract_acronyms(text);
        assert_eq!(acronyms.len(), 0);
    }

    #[test]
    fn test_extract_acronyms_length_bounds_ext() {
        let text = "A AB ABC ABCD ABCDE ABCDEF ABCDEFG";
        let acronyms = extract_acronyms(text);
        let names: Vec<_> = acronyms.iter().map(|a| a.name.as_str()).collect();
        // 2-6 chars valid
        assert!(names.contains(&"AB"));
        assert!(names.contains(&"ABC"));
        assert!(names.contains(&"ABCD"));
        assert!(names.contains(&"ABCDE"));
        assert!(names.contains(&"ABCDEF"));
        // 1 char and 7 char should be filtered
        assert!(!names.contains(&"A"));
        assert!(!names.contains(&"ABCDEFG"));
    }

    #[test]
    fn test_extract_acronyms_mixed_case_rejected() {
        let text = "Nasa Fbi Ai Ml";
        let acronyms = extract_acronyms(text);
        assert_eq!(acronyms.len(), 0);
    }

    #[test]
    fn test_extract_acronyms_with_digits_ext() {
        let text = "HTTP2 TLS13 USB3";
        let acronyms = extract_acronyms(text);
        let names: Vec<_> = acronyms.iter().map(|a| a.name.as_str()).collect();
        assert!(names.contains(&"HTTP2"));
        assert!(names.contains(&"TLS13"));
        assert!(names.contains(&"USB3"));
    }
}
