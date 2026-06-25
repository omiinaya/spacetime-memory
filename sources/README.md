# Raw Sources

Place source documents here for ingestion into the wiki.

## Convention

This directory is the **raw sources layer** from the [LLM Wiki pattern](../AGENTS.md):

> Raw sources — your curated collection of source documents. Articles, papers,
> images, data files. These are immutable — the LLM reads from them but never
> modifies them. This is your source of truth.

## Usage

```bash
# Ingest a source file into the wiki
stmem ingest file sources/my-article.md --title "My Article" --source-type article --workspace default

# Or from a URL (save it first)
curl -sL "https://example.com/article" > sources/article.html
stmem ingest file sources/article.html --title "Example Article"
```

## Organization

- `articles/` — news articles, blog posts, long-form content
- `papers/` — academic papers, research reports
- `transcripts/` — meeting transcripts, podcast transcripts
- `notes/` — personal notes, journal entries
- `data/` — structured data files, CSVs, JSON dumps

Mark files with a date prefix for chronological sorting if desired:
`2026-06-25_my-article.md`
