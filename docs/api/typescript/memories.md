# memories

Source: `sdk/typescript/src/memories.ts`

## API Reference

### tantivySearch

Memory operations — store, update, delete, get, search.
/
import type { ClientLike, MemoryRecord, SearchResult, SearchOptions, StoreOptions, ListMemoriesOptions, MemoryRevisionRecord, CrossEncoderRerankOptions } from "./types";
import { IMAGES_CONTEXT_PREFIX } from "./types";
import { sortByCreatedDesc, sortByCreatedAsc, fnmatch, queryHash, esc, escLike } from "./helpers";
/** Tantivy BM25 full-text search.

---
