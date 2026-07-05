use spacetimedb::*;

use crate::trace_span;
use crate::{now_micros, uuid_v4_uniq};
use crate::tracing::TracingSpanKind;
use crate::auth::require_auth;
use crate::workspace::check_space_access;
use crate::trace_span;
use crate::tracing::TracingSpanKind;

/// A note — markdown document with wikilink backlinking support.
#[table(accessor = note)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Note {
    #[primary_key]
    pub id: String,
    pub workspace_id: String,
    /// Title of the note (auto-extracted from first # heading, or empty)
    pub title: String,
    /// Raw markdown content
    pub content: String,
    /// Which date this note belongs to (daily notes set this; freeform notes leave empty)
    pub note_date: String,
    /// Persistent embedding (only updated on save when content changes significantly)
    pub embedding_json: String,
    /// Number of backlinks pointing *to* this note (denormalised for sorting)
    pub backlink_count: u32,
    /// Number of block-level references pointing to blocks in this note
    pub block_ref_count: u32,
    pub created_at: i64,
    pub updated_at: i64,
    pub is_active: bool,
    /// Version number (incremented on updates for history tracking)
    pub version: Option<u32>,
}

/// A snapshot of a note's state before an update.
/// Used for version history / audit / undo-diff tracking.
#[table(accessor = note_revision)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct NoteRevision {
    #[primary_key]
    pub id: String,
    /// The note this revision belongs to
    pub note_id: String,
    pub workspace_id: String,
    /// Which version this was before the update
    pub version: u32,
    pub previous_title: String,
    pub previous_content: String,
    pub new_title: String,
    pub new_content: String,
    pub changed_at: i64,
    pub changed_by: String,
}

/// Save a revision snapshot before a note is updated.
/// Should be called *before* modifying the note in-place.
pub fn record_note_revision(
    ctx: &ReducerContext,
    note: &Note,
    new_title: &str,
    new_content: &str,
) {
    let id = uuid_v4_uniq(ctx, |id| ctx.db.note_revision().id().find(id).is_none(), 3);
    let revision = NoteRevision {
        id,
        note_id: note.id.clone(),
        workspace_id: note.workspace_id.clone(),
        version: note.version.unwrap_or(0),
        previous_title: note.title.clone(),
        previous_content: note.content.clone(),
        new_title: new_title.to_string(),
        new_content: new_content.to_string(),
        changed_at: now_micros(ctx),
        changed_by: ctx.sender().to_hex().to_string(),
    };
    ctx.db.note_revision().insert(revision);
}

/// A backlink — forward edge from note A → note B ([[wikilink]]).
#[table(accessor = note_backlink)]
#[derive(Debug, Clone)]
pub struct NoteBacklink {
    #[primary_key]
    pub id: String,
    /// The note that contains the [[wikilink]]
    pub source_note_id: String,
    /// The note being linked to
    pub target_note_id: String,
    /// The display text used in the wikilink
    pub display_text: String,
    pub created_at: i64,
}

/// A block — individual paragraph/heading/list-item within a note.
/// Blocks are parsed from markdown content and given stable IDs.
#[table(accessor = note_block)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct NoteBlock {
    #[primary_key]
    pub id: String,
    /// Parent note
    pub note_id: String,
    /// Block type: "paragraph", "heading", "list_item", "todo", "code_block", "quote", "hr", "table"
    pub block_type: String,
    /// Raw text content (without markdown delimiters for the block itself)
    pub content: String,
    /// Full markdown source line(s) for this block
    pub source: String,
    /// Order within the note (0-indexed, sequential)
    pub block_order: u32,
    /// Heading level (1-6 for headings, 0 otherwise)
    pub heading_level: u8,
    /// Indent level for nested list items
    pub indent_level: u32,
    /// Task state: "none", "todo", "done", "later", "now", "waiting", "cancelled"
    pub task_state: String,
    /// JSON metadata (tags, priority, deadline, custom properties)
    pub properties_json: String,
    pub is_active: bool,
    pub created_at: i64,
}

/// A block-level reference — ((block-id)) or {{embed ((block-id))}}
#[table(accessor = block_reference)]
#[derive(Debug, Clone)]
pub struct BlockReference {
    #[primary_key]
    pub id: String,
    /// The note containing the reference
    pub source_note_id: String,
    /// The block containing the reference
    pub source_block_id: String,
    /// The target block being referenced
    pub target_block_id: String,
    /// The target note (denormalised for quick queries)
    pub target_note_id: String,
    /// Reference type: "ref" for ((id)), "embed" for {{embed ((id))}}
    pub ref_type: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Note reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_note(
    ctx: &ReducerContext,
    workspace_id: String,
    title: String,
    content: String,
    note_date: String,
    embedding_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_note", TracingSpanKind::Write, &workspace_id, {
        require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &workspace_id, &caller, "editor")?;
        let now = now_micros(ctx);
        let id = uuid_v4_uniq(ctx, |id| ctx.db.note().id().find(id).is_none(), 3);

