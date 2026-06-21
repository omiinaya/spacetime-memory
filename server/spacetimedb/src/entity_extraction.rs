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

// ---------------------------------------------------------------------------
// Additional extractors
// ---------------------------------------------------------------------------

/// Extract single-word capitalized names (technologies, concepts, products).
/// Skips words that are likely sentence-starters or common nouns.
fn extract_single_words(text: &str) -> Vec<Mention> {
    let mut results = Vec::new();
    let words: Vec<&str> = text.split_whitespace().collect();

    for (i, word) in words.iter().enumerate() {
        let stripped = word.trim_end_matches(|c: char| c == '.' || c == ',' || c == ';' || c == ':');
        // Must be capitalized, at least 3 chars
        if stripped.len() < 3 {
            continue;
        }
        let mut chars = stripped.chars();
        let first = chars.next();
        if first.map_or(true, |c| !c.is_ascii_uppercase()) {
            continue;
        }
        // Rest must be lowercase
        if !chars.all(|c| c.is_ascii_lowercase()) {
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

/// Extract acronyms (ALL_CAPS words with 2-6 characters).
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

/// Extract extracted entity mention.
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
    let tech_concepts = extract_single_words(&content);
    let acronyms = extract_acronyms(&content);
    let all_mentions: Vec<Mention> = people
        .into_iter()
        .chain(companies.into_iter())
        .chain(tech_concepts.into_iter())
        .chain(acronyms.into_iter())
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
        assert!(is_company_suffix("Software"));
    }

    #[test]
    fn test_company_suffix_case_insensitive() {
        assert!(is_company_suffix("inc"));
        assert!(is_company_suffix("llc"));
        assert!(is_company_suffix("gmbh"));
        assert!(is_company_suffix("ltd"));
    }

    #[test]
    fn test_company_suffix_not_a_suffix() {
        assert!(!is_company_suffix("Banana"));
        assert!(!is_company_suffix(""));
        assert!(!is_company_suffix("Apple"));
        assert!(!is_company_suffix("Corporation")); // "Corp" yes, "Corporation" no
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
        // "A Bc" — first word "A" has len 1 → entity_score returns 0 (len < 3)
        let mentions = extract_people("A Bc and Xy Zz are here");
        // "A" is too short, "Xy" len=2 → entity_score=0
        assert!(mentions.is_empty());
    }

    #[test]
    fn test_extract_people_false_positives_filtered() {
        // "I The" — "I" is short (len 1), should be filtered
        let mentions = extract_people("I The person said hi");
        assert!(mentions.is_empty());
    }

    #[test]
    fn test_extract_people_middle_of_sentence() {
        let mentions = extract_people("The speaker John Doe presented today");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"John Doe"));
    }

    #[test]
    fn test_extract_people_empty() {
        let mentions = extract_people("");
        assert!(mentions.is_empty());
    }

    // ── extract_companies ──────────────────────────────────────────────

    #[test]
    fn test_extract_companies_with_suffix() {
        let mentions = extract_companies("OpenAI Inc and Google LLC are big");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"OpenAI Inc"));
        assert!(names.contains(&"Google LLC"));
    }

    #[test]
    fn test_extract_companies_multi_word() {
        let mentions = extract_companies("Atlas Venture Partners raised a fund");
        let names: Vec<&str> = mentions.iter().map(|m| m.name.as_str()).collect();
        assert!(names.contains(&"Atlas Venture Partners"));
    }

    #[test]
    fn test_extract_companies_suffix_at_start() {
        // "Inc" at position 0 — no preceding capitalized words
        let mentions = extract_companies("Inc is not a company name here");
        assert!(mentions.is_empty());
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
}
