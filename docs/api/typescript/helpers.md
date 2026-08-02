# helpers

Source: `sdk/typescript/src/helpers.ts`

## API Reference

### esc

Shared helper functions used across domain modules.
/
import type { ClientLike } from "./types";
/** Escape a string for safe SQL equality context. Doubles single quotes, escapes backslashes.

---

### escLike

Escape a string for safe SQL LIKE context.
Escapes single quotes, backslashes, and LIKE wildcards (% and _).
Always use with ESCAPE '\\' in the SQL clause.

---

### sortByCreatedDesc

The STDB v2 SQL endpoint supports only SELECT / WHERE (=, AND, OR) / LIMIT.
ORDER BY and LIKE are rejected — sort and filter client-side instead.

---

### safeIdent

Ensure an identifier (table name, column name) contains only safe characters.
Throws if the identifier contains SQL-metacharacters that could facilitate injection.

---

### safeNum

Numeric placeholder helper for _sqlExec. Returns the raw number as a SQL-safe literal,
or 0 if undefined/null.

---

### fnmatch

Simple fnmatch-style glob matching (supports * and ? wildcards).
Case-sensitive comparison — caller should lowercase both arguments.

---

### parseSqlResponse

Parse a SpacetimeDB SQL HTTP response into a flat array of objects.

---