        // Normalise note_date: if non-empty, must be YYYY-MM-DD
        if !note_date.is_empty() && !is_date_format(&note_date) {
            return Err(format!("Invalid note_date '{}': must be empty or YYYY-MM-DD", note_date));
        }

        // Extract title from first # heading if title is empty
        let final_title = if title.is_empty() {
            extract_title_from_markdown(&content)
        } else {
            title
        };

        let note = Note {
            id: id.clone(),
            workspace_id,
            title: final_title,
            content: content.clone(),
            note_date,
            embedding_json: if embedding_json.is_empty() { String::from("[]") } else { embedding_json },
            backlink_count: 0,
            block_ref_count: 0,
            created_at: now,
            updated_at: now,
            is_active: true,
            version: Some(1),
        };

        ctx.db.note().insert(note);

        // Parse blocks and backlinks
        parse_note_blocks_inner(ctx, &id, &content, now);
        resolve_backlinks(&ctx, &id, &content, now);

        Ok(())
    })
}

#[reducer]
pub fn update_note(
    ctx: &ReducerContext,
    id: String,
    title: String,
    content: String,
    embedding_json: String,
    expected_version: u32,
) -> Result<(), String> {
    // We need workspace_id before trace_span, so we look it up first
    let ws_id = ctx
        .db
        .note()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Note '{}' not found", id))?
        .workspace_id
        .clone();
    trace_span!(ctx, "update_note", TracingSpanKind::Write, &ws_id, {
        require_auth(ctx)?;
        let now = now_micros(ctx);

        let mut note = ctx
            .db
            .note()
            .id()
            .find(&id)
            .ok_or_else(|| format!("Note '{}' not found", id))?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &note.workspace_id, &caller, "editor")?;

        // Optimistic concurrency guard: if expected_version > 0, verify it matches
        let current_version = note.version.unwrap_or(0);
        if expected_version > 0 && expected_version != current_version {
            return Err(format!(
                "Concurrent note update detected: expected version {}, but note is at version {}. Re-read the note and retry.",
                expected_version, current_version
            ));
        }

        let final_title = if title.is_empty() {
            extract_title_from_markdown(&content)
        } else {
            title
        };

        // Save revision snapshot before modifying
        record_note_revision(ctx, &note, &final_title, &content);

        note.title = final_title;
        note.content = content.clone();
        note.updated_at = now;
        note.version = Some(current_version + 1);
        if !embedding_json.is_empty() {
            note.embedding_json = embedding_json;
        }
        ctx.db.note().id().update(note);

        // Re-parse backlinks: delete old ones, insert new ones
        clear_backlinks(ctx, &id);
        resolve_backlinks(&ctx, &id, &content, now);

        // Re-parse blocks
        clear_blocks(ctx, &id);
        parse_note_blocks_inner(ctx, &id, &content, now);

        Ok(())
    })
}

#[reducer]
pub fn delete_note(ctx: &ReducerContext, id: String) -> Result<(), String> {
    // We need workspace_id before trace_span, so we look it up first
    let ws_id = ctx
        .db
        .note()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Note '{}' not found", id))?
        .workspace_id
        .clone();
    trace_span!(ctx, "delete_note", TracingSpanKind::Write, &ws_id, {
    require_auth(ctx)?;
    let note = ctx
        .db
        .note()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Note '{}' not found", id))?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &note.workspace_id, &caller, "editor")?;
    clear_backlinks(ctx, &id);

    // Clean up blocks
    clear_blocks(ctx, &id);

    // Clean up block references pointing to this note's blocks
    let refs_targeting: Vec<_> = ctx
        .db
        .block_reference()
        .iter().take(crate::MAX_RESULTS)
        .filter(|br: &BlockReference| br.target_note_id == id)
        .map(|br| br.id.clone())
        .collect();
    for rid in &refs_targeting {
        ctx.db.block_reference().id().delete(rid);
    }

    ctx.db.note().id().delete(&id);
    Ok(())

    })
}

// ---------------------------------------------------------------------------
// Block parsing reducer (callable standalone or from create/update)
// ---------------------------------------------------------------------------

#[reducer]
pub fn parse_note_blocks(ctx: &ReducerContext, note_id: String, expected_version: u32) -> Result<(), String> {
    trace_span!(ctx, "parse_note_blocks", TracingSpanKind::Write, "", {
        let _account = require_auth(ctx)?;
        let note = ctx
            .db
            .note()
            .id()
            .find(&note_id)
            .ok_or_else(|| format!("Note '{}' not found", note_id))?;

        // Optimistic concurrency guard: if expected_version > 0, verify it matches
        let current_version = note.version.unwrap_or(0);
        if expected_version > 0 && expected_version != current_version {
            return Err(format!(
                "Concurrent block re-parse detected: expected version {}, but note is at version {}. Re-read the note and retry.",
                expected_version, current_version
            ));
        }

        let now = now_micros(ctx);
        clear_blocks(ctx, &note_id);
        parse_note_blocks_inner(ctx, &note_id, &note.content, now);
        Ok(())
    })
}

