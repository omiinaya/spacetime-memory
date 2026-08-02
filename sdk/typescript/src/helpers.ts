/**
 * Shared helper functions used across domain modules.
 */
import type { ClientLike } from "./types";

/** Escape a string for safe SQL equality context. Doubles single quotes, escapes backslashes. */
export function esc(val: string): string {
  return val.replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "''");
}

/**
 * Escape a string for safe SQL LIKE context.
 * Escapes single quotes, backslashes, and LIKE wildcards (% and _).
 * Always use with ESCAPE '\\' in the SQL clause.
 */
export function escLike(val: string): string {
  return esc(val).replace(/%/g, '\\\\%').replace(/_/g, '\\\\_');
}

/**
 * The STDB v2 SQL endpoint supports only SELECT / WHERE (=, AND, OR) / LIMIT.
 * ORDER BY and LIKE are rejected — sort and filter client-side instead.
 */
export function sortByCreatedDesc(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  return rows.sort((a, b) => Number(b.created_at ?? 0) - Number(a.created_at ?? 0));
}
export function sortByCreatedAsc(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  return rows.sort((a, b) => Number(a.created_at ?? 0) - Number(b.created_at ?? 0));
}
export function jsLike(value: unknown, needle: string): boolean {
  return String(value ?? "").toLowerCase().includes(needle.toLowerCase());
}

/**
 * Ensure an identifier (table name, column name) contains only safe characters.
 * Throws if the identifier contains SQL-metacharacters that could facilitate injection.
 */
export function safeIdent(name: string): string {
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name)) {
    throw new Error(`Invalid SQL identifier — contains unsafe characters: "${name}"`);
  }
  return name;
}

/**
 * Numeric placeholder helper for _sqlExec. Returns the raw number as a SQL-safe literal,
 * or 0 if undefined/null.
 */
export function safeNum(n: number | undefined | null): string {
  if (n == null) return "0";
  const clamped = isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
  return String(clamped);
}

/**
 * Simple fnmatch-style glob matching (supports * and ? wildcards).
 * Case-sensitive comparison — caller should lowercase both arguments.
 */
export function fnmatch(text: string, pattern: string): boolean {
  let regexStr = "^";
  for (let i = 0; i < pattern.length; i++) {
    const ch = pattern[i];
    if (ch === "*") {
      regexStr += ".*";
    } else if (ch === "?") {
      regexStr += ".";
    } else if (ch === "." || ch === "+" || ch === "(" || ch === ")" || ch === "[" || ch === "]" || ch === "{" || ch === "}" || ch === "\\" || ch === "|" || ch === "^" || ch === "$") {
      regexStr += "\\" + ch;
    } else {
      regexStr += ch;
    }
  }
  regexStr += "$";
  return new RegExp(regexStr).test(text);
}

export function queryHash(query: string): string {
  let h = 0;
  for (let i = 0; i < query.length; i++) {
    h = (Math.imul(h, 6364136223846793005) + query.charCodeAt(i)) >>> 0;
  }
  return h.toString(16).padStart(16, "0");
}

/**
 * Parse a SpacetimeDB SQL HTTP response into a flat array of objects.
 */
export function parseSqlResponse(raw: string): Record<string, unknown>[] {
  if (!raw.trim()) return [];
  const tables: unknown[] = JSON.parse(raw);
  const results: Record<string, unknown>[] = [];
  for (const table of tables) {
    const tbl = table as Record<string, unknown>;
    const elements = ((tbl?.schema as Record<string, unknown>)?.elements ?? []) as Record<string, unknown>[];
    const colNames: string[] = elements.map(
      (el: Record<string, unknown>) => ((el?.name as Record<string, string>)?.some ?? "?col?")
    );
    for (const row of (tbl?.rows as unknown[][]) ?? []) {
      const r: Record<string, unknown> = {};
      for (let i = 0; i < colNames.length; i++) {
        r[colNames[i]] = row[i];
      }
      results.push(r);
    }
  }
  return results;
}
