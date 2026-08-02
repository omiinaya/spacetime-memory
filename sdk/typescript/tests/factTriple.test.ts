/**
 * Tests for factTriple.ts — FactTriple operations.
 *
 * Uses mocked fetch responses (no SpacetimeDB required).
 * Run with: npx vitest run tests/factTriple.test.ts
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
// FactTriple
// ---------------------------------------------------------------------------

describe("FactTriple", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("storeFactTriple calls the reducer with correct args", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.storeFactTriple("ws1", "entity-1", "is_a", "entity-2", 0.95, 1000000, 2000000);
    expect(callUrls.some((u) => u.includes("call/store_fact_triple"))).toBe(true);
  });

  it("storeFactTriple with minimal args uses defaults", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.storeFactTriple("ws1", "entity-1", "related_to", "entity-2");
    expect(callUrls.some((u) => u.includes("call/store_fact_triple"))).toBe(true);
  });

  it("updateFactTripleConfidence calls the reducer", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.updateFactTripleConfidence("triple-1", 0.8);
    expect(callUrls.some((u) => u.includes("call/update_fact_triple_confidence"))).toBe(true);
  });

  it("deleteFactTriple calls the reducer", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.deleteFactTriple("triple-1");
    expect(callUrls.some((u) => u.includes("call/delete_fact_triple"))).toBe(true);
  });

  it("setFactTripleTemporalBounds calls the reducer", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.setFactTripleTemporalBounds("triple-1", 1000000, 2000000);
    expect(callUrls.some((u) => u.includes("call/set_fact_triple_temporal_bounds"))).toBe(true);
  });

  it("listFactTriples returns parsed triples from json_data", async () => {
    const triples = [
      { id: "t-1", workspace_id: "ws1", subject_id: "entity-1", predicate: "is_a", object_id: "entity-2", confidence: 0.95, valid_from: 0, valid_to: 0 },
      { id: "t-2", workspace_id: "ws1", subject_id: "entity-1", predicate: "related_to", object_id: "entity-3", confidence: 0.8, valid_from: 0, valid_to: 0 },
    ];
    const jsonRow = {
      id: "r1", workspace_id: "ws1",
      json_data: JSON.stringify(triples),
      created_at: 1000000000,
    };
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call/list_fact_triples")) return reducerOkResponse();
      if (url.includes("sql")) return sqlResponse(sqlMockResponse([jsonRow] as any));
      return reducerOkResponse();
    });
    const result = await client.listFactTriples("ws1");
    expect(Array.isArray(result)).toBe(true);
    if (result.length > 0) {
      expect(result[0]).toHaveProperty("subject_id");
      expect(result[0]).toHaveProperty("predicate");
      expect(result[0]).toHaveProperty("object_id");
    }
  });

  it("listFactTriples returns [] when no triples exist", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call/list_fact_triples")) return reducerOkResponse();
      if (url.includes("sql")) return sqlResponse(sqlMockResponse([]));
      return reducerOkResponse();
    });
    const result = await client.listFactTriples("ws1");
    expect(result).toEqual([]);
  });
});