// ---------------------------------------------------------------------------
// Individual block update reducer
// ---------------------------------------------------------------------------

/// Update a single block's metadata (task_state, properties_json, content, is_active)
/// with optimistic concurrency control via the parent note's version.
///
/// This avoids re-parsing the entire note when only block-level metadata changes
/// (e.g., toggling a task checkbox, updating block properties).
///
/// When task_state is provided, the parent note's content is also updated to
/// keep the markdown source in sync (e.g., `[ ]` <-> `[x]`).
#[reducer]
pub fn update_note_block(
    ctx: &ReducerContext,
    note_id: String,
    block_id: String,
    expected_note_version: u32,
    task_state: String,
    properties_json: String,
    block_content: String,
    is_active: Option<bool>,
) -> Result<(), String> {
    // Need workspace_id before trace_span
    let ws_id = ctx
        .db
        .note()
        .id()
        .find(&note_id)
        .ok_or_else(|| format!("Note '{}' not found", note_id))?
        .workspace_id
        .clone();

    trace_span!(ctx, "update_note_block", TracingSpanKind::Write, &ws_id, {
        require_auth(ctx)?;
        let caller = ctx.sender().to_hex();
        check_space_access(ctx, &ws_id, &caller, "editor")?;
        let now = now_micros(ctx);

        // Verify note exists and check version (optimistic concurrency)
        let mut note = ctx
            .db
            .note()
            .id()
            .find(&note_id)
            .ok_or_else(|| format!("Note '{}' not found", note_id))?;

        let current_version = note.version.unwrap_or(0);
        if expected_note_version > 0 && expected_note_version != current_version {
            return Err(format!(
                "Concurrent note block update detected: expected version {}, but note is at version {}. Re-read the note and retry.",
                expected_note_version, current_version
            ));
        }

        // Find the block
        let mut block = ctx
            .db
            .note_block()
            .id()
            .find(&block_id)
            .ok_or_else(|| format!("Block '{}' not found in note '{}'", block_id, note_id))?;

        // Verify block belongs to the specified note
        if block.note_id != note_id {
            return Err(format!(
                "Block '{}' does not belong to note '{}'", block_id, note_id
            ));
        }

        // Save revision snapshot before modifying
        record_note_revision(ctx, &note, &note.title, &note.content);

        let mut content_updated = false;
        let mut new_content = note.content.clone();

        // Update task_state and keep note markdown in sync
        if !task_state.is_empty() && task_state != block.task_state {
            let old_state = std::mem::replace(&mut block.task_state, task_state.clone());

            if apply_task_state_to_content(
                &mut new_content,
                &block.source,
                &old_state,
                &task_state,
            ) {
                content_updated = true;
            }
        }

        // Update properties_json
        if !properties_json.is_empty() && properties_json != block.properties_json {
            block.properties_json = properties_json;
        }

        // Update block text content / source
        if !block_content.is_empty() && block_content != block.content {
            let old_source = block.source.clone();
            block.content = block_content.clone();
            block.source = block_content;
            if let Some(pos) = new_content.find(&old_source) {
                new_content.replace_range(pos..pos + old_source.len(), &block.source);
                content_updated = true;
            }
        }

        // Update active state
        if let Some(active) = is_active {
            block.is_active = active;
        }

        ctx.db.note_block().id().update(block);

        // Persist content changes and bump note version
        if content_updated {
            note.content = new_content;
        }
        note.version = Some(current_version + 1);
        note.updated_at = now;
        ctx.db.note().id().update(note);

        Ok(())
    })
}

/// Apply a task_state transition to the note content by modifying the markdown
/// representation of the targeted block (e.g., `[ ]` <-> `[x]`).
fn apply_task_state_to_content(
    content: &mut String,
    block_source: &str,
    old_state: &str,
    new_state: &str,
) -> bool {
    let start = match content.find(block_source) {
        Some(pos) => pos,
        None => return false,
    };

    let source_slice = &content[start..start + block_source.len()];

    let updated = match (old_state, new_state) {
        // Checkbox toggle: [ ] <-> [x]
        ("todo", "done") | ("done", "todo") | ("none", "todo") | ("none", "done") => {
            if let Some(ck_pos) = source_slice.find('[') {
                let actual_pos = start + ck_pos;
                if actual_pos + 3 <= content.len() {
                    let slice = &content[actual_pos..actual_pos + 3];
                    let replacement = if new_state == "done" { "[x]" } else { "[ ]" };
                    if slice == "[ ]" || slice == "[x]" || slice == "[X]" {
                        content.replace_range(actual_pos..actual_pos + 3, replacement);
                        true
                    } else {
                        false
                    }
                } else {
                    false
                }
            } else {
                false
            }
        }
        // Inline TODO <-> DONE / LATER <-> NOW etc.
        _ if !old_state.is_empty() && !new_state.is_empty()
            && old_state != "none" && new_state != "none" =>
        {
            let old_upper = old_state.to_uppercase();
            let new_upper = new_state.to_uppercase();
            let old_marker = format!("{} ", old_upper);
            let new_marker = format!("{} ", new_upper);
            if let Some(m_pos) = source_slice.find(&old_marker) {
                let actual_pos = start + m_pos;
                content.replace_range(actual_pos..actual_pos + old_marker.len(), &new_marker);
                true
            } else {
                false
            }
        }
        _ => false,
    };

    updated
}

