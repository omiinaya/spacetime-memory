use spacetimedb::*;
use crate::auth::require_auth;
use crate::crypto::encrypt_if_enabled;
use crate::trace_span;
use crate::tracing::TracingSpanKind;

use crate::{now_micros, uuid_v4_uniq};
use crate::workspace::check_space_access;

/// A document ingested into the workspace.
#[table(accessor = document)]
#[derive(Debug, Clone)]
pub struct Document {
    #[primary_key]
    pub id: String,
    #[index(btree)]
    pub workspace_id: String,
    pub title: String,
    pub content: String,
    /// "pdf" | "image" | "video" | "code" | "text" | "url"
    pub content_type: String,
    pub file_path: String,
    pub source_url: String,
    /// JSON metadata blob
    pub metadata_json: String,
    pub chunk_count: u32,
    pub created_at: i64,
    pub updated_at: i64,
}

/// A chunk of a document, holding a segment of content and its embedding.
#[table(accessor = doc_chunk)]
#[derive(Debug, Clone)]
pub struct DocChunk {
    #[primary_key]
    pub id: String,
    pub document_id: String,
    pub content: String,
    pub chunk_index: u32,
    /// JSON array of f64 embeddings
    pub embedding_json: String,
    pub created_at: i64,
}

// ---------------------------------------------------------------------------
// Document reducers
// ---------------------------------------------------------------------------

#[reducer]
pub fn create_document(
    ctx: &ReducerContext,
    workspace_id: String,
    title: String,
    content: String,
    content_type: String,
    file_path: String,
    source_url: String,
    metadata_json: String,
) -> Result<(), String> {
    trace_span!(ctx, "create_document", TracingSpanKind::Write, &workspace_id, {
    let _account = require_auth(ctx)?;
    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &workspace_id, &caller, "editor")?;
    let now = now_micros(ctx);
    let id = uuid_v4_uniq(ctx, |id| ctx.db.document().id().find(id).is_none(), 3);

    // Validate content_type
    match content_type.as_str() {
        "pdf" | "image" | "video" | "code" | "text" | "url" => {}
        _ => {
            return Err(format!(
                "Invalid content_type '{}': must be 'pdf', 'image', 'video', 'code', 'text', or 'url'",
                content_type
            ));
        }
    }

    let doc_content = content.clone();

    // Encrypt content if workspace encryption is enabled; keep plaintext for auto-chunking
    let enc_content = encrypt_if_enabled(ctx, &workspace_id, &content)?;
    let doc = Document {
        id: id.clone(),
        workspace_id: workspace_id.clone(),
        title,
        content: enc_content,
        content_type,
        file_path,
        source_url,
        metadata_json: if metadata_json.is_empty() {
            String::from("{}")
        } else {
            metadata_json
        },
        chunk_count: 0,
        created_at: now,
        updated_at: now,
    };

    ctx.db.document().insert(doc);

    // ── Auto-chunk on create ────────────────────────────────────
    // If content is non-trivial (≥100 chars), split into overlapping
    // chunks of ~500 chars. Chunks get stored in doc_chunk but NOT
    // auto-indexed (embeddings require the embedder sidecar).
    // The SDK can call index_chunks() later to add embeddings.
    if doc_content.len() >= 100 {
        let chunks = chunk_text(&doc_content, 500, 50);
        for (i, chunk_text) in chunks.iter().enumerate() {
            let enc_chunk_content = encrypt_if_enabled(ctx, &workspace_id, chunk_text)?;
            let chunk = DocChunk {
                id: uuid_v4_uniq(ctx, |id| ctx.db.doc_chunk().id().find(id).is_none(), 3),
                document_id: id.clone(),
                content: enc_chunk_content,
                chunk_index: i as u32,
                embedding_json: String::from("[]"), // no embedding yet
                created_at: now,
            };
            ctx.db.doc_chunk().insert(chunk);
        }
        // Update chunk count
        if let Some(mut d) = ctx.db.document().id().find(&id) {
            d.chunk_count = chunks.len() as u32;
            ctx.db.document().id().update(d);
        }
    }

    Ok(())
    })
}

