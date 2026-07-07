import re

with open('server/spacetimedb/src/note.rs', 'r') as f:
    content = f.read()

# 1. Insert BacklinkResult table after NoteBacklink
# Find the closing of NoteBacklink and insert BacklinkResult before NoteBlock
old_block_comment = '/// A block \u2014 individual paragraph/heading/list-item within a note.'
backlink_table = '''/// Stores the result of a get_backlinks / get_outgoing_links query (public for SQL reads).
/// Transient \u2014 contents are replaced on each query call.
#[table(accessor = backlink_result, public)]
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct BacklinkResult {
    #[primary_key]
    pub id: String,
    /// Source note ID (the note containing the [[wikilink]])
    pub source_note_id: String,
    pub source_note_title: String,
    /// Target note ID (the note being linked to)
    pub target_note_id: String,
    pub target_note_title: String,
    /// Display text used in the wikilink
    pub display_text: String,
    pub created_at: i64,
}

'''

content = content.replace(
    old_block_comment,
    backlink_table + old_block_comment,
    1
)

# 2. Insert get_backlinks and get_outgoing_links reducers after delete_note
old_marker = '// ---------------------------------------------------------------------------\n// Block parsing reducer (callable standalone or from create/update)\n// ---------------------------------------------------------------------------\n\n#[reducer]\npub fn parse_note_blocks'

new_reducers = '''// ---------------------------------------------------------------------------
// Backlink / outgoing-link query reducers
// ---------------------------------------------------------------------------

/// Get all backlinks pointing *to* a specific note.
/// Populates the public backlink_result table for SQL reads.
#[reducer]
pub fn get_backlinks(ctx: &ReducerContext, note_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    // Clear stale results from previous queries
    let stale: Vec<_> = ctx
        .db
        .backlink_result()
        .iter()
        .take(crate::MAX_RESULTS * 2)
        .map(|r: &BacklinkResult| r.id.clone())
        .collect();
    for id in &stale {
        ctx.db.backlink_result().id().delete(id);
    }

    // Collect note titles for efficient lookup
    let mut note_titles: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    for n in ctx.db.note().iter().take(crate::MAX_RESULTS) {
        note_titles.insert(n.id.clone(), n.title.clone());
    }

    // Find all backlinks targeting this note
    for bl in ctx.db.note_backlink().iter().take(crate::MAX_RESULTS * 2) {
        if bl.target_note_id == note_id {
            let source_title = note_titles.get(&bl.source_note_id).cloned().unwrap_or_default();
            let target_title = note_titles.get(&bl.target_note_id).cloned().unwrap_or_default();
            ctx.db.backlink_result().insert(BacklinkResult {
                id: uuid_v4_uniq(ctx, |id| ctx.db.backlink_result().id().find(id).is_none(), 3),
                source_note_id: bl.source_note_id.clone(),
                source_note_title: source_title,
                target_note_id: bl.target_note_id.clone(),
                target_note_title: target_title,
                display_text: bl.display_text.clone(),
                created_at: now,
            });
        }
    }

    Ok(())
}

/// Get all outgoing links from a specific note.
/// Populates the public backlink_result table for SQL reads.
#[reducer]
pub fn get_outgoing_links(ctx: &ReducerContext, note_id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);

    // Clear stale results from previous queries
    let stale: Vec<_> = ctx
        .db
        .backlink_result()
        .iter()
        .take(crate::MAX_RESULTS * 2)
        .map(|r: &BacklinkResult| r.id.clone())
        .collect();
    for id in &stale {
        ctx.db.backlink_result().id().delete(id);
    }

    // Collect note titles for efficient lookup
    let mut note_titles: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    for n in ctx.db.note().iter().take(crate::MAX_RESULTS) {
        note_titles.insert(n.id.clone(), n.title.clone());
    }

    // Find all outgoing links from this note
    for bl in ctx.db.note_backlink().iter().take(crate::MAX_RESULTS * 2) {
        if bl.source_note_id == note_id {
            let source_title = note_titles.get(&bl.source_note_id).cloned().unwrap_or_default();
            let target_title = note_titles.get(&bl.target_note_id).cloned().unwrap_or_default();
            ctx.db.backlink_result().insert(BacklinkResult {
                id: uuid_v4_uniq(ctx, |id| ctx.db.backlink_result().id().find(id).is_none(), 3),
                source_note_id: bl.source_note_id.clone(),
                source_note_title: source_title,
                target_note_id: bl.target_note_id.clone(),
                target_note_title: target_title,
                display_text: bl.display_text.clone(),
                created_at: now,
            });
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Block parsing reducer (callable standalone or from create/update)
// ---------------------------------------------------------------------------

#[reducer]
pub fn parse_note_blocks'''

content = content.replace(old_marker, new_reducers, 1)

with open('server/spacetimedb/src/note.rs', 'w') as f:
    f.write(content)

print(f'Done: {len(content.splitlines())} lines')