// ---------------------------------------------------------------------------
// Block parsing logic
// ---------------------------------------------------------------------------

fn parse_note_blocks_inner(ctx: &ReducerContext, note_id: &str, content: &str, now: i64) {
    let blocks = split_into_blocks(content);

    for (order, block) in blocks.iter().enumerate() {
        let block_id = format!("{}:{:04x}", note_id, order);
        let (block_type, heading_level, task_state, indent_level, props, text) = classify_block(block);

        ctx.db.note_block().insert(NoteBlock {
            id: block_id.clone(),
            note_id: note_id.to_string(),
            block_type,
            content: text,
            source: block.to_string(),
            block_order: order as u32,
            heading_level,
            indent_level,
            task_state,
            properties_json: props,
            is_active: true,
            created_at: now,
        });
    }

    // Resolve ((block-ref)) references between blocks
    resolve_block_refs(ctx, note_id, &blocks, now);
}

/// Split raw markdown into blocks at paragraph/heading/list-item boundaries.
fn split_into_blocks(content: &str) -> Vec<String> {
    let mut blocks: Vec<String> = Vec::new();
    let mut current = String::new();

    for line in content.lines() {
        let trimmed = line.trim();

        // Blank lines separate blocks (except inside code fences)
        if trimmed.is_empty() {
            if !current.is_empty() {
                blocks.push(current.trim_end().to_string());
                current = String::new();
            }
            continue;
        }

        // Headings are always their own block
        if trimmed.starts_with('#') && !current.is_empty() && !current.contains('\n') {
            // If current has content and this is a heading, finalize current
            if !current.trim().is_empty() {
                blocks.push(current.trim_end().to_string());
                current = String::new();
            }
            blocks.push(trimmed.to_string());
            continue;
        }

        // Horizontal rules are their own block
        if trimmed.starts_with("---") || trimmed.starts_with("***") || trimmed.starts_with("___") {
            if !current.is_empty() {
                blocks.push(current.trim_end().to_string());
                current = String::new();
            }
            blocks.push(trimmed.to_string());
            continue;
        }

        // List items and blockquotes start new blocks when there's a blank line before them
        // But inline continuation is fine
        if !current.is_empty() && (trimmed.starts_with("- ") || trimmed.starts_with("* ") || trimmed.starts_with("> ")) {
            // Check if current is likely the same type of list
            let last_line = current.lines().last().unwrap_or("");
            let last_trimmed = last_line.trim();
            let same_type = (last_trimmed.starts_with("- ") && trimmed.starts_with("- "))
                || (last_trimmed.starts_with("* ") && trimmed.starts_with("* "))
                || (last_trimmed.starts_with("> ") && trimmed.starts_with("> "))
                || (last_trimmed.starts_with("- [") && trimmed.starts_with("- ["));
            if !same_type && !current.trim().is_empty() {
                blocks.push(current.trim_end().to_string());
                current = String::new();
            }
        }

        current.push_str(line);
        current.push('\n');
    }

    if !current.trim().is_empty() {
        blocks.push(current.trim_end().to_string());
    }

    // If completely empty content, produce no blocks
    if blocks.is_empty() && !content.trim().is_empty() {
        blocks.push(content.trim().to_string());
    }

    blocks
}