/// Split text into overlapping chunks of `chunk_size` chars
/// with `overlap` chars between consecutive chunks.
fn chunk_text(text: &str, chunk_size: usize, overlap: usize) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    if chars.len() <= chunk_size {
        return vec![text.to_string()];
    }

    let _step = chunk_size.saturating_sub(overlap).max(1);
    let mut chunks = Vec::new();
    let mut start = 0;
    while start < chars.len() {
        let end = (start + chunk_size).min(chars.len());
        // Try to break at sentence boundary (., !, ?, newline)
        let mut break_at = end;
        if end < chars.len() {
            for i in ((start + chunk_size / 2).max(start)..end).rev() {
                if chars[i] == '.' || chars[i] == '!' || chars[i] == '?' || chars[i] == '\n' {
                    break_at = i + 1;
                    break;
                }
            }
        }
        let chunk: String = chars[start..break_at].iter().collect();
        if !chunk.trim().is_empty() {
            chunks.push(chunk);
        }
        start = break_at.saturating_sub(overlap).max(start + 1);
    }
    chunks
}

#[reducer]
pub fn add_chunk(
    ctx: &ReducerContext,
    document_id: String,
    content: String,
    chunk_index: u32,
    embedding_json: String,
) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let now = now_micros(ctx);
    let id = uuid_v4_uniq(ctx, |id| ctx.db.doc_chunk().id().find(id).is_none(), 3);

    // Verify that the parent document exists
    let mut doc = ctx
        .db
        .document()
        .id()
        .find(&document_id)
        .ok_or_else(|| format!("Document '{}' not found", document_id))?;

    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &doc.workspace_id, &caller, "editor")?;

    // Encrypt chunk content if workspace encryption is enabled
    let enc_content = encrypt_if_enabled(ctx, &doc.workspace_id, &content)?;
    let chunk = DocChunk {
        id: id.clone(),
        document_id: document_id.clone(),
        content: enc_content,
        chunk_index,
        embedding_json: if embedding_json.is_empty() {
            String::from("[]")
        } else {
            embedding_json
        },
        created_at: now,
    };

    ctx.db.doc_chunk().insert(chunk);

    // Update the document's chunk count
    doc.chunk_count += 1;
    doc.updated_at = now;
    ctx.db.document().id().update(doc);

    Ok(())
}

#[reducer]
pub fn delete_document(ctx: &ReducerContext, id: String) -> Result<(), String> {
    let _account = require_auth(ctx)?;
    let doc = ctx
        .db
        .document()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Document '{}' not found", id))?;

    let caller = ctx.sender().to_hex();
    check_space_access(ctx, &doc.workspace_id, &caller, "editor")?;

    // Cascade-delete all chunks belonging to this document
    let chunks: Vec<_> = ctx
        .db
        .doc_chunk()
        .iter().take(crate::MAX_RESULTS)
        .filter(|c| c.document_id == id)
        .collect();
    for c in chunks {
        ctx.db.doc_chunk().id().delete(&c.id);
    }

    ctx.db.document().id().delete(&id);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_chunk_text_short_content() {
        let chunks = chunk_text("hello world", 500, 50);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0], "hello world");
    }

    #[test]
    fn test_chunk_text_long_content() {
        let text = "A".repeat(1200);
        let chunks = chunk_text(&text, 500, 50);
        assert!(chunks.len() >= 2, "expected at least 2 chunks, got {}", chunks.len());
        // Each chunk should be roughly 500 chars (except last)
        for (i, c) in chunks.iter().enumerate() {
            if i < chunks.len() - 1 {
                assert!(c.len() <= 510, "chunk {} too long: {}", i, c.len());
            }
        }
    }

    #[test]
    fn test_chunk_text_sentence_boundary() {
        let text = format!(
            "{}. {}! {}? {}\n{}",
            "A".repeat(300), "B".repeat(300), "C".repeat(300), "D".repeat(300), "E".repeat(100)
        );
        let chunks = chunk_text(&text, 500, 50);
        assert!(chunks.len() >= 2, "expected at least 2 chunks, got {}", chunks.len());
        // First chunk should end with a sentence boundary
        let first = &chunks[0];
        assert!(
            first.ends_with('.') || first.ends_with('!') || first.ends_with('?') || first.ends_with('\n'),
            "first chunk should end at sentence boundary, got: ...{}",
            &first[first.len().saturating_sub(20)..]
        );
    }

    #[test]
    fn test_chunk_text_empty() {
        let chunks = chunk_text("", 500, 50);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0], "");
    }
}
