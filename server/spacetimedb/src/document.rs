use spacetimedb::*;

use crate::{now_micros, uuid_v4};

/// A document ingested into the workspace.
#[table(accessor = document, public)]
#[derive(Debug, Clone)]
pub struct Document {
    #[primary_key]
    pub id: String,
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
#[table(accessor = doc_chunk, public)]
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
    let now = now_micros();
    let id = uuid_v4();

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

    let doc = Document {
        id: id.clone(),
        workspace_id,
        title,
        content,
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
    Ok(())
}

#[reducer]
pub fn add_chunk(
    ctx: &ReducerContext,
    document_id: String,
    content: String,
    chunk_index: u32,
    embedding_json: String,
) -> Result<(), String> {
    let now = now_micros();
    let id = uuid_v4();

    // Verify that the parent document exists
    let mut doc = ctx
        .db
        .document()
        .id()
        .find(&document_id)
        .ok_or_else(|| format!("Document '{}' not found", document_id))?;

    let chunk = DocChunk {
        id: id.clone(),
        document_id: document_id.clone(),
        content,
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
    ctx.db
        .document()
        .id()
        .find(&id)
        .ok_or_else(|| format!("Document '{}' not found", id))?;

    ctx.db.document().id().delete(&id);
    Ok(())
}