/// Classify a block and extract metadata.
fn classify_block(block: &str) -> (String, u8, String, u32, String, String) {
    let trimmed = block.trim();

    // Heading
    if let Some(rest) = trimmed.strip_prefix("###### ") { return ("heading".to_string(), 6, "none".to_string(), 0, "{}".to_string(), rest.trim().to_string()); }
    if let Some(rest) = trimmed.strip_prefix("##### ") { return ("heading".to_string(), 5, "none".to_string(), 0, "{}".to_string(), rest.trim().to_string()); }
    if let Some(rest) = trimmed.strip_prefix("#### ") { return ("heading".to_string(), 4, "none".to_string(), 0, "{}".to_string(), rest.trim().to_string()); }
    if let Some(rest) = trimmed.strip_prefix("### ") { return ("heading".to_string(), 3, "none".to_string(), 0, "{}".to_string(), rest.trim().to_string()); }
    if let Some(rest) = trimmed.strip_prefix("## ") { return ("heading".to_string(), 2, "none".to_string(), 0, "{}".to_string(), rest.trim().to_string()); }
    if let Some(rest) = trimmed.strip_prefix("# ") { return ("heading".to_string(), 1, "none".to_string(), 0, "{}".to_string(), rest.trim().to_string()); }

    // Checkbox task — - [ ] or - [x] or TODO/DONE variants
    if trimmed.starts_with("- [") || trimmed.starts_with("* [") {
        let is_checked = trimmed.contains("[x]") || trimmed.contains("[X]");
        let indent = count_indent(block);
        let content = if let Some(idx) = trimmed.find(']') {
            trimmed[idx+1..].trim().to_string()
        } else {
            trimmed.to_string()
        };
        let state = if is_checked { "done".to_string() } else { "todo".to_string() };
        return ("todo".to_string(), 0, state, indent, "{}".to_string(), content);
    }

    // TODO/DONE/LATER/NOW/WAITING/CANCELLED inline markers
    for prefix in &["TODO ", "DONE ", "LATER ", "NOW ", "WAITING ", "CANCELLED ", "DOING "] {
        if trimmed.starts_with(prefix) || trimmed.to_uppercase().starts_with(prefix) {
            let state = prefix.trim().to_lowercase();
            let content = trimmed[prefix.len().saturating_sub(if trimmed.starts_with(prefix) { 0 } else { prefix.len() - 1 })..].trim().to_string();
            return ("todo".to_string(), 0, state, count_indent(block), "{}".to_string(), if content.is_empty() { trimmed.to_string() } else { content });
        }
    }

    // List item
    if trimmed.starts_with("- ") || trimmed.starts_with("* ") {
        let indent = count_indent(block);
        let content = if let Some(c) = trimmed.strip_prefix("- ") { c.trim().to_string() }
                      else if let Some(c) = trimmed.strip_prefix("* ") { c.trim().to_string() }
                      else { trimmed.to_string() };
        return ("list_item".to_string(), 0, "none".to_string(), indent, "{}".to_string(), content);
    }

    // Ordered list item — 1. item
    if trimmed.chars().next().map_or(false, |c| c.is_ascii_digit())
        && trimmed.contains(". ")
    {
        let indent = count_indent(block);
        let content = trimmed.splitn(2, ". ").nth(1).unwrap_or("").trim().to_string();
        return ("list_item".to_string(), 0, "none".to_string(), indent, "{}".to_string(), content);
    }

    // Blockquote
    if trimmed.starts_with("> ") {
        let content = trimmed.strip_prefix("> ").unwrap_or("").trim().to_string();
        return ("quote".to_string(), 0, "none".to_string(), 0, "{}".to_string(), content);
    }

    // Code block (multiline)
    if trimmed.starts_with("```") || trimmed.starts_with("~~~") {
        let lang = trimmed.trim_start_matches('`').trim_start_matches('~').trim().to_string();
        // Extract code content (remove fence lines)
        let mut code_content = String::new();
        for line in block.lines().skip(1) {
            if line.trim().starts_with("```") || line.trim().starts_with("~~~") { break; }
            code_content.push_str(line);
            code_content.push('\n');
        }
        return ("code_block".to_string(), 0, "none".to_string(), 0, format!("{{\"lang\":\"{}\"}}", lang), code_content.trim().to_string());
    }

    // Horizontal rule
    if trimmed == "---" || trimmed == "***" || trimmed == "___" {
        return ("hr".to_string(), 0, "none".to_string(), 0, "{}".to_string(), String::new());
    }

    // Default: paragraph
    ("paragraph".to_string(), 0, "none".to_string(), 0, "{}".to_string(), trimmed.to_string())
}

fn count_indent(block: &str) -> u32 {
    let first = block.lines().next().unwrap_or("");
    first.chars().take_while(|c| *c == ' ' || *c == '\t').count() as u32
}

// ---------------------------------------------------------------------------
// Block reference resolution
// ---------------------------------------------------------------------------

