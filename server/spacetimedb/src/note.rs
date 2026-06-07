use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// A note — markdown document with wikilink backlinking support.
/// Sits alongside the document/ingestion pipeline but is user-authored.
#[table(accessor = note, public)]
#[derive(Debug, Clone)]
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
    pub created_at: i64,
    pub updated_at: i64,
    pub is_active: bool,
}

/// A backlink — forward edge from note A → note B ([[wikilink]]).
#[table(accessor = note_backlink, public)]
#[derive(Debug, Clone)]
pub struct NoteBacklink {
    #[primary_key]
    pub id: String,
    /// The note that contains the [[wikilink]]
    pub source_note_id: String,
    /// The note being linked to
    pub target_note_id: String,
    /// The display text used in the wikilink (e.g. "My Note" from [[My Note]])
    pub display_text: String,
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
    let now = now_micros(ctx);
    let id = uuid_v4(ctx);

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
        content,
        note_date,
        embedding_json: if embedding_json.is_empty() { String::from("[]") } else { embedding_json },
        backlink_count: 0,
        created_at: now,
        updated_at: now,
        is_active: true,
    };

    ctx.db.note().insert(note);

    // Parse and insert backlinks — borrow content from the struct
    if let Some(n) = ctx.db.note().id().find(&id) {
        resolve_backlinks(ctx, &id, &n.content, now);
    }

    Ok(())
}

#[reducer]
pub fn update_note(
    ctx: &ReducerContext,
    id: String,
    title: String,
    content: String,
    embedding_json: String,
) -> Result<(), String> {
    let now = now_micros(ctx);

    let mut note = ctx
        .db
        .note()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Note '{}' not found", id))?;

    let final_title = if title.is_empty() {
        extract_title_from_markdown(&content)
    } else {
        title
    };

    note.title = final_title;
    note.content = content.clone();
    note.updated_at = now;
    if !embedding_json.is_empty() {
        note.embedding_json = embedding_json;
    }
    ctx.db.note().id().update(note);

    // Re-parse backlinks: delete old ones, insert new ones
    let old_links: Vec<_> = ctx
        .db
        .note_backlink()
        .iter()
        .filter(|bl: &NoteBacklink| bl.source_note_id == id)
        .map(|bl| bl.id.clone())
        .collect();
    for link_id in &old_links {
        // Decrement target backlink_count
        if let Some(bl) = ctx.db.note_backlink().id().find(link_id) {
            if let Some(mut target) = ctx.db.note().id().find(&bl.target_note_id) {
                target.backlink_count = target.backlink_count.saturating_sub(1);
                ctx.db.note().id().update(target);
            }
        }
        ctx.db.note_backlink().id().delete(link_id);
    }

    resolve_backlinks(ctx, &id, &content, now);

    Ok(())
}

#[reducer]
pub fn delete_note(ctx: &ReducerContext, id: String) -> Result<(), String> {
    // Clean up backlinks
    let backlinks: Vec<_> = ctx
        .db
        .note_backlink()
        .iter()
        .filter(|bl: &NoteBacklink| bl.source_note_id == id || bl.target_note_id == id)
        .map(|bl| bl.id.clone())
        .collect();
    for bl_id in &backlinks {
        if let Some(bl) = ctx.db.note_backlink().id().find(bl_id) {
            if let Some(mut target) = ctx.db.note().id().find(&bl.target_note_id) {
                target.backlink_count = target.backlink_count.saturating_sub(1);
                ctx.db.note().id().update(target);
            }
        }
        ctx.db.note_backlink().id().delete(bl_id);
    }

    ctx.db.note().id().delete(&id);
    Ok(())
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

fn resolve_backlinks(ctx: &ReducerContext, source_id: &str, content: &str, now: i64) {
    // Parse [[wikilink]] or [[wikilink|display]] syntax
    for cap in content.split('[') {
        if !cap.starts_with('[') { continue; }
        let inner = match cap.find(']') {
            Some(end) => &cap[1..end],  // skip the first [
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
            .filter(|n: &Note| n.title == target_title && n.id != source_id)
            .map(|n| n.id.clone())
            .collect();

        // If no exact match, don't create backlinks (orphan wikilink — still try fuzzy)
        // We just skip backlinks for non-existent targets; the link still renders
        if matches.is_empty() {
            // Still store a backlink with empty target? No, that creates garbage.
            // The frontend will render [[Unknown Note]] as a dead link instead.
            continue;
        }

        for target_id in &matches {
            let bl = NoteBacklink {
                id: uuid_v4(ctx),
                source_note_id: source_id.to_string(),
                target_note_id: target_id.clone(),
                display_text: _display.to_string(),
                created_at: now,
            };
            ctx.db.note_backlink().insert(bl);

            // Increment target backlink count
            if let Some(mut target) = ctx.db.note().id().find(target_id) {
                target.backlink_count += 1;
                ctx.db.note().id().update(target);
            }
        }
    }
}
