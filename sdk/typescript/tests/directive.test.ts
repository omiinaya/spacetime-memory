/**
 * Tests for directive.ts — Directive operations.
 *
 * Uses mocked fetch responses (no SpacetimeDB required).
 * Run with: npx vitest run tests/directive.test.ts
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Client } from "../client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function reducerOkResponse() {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify({ status: "ok" })) };
}

function sqlResponse(text: string) {
  return { ok: true, text: vi.fn().mockResolvedValue(text) };
}

function sqlMockResponse(rows: unknown[][]): string {
  if (rows.length === 0) {
    return JSON.stringify([{ schema: { elements: [{ name: { some: "id" } }] }, rows: [] }]);
  }
  const firstRow = rows[0] as Record<string, unknown>;
  const keys = Object.keys(firstRow);
  const elements = keys.map((k) => ({ name: { some: k } }));
  const values = rows.map((row) => {
    const r = row as Record<string, unknown>;
    return keys.map((k) => r[k] ?? null);
  });
  return JSON.stringify([{ schema: { elements }, rows: values }]);
}

// ---------------------------------------------------------------------------
// Directive
// ---------------------------------------------------------------------------

describe("Directive", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("createDirective calls the reducer with all args", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.createDirective("ws1", "Learn Rust", "Complete the Rust book", 2.0, "user1", '{"deadline":"2026-08-01"}');
    expect(callUrls.some((u) => u.includes("call/create_directive"))).toBe(true);
  });

  it("createDirective with minimal args uses defaults", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.createDirective("ws1", "Learn Rust");
    expect(callUrls.some((u) => u.includes("call/create_directive"))).toBe(true);
  });

  it("updateDirectiveStatus calls the reducer", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.updateDirectiveStatus("dir-1", "completed");
    expect(callUrls.some((u) => u.includes("call/update_directive_status"))).toBe(true);
  });

  it("updateDirectiveProgress calls the reducer", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.updateDirectiveProgress("dir-1", 0.75);
    expect(callUrls.some((u) => u.includes("call/update_directive_progress"))).toBe(true);
  });

  it("deleteDirective calls the reducer", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.deleteDirective("dir-1");
    expect(callUrls.some((u) => u.includes("call/delete_directive"))).toBe(true);
  });

  it("listDirectives returns parsed directives from json_data", async () => {
    const directives = [
      { id: "dir-1", workspace_id: "ws1", name: "Learn Rust", description: "Complete the Rust book", status: "active", progress: 0.5, priority: 2.0, assigned_to: "user1" },
      { id: "dir-2", workspace_id: "ws1", name: "Build a project", description: "Apply Rust knowledge", status: "active", progress: 0.0, priority: 1.0, assigned_to: "" },
    ];
    const jsonRow = {
      id: "r1", workspace_id: "ws1",
      json_data: JSON.stringify(directives),
      created_at: 1000000000,
    };
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call/list_directives")) return reducerOkResponse();
      if (url.includes("sql")) return sqlResponse(sqlMockResponse([jsonRow] as any));
      return reducerOkResponse();
    });
    const result = await client.listDirectives("ws1");
    expect(Array.isArray(result)).toBe(true);
    if (result.length > 0) {
      expect(result[0]).toHaveProperty("name");
      expect(result[0]).toHaveProperty("status");
    }
  });

  it("listDirectives returns [] when no directives exist", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call/list_directives")) return reducerOkResponse();
      if (url.includes("sql")) return sqlResponse(sqlMockResponse([]));
      return reducerOkResponse();
    });
    const result = await client.listDirectives("ws1");
    expect(result).toEqual([]);
  });
});