/// Resolve ((block-id)) and {{embed ((block-id))}} references in parsed blocks.
fn resolve_block_refs(ctx: &ReducerContext, note_id: &str, blocks: &[String], now: i64) {
    // First pass: build block_id -> order mapping from current parse
    let block_ids: Vec<String> = (0..blocks.len())
        .map(|i| format!("{}:{:04x}", note_id, i))
        .collect();

    for (order, block_text) in blocks.iter().enumerate() {
        let source_block_id = &block_ids[order];
        // Find all ((...)) references in this block
        for (target_block_id, is_embed) in find_block_refs(block_text) {
            let target_note_id = if target_block_id.contains(':') {
                // Full ref: note_id:order
                let colon = target_block_id.find(':').unwrap_or(0);
                target_block_id[..colon].to_string()
            } else {
                // Local ref: just order hex, same note
                // Reconstruct full ref: current_note_id:order
                let full_id = format!("{}:{:04x}", note_id, order);
                full_id
            };

            // Verify the target block exists
            let target_exists = if target_note_id == note_id {
                // Verify within this parse
                if let Ok(parsed_order) = u32::from_str_radix(&target_block_id, 16) {
                    (parsed_order as usize) < blocks.len()
                } else {
                    false
                }
            } else {
                // Check DB
                let full_target_id = if target_block_id.contains(':') {
                    target_block_id.clone()
                } else {
                    format!("{}:{}", note_id, target_block_id)
                };
                ctx.db.note_block().id().find(&full_target_id).is_some()
            };

            if target_exists {
                let full_target_id = if target_block_id.contains(':') {
                    target_block_id.clone()
                } else {
                    format!("{}:{}", note_id, target_block_id)
                };

                let full_target_note_id = if target_note_id == note_id {
                    note_id.to_string()
                } else {
                    // Extract note_id from full ref
                    target_block_id.split(':').next().unwrap_or(note_id).to_string()
                };

                ctx.db.block_reference().insert(BlockReference {
                    id: uuid_v4_uniq(ctx, |id| ctx.db.block_reference().id().find(id).is_none(), 3),
                    source_note_id: note_id.to_string(),
                    source_block_id: source_block_id.clone(),
                    target_block_id: full_target_id.clone(),
                    target_note_id: full_target_note_id.clone(),
                    ref_type: if is_embed { "embed".to_string() } else { "ref".to_string() },
                    created_at: now,
                });
            }
        }
    }
}

/// Find all ((block-id)) and {{embed ((block-id))}} references in text.
/// Returns (target_block_id, is_embed) pairs.
fn find_block_refs(text: &str) -> Vec<(String, bool)> {
    let mut refs = Vec::new();
    let chars: Vec<char> = text.chars().collect();
    let len = chars.len();
    let mut i = 0;

    while i < len {
        // {{embed ((id))}} pattern
        if i + 2 < len && chars[i] == '{' && chars[i+1] == '{' {
            let rest: String = chars[i..].iter().collect();
            if let Some(embed_start) = rest.find("((") {
                if let Some(embed_end) = rest[embed_start..].find("))") {
                    let inner = &rest[embed_start+2..embed_start+embed_end];
                    let target = inner.trim().to_string();
                    if !target.is_empty() {
                        refs.push((target, true));
                    }
                    i += embed_start + embed_end + 2;
                    continue;
                }
            }
        }

        // ((id)) pattern
        if chars[i] == '(' && i + 1 < len && chars[i+1] == '(' {
            let rest: String = chars[i..].iter().collect();
            if let Some(end) = rest.find("))") {
                let inner = &rest[2..end];
                let target = inner.trim().to_string();
                if !target.is_empty() {
                    refs.push((target, false));
                }
                i += end + 2;
                continue;
            }
        }

        i += 1;
    }

    refs
}

// ---------------------------------------------------------------------------
// Backlink helpers
fn clear_backlinks(ctx: &ReducerContext, note_id: &str) {
    let old_links: Vec<_> = ctx
        .db
        .note_backlink()
        .iter().take(crate::MAX_RESULTS)
        .filter(|bl: &NoteBacklink| bl.source_note_id == note_id)
        .map(|bl| (bl.id.clone(), bl.target_note_id.clone()))
        .collect();
    for (link_id, target_id) in &old_links {
        if let Some(mut target) = ctx.db.note().id().find(target_id) {
            target.backlink_count = target.backlink_count.saturating_sub(1);
            ctx.db.note().id().update(target);
        }
        ctx.db.note_backlink().id().delete(link_id);
    }
}

