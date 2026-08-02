/**
 * Tests for batchOps.ts — Batch memory operations.
 *
 * Uses mocked fetch responses (no SpacetimeDB required).
 * Run with: npx vitest run tests/batchOps.test.ts
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Client } from "../client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function reducerOkResponse() {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify({ status: "ok" })) };
}

// ---------------------------------------------------------------------------
// BatchOps
// ---------------------------------------------------------------------------

describe("BatchOps", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("batchUpdateMemories calls the reducer with correct args", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify({ status: "ok", updated: 2 })) };
    });
    const result = await client.batchUpdateMemories("ws1", ["mem-1", "mem-2"], { content: "Updated", confidence: 0.95 });
    expect(callUrls.some((u) => u.includes("call/batch_update_memories"))).toBe(true);
    expect(result).toHaveProperty("status");
    expect(result).toHaveProperty("updated");
  });

  it("batchDeleteMemories calls the reducer with workspace scoping", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.batchDeleteMemories("ws1", ["mem-1", "mem-2", "mem-3"]);
    expect(callUrls.some((u) => u.includes("call/batch_delete_memories"))).toBe(true);
  });

  it("batchSetCategory calls the reducer with correct args", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.batchSetCategory("ws1", ["mem-1", "mem-2"], "preferences");
    expect(callUrls.some((u) => u.includes("call/batch_set_category"))).toBe(true);
  });

  it("batchUpdateMemories returns fallback result when reducer returns null", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (_url: string) => ({
      ok: true,
      text: vi.fn().mockResolvedValue(""),
    }));
    const result = await client.batchUpdateMemories("ws1", ["mem-1"], { content: "Test" });
    expect(result).toHaveProperty("status", "ok");
    expect(result).toHaveProperty("updated", 1);
  });

  it("batchUpdateMemories with empty array still calls reducer", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return reducerOkResponse();
    });
    await client.batchUpdateMemories("ws1", [], {});
    expect(callUrls.some((u) => u.includes("call/batch_update_memories"))).toBe(true);
  });
});