fn clear_blocks(ctx: &ReducerContext, note_id: &str) {
    // Delete all block references from this note's blocks
    let block_ids: Vec<(String, Vec<String>)> = ctx
        .db
        .note_block()
        .iter().take(crate::MAX_RESULTS)
        .filter(|b: &NoteBlock| b.note_id == note_id)
        .map(|b| b.id.clone())
        .collect::<Vec<_>>()
        .chunks(1)
        .map(|c| {
            let bid = c[0].clone();
            let refs: Vec<_> = ctx
                .db
                .block_reference()
                .iter().take(crate::MAX_RESULTS)
                .filter(|br: &BlockReference| br.source_block_id == bid || br.target_block_id == bid)
                .map(|br| br.id.clone())
                .collect();
            (bid, refs)
        })
        .collect();

    for (bid, ref_ids) in &block_ids {
        for ref_id in ref_ids {
            ctx.db.block_reference().id().delete(ref_id);
        }
        ctx.db.note_block().id().delete(bid);
    }

    // Also delete block references where source_note_id matches
    let source_refs: Vec<_> = ctx
        .db
        .block_reference()
        .iter().take(crate::MAX_RESULTS)
        .filter(|br: &BlockReference| br.source_note_id == note_id)
        .map(|br| br.id.clone())
        .collect();
    for rid in &source_refs {
        ctx.db.block_reference().id().delete(rid);
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn is_date_format(s: &str) -> bool {
    let parts: Vec<&str> = s.split('-').collect();
    if parts.len() != 3 { return false; }
    if parts[0].len() != 4 { return false; }
    if parts[1].len() != 2 { return false; }
    if parts[2].len() != 2 { return false; }
    parts[0].chars().all(|c| c.is_ascii_digit())
        && parts[1].chars().all(|c| c.is_ascii_digit())
        && parts[2].chars().all(|c| c.is_ascii_digit())
}

fn extract_title_from_markdown(content: &str) -> String {
    for line in content.lines() {
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix("# ") {
            let t = rest.trim().to_string();
            if !t.is_empty() { return t; }
        }
        if let Some(rest) = trimmed.strip_prefix("#\t") {
            let t = rest.trim().to_string();
            if !t.is_empty() { return t; }
        }
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_split_into_blocks_empty() {
        let blocks = split_into_blocks("");
        assert!(blocks.is_empty());
    }

    #[test]
    fn test_split_into_blocks_blank_string() {
        let blocks = split_into_blocks("   \n\n  ");
        assert!(blocks.is_empty());
    }

    #[test]
    fn test_split_into_blocks_heading_and_paragraph() {
        let blocks = split_into_blocks("# Hello\n\nWorld");
        assert_eq!(blocks.len(), 2);
        assert!(blocks[0].contains("# Hello"));
        assert!(blocks[1].contains("World"));
    }

    #[test]
    fn test_split_into_blocks_multiple_headings() {
        let blocks = split_into_blocks("# A\n\n## B\n\n### C");
        assert_eq!(blocks.len(), 3);
        assert!(blocks[0].contains("# A"));
        assert!(blocks[1].contains("## B"));
        assert!(blocks[2].contains("### C"));
    }

    #[test]
    fn test_split_into_blocks_list_items_same_type() {
        let blocks = split_into_blocks("- item 1\n- item 2\n- item 3");
        // Same type list items should stay together
        assert_eq!(blocks.len(), 1);
        assert!(blocks[0].contains("- item 1"));
    }

    #[test]
    fn test_split_into_blocks_hr_separates() {
        let blocks = split_into_blocks("Before\n\n---\n\nAfter");
        assert_eq!(blocks.len(), 3);
        assert!(blocks[0].contains("Before"));
        assert!(blocks[1].contains("---"));
        assert!(blocks[2].contains("After"));
    }

    #[test]
    fn test_classify_block_heading_h1() {
        let (typ, level, _, _, _, content) = classify_block("# Title");
        assert_eq!(typ, "heading");
        assert_eq!(level, 1);
        assert_eq!(content, "Title");
    }

    #[test]
    fn test_classify_block_heading_h2() {
        let (typ, level, _, _, _, content) = classify_block("## Subtitle");
        assert_eq!(typ, "heading");
        assert_eq!(level, 2);
        assert_eq!(content, "Subtitle");
    }

    #[test]
    fn test_classify_block_heading_h6() {
        let (typ, level, _, _, _, content) = classify_block("###### Deep");
        assert_eq!(typ, "heading");
        assert_eq!(level, 6);
        assert_eq!(content, "Deep");
    }

    #[test]
    fn test_classify_block_todo_done() {
        let (typ, _, state, _, _, content) = classify_block("- [x] Completed task");
        assert_eq!(typ, "todo");
        assert_eq!(state, "done");
        assert!(content.contains("Completed task"));
    }

    #[test]
    fn test_classify_block_todo_unchecked() {
        let (typ, _, state, _, _, content) = classify_block("- [ ] Pending task");
        assert_eq!(typ, "todo");
        assert_eq!(state, "todo");
        assert!(content.contains("Pending task"));
    }

    #[test]
    fn test_classify_block_todo_caps_x() {
        let (typ, _, state, _, _, _) = classify_block("* [X] Done task");
        assert_eq!(typ, "todo");
        assert_eq!(state, "done");
    }

    #[test]
    fn test_classify_block_list_item_dash() {
        let (typ, _, _, _, _, content) = classify_block("- list item");
        assert_eq!(typ, "list_item");
        assert_eq!(content, "list item");
    }

    #[test]
    fn test_classify_block_list_item_star() {
        let (typ, _, _, _, _, content) = classify_block("* bullet point");
        assert_eq!(typ, "list_item");
        assert_eq!(content, "bullet point");
    }

    #[test]
    fn test_classify_block_ordered_list() {
        let (typ, _, _, _, _, content) = classify_block("1. first item");
        assert_eq!(typ, "list_item");
        assert_eq!(content, "first item");
    }

    #[test]
    fn test_classify_block_code_block() {
        let (typ, _, _, _, props, _) = classify_block("```rust");
        assert_eq!(typ, "code_block");
        assert!(props.contains("rust"));
    }

    #[test]
    fn test_classify_block_quote() {
        let (typ, _, _, _, _, content) = classify_block("> quoted text");
        assert_eq!(typ, "quote");
        assert_eq!(content, "quoted text");
    }

    #[test]
    fn test_classify_block_hr_dash() {
        let (typ, _, _, _, _, _) = classify_block("---");
        assert_eq!(typ, "hr");
    }

    #[test]
    fn test_classify_block_hr_star() {
        let (typ, _, _, _, _, _) = classify_block("***");
        assert_eq!(typ, "hr");
    }

    #[test]
    fn test_classify_block_paragraph() {
        let (typ, _, _, _, _, content) = classify_block("Just a regular paragraph.");
        assert_eq!(typ, "paragraph");
        assert_eq!(content, "Just a regular paragraph.");
    }

    #[test]
    fn test_count_indent_no_indent() {
        assert_eq!(count_indent("hello"), 0);
    }

    #[test]
    fn test_count_indent_spaces() {
        assert_eq!(count_indent("  indented"), 2);
    }

    #[test]
    fn test_count_indent_tabs() {
        assert_eq!(count_indent("\t\tindented"), 2);
    }

    #[test]
    fn test_count_indent_mixed() {
        assert_eq!(count_indent("  \tindented"), 3);
    }

    #[test]
    fn test_find_block_refs_simple() {
        let refs = find_block_refs("See ((abc123)) for details");
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].0, "abc123");
        assert!(!refs[0].1); // not an embed
    }

    #[test]
    fn test_find_block_refs_multiple() {
        let refs = find_block_refs("((a)) and ((b)) and ((c))");
        assert_eq!(refs.len(), 3);
    }

    #[test]
    fn test_find_block_refs_embed() {
        let refs = find_block_refs("{{embed ((note:id:0001))}}");
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].0, "note:id:0001");
        assert!(refs[0].1); // is an embed
    }

    #[test]
    fn test_find_block_refs_none() {
        let refs = find_block_refs("No references here");
        assert!(refs.is_empty());
    }

    #[test]
    fn test_find_block_refs_empty_inner() {
        let refs = find_block_refs("Empty (()) parens");
        assert!(refs.is_empty());
    }

    #[test]
    fn test_is_date_format_valid() {
        assert!(is_date_format("2024-01-15"));
        assert!(is_date_format("1999-12-31"));
        assert!(is_date_format("2020-02-29"));
    }

    #[test]
    fn test_is_date_format_invalid() {
        assert!(!is_date_format("not-a-date"));
        assert!(!is_date_format("01-15-2024")); // wrong order
        assert!(!is_date_format("2024-1-15"));  // non-padded month
        assert!(!is_date_format(""));           // empty
        assert!(!is_date_format("2024-01"));    // too short
    }

    #[test]
    fn test_extract_title_from_markdown_h1() {
        let title = extract_title_from_markdown("# My Note\n\nContent here");
        assert_eq!(title, "My Note");
    }

    #[test]
    fn test_extract_title_from_markdown_tab_prefix() {
        let title = extract_title_from_markdown("#\tTab Title\n\nContent");
        assert_eq!(title, "Tab Title");
    }

    #[test]
    fn test_extract_title_from_markdown_h2_ignored() {
        // Only h1 (# ) is extracted
        let title = extract_title_from_markdown("## Subtitle\n\nContent");
        assert_eq!(title, "");
    }

    #[test]
    fn test_extract_title_fallback() {
        let title = extract_title_from_markdown("No heading\nJust text");
        assert_eq!(title, "");
    }

    #[test]
    fn test_extract_title_empty_content() {
        let title = extract_title_from_markdown("");
        assert_eq!(title, "");
    }
}

fn resolve_backlinks(ctx: &ReducerContext, source_id: &str, content: &str, now: i64) {
    // Parse [[wikilink]] or [[wikilink|display]] syntax
    for cap in content.split('[') {
        if !cap.starts_with('[') { continue; }
        let inner = match cap.find(']') {
            Some(end) => &cap[1..end],
            None => continue,
        };

        let (target_title, _display) = if let Some(pipe) = inner.find('|') {
            let t = inner[..pipe].trim();
            let d = inner[pipe+1..].trim();
            (t, if d.is_empty() { t } else { d })
        } else {
            let t = inner.trim();
            (t, t)
        };

        if target_title.is_empty() { continue; }

        // Find notes by title that match the target
        let matches: Vec<_> = ctx
            .db
            .note()
            .iter()
            .take(crate::MAX_RESULTS)
            .filter(|n: &Note| n.title == target_title && n.id != source_id)
            .map(|n| n.id.clone())
            .collect();

        if matches.is_empty() { continue; }

        for target_id in &matches {
            let bl = NoteBacklink {
                id: uuid_v4_uniq(ctx, |id| ctx.db.note_backlink().id().find(id).is_none(), 3),
                source_note_id: source_id.to_string(),
                target_note_id: target_id.clone(),
                display_text: _display.to_string(),
                created_at: now,
            };
            ctx.db.note_backlink().insert(bl);

            if let Some(mut target) = ctx.db.note().id().find(target_id) {
                target.backlink_count += 1;
                ctx.db.note().id().update(target);
            }
        }
    }
}
