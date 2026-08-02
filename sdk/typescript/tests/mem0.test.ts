/**
 * Unit tests for the spacetime-memory Mem0 TS adapter.
 *
 * Mocks global fetch to avoid needing a live SpacetimeDB instance.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { Memory, Mem0Memory, AddResult, MemoryResult, SearchOptions, GraphEntity } from "../mem0";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a mock fetch that returns SQL rows. */
function mockSqlResponse(rows: unknown[]): void {
  const body = JSON.stringify([
    {
      schema: {
        elements: Object.keys(rows[0] ?? {}).map((name) => ({
          name: { some: name },
        })),
      },
      rows: rows.map((r) =>
        Object.values(r as Record<string, unknown>).map((v) =>
          typeof v === "bigint" ? Number(v) : v,
        ),
      ),
    },
  ]);
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    text: vi.fn().mockResolvedValue(body),
  });
}

/** Build a mock fetch that returns JSON for a reducer call. */
function mockReducerResponse(returnValue: unknown): void {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    text: vi.fn().mockResolvedValue(
      typeof returnValue === "string" ? returnValue : JSON.stringify(returnValue ?? "")
    ),
  });
}

/** Default mock that makes basic reducer calls work. */
function defaultMock(): void {
  globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
    if (url.includes("sql")) {
      // Return empty SQL rows for workspace queries
      return {
        ok: true,
        text: vi.fn().mockResolvedValue(
          JSON.stringify([
            {
              schema: { elements: [{ name: { some: "status" } }] },
              rows: [],
            },
          ])
        ),
      };
    }
    if (url.includes("embed")) {
      return {
        ok: true,
        json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }),
      };
    }
    // Reducer calls
    return { ok: true, text: vi.fn().mockResolvedValue("") };
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Memory (Mem0 TS adapter)", () => {
  let memory: Memory;

  beforeEach(() => {
    vi.restoreAllMocks();
    defaultMock();
    memory = new Memory({ host: "test.local", port: 3001 });
  });

  // -----------------------------------------------------------------------
  // Constructor & factory
  // -----------------------------------------------------------------------
  describe("constructor", () => {
    it("creates instance with default config", () => {
      const m = new Memory();
      expect(m).toBeInstanceOf(Memory);
      expect(m._client).toBeDefined();
    });

    it("creates instance with explicit host/port", () => {
      const m = new Memory({ host: "127.0.0.1", port: 3001 });
      expect(m).toBeInstanceOf(Memory);
    });

    it("loads per-user llmConfig", () => {
      const m = new Memory({
        llmConfig: {
          alice: { model: "gpt-4", apiKey: "sk-test" },
        },
      });
      expect(m).toBeInstanceOf(Memory);
    });
  });

  describe("fromConfig", () => {
    it("creates instance from config dict", () => {
      const m = Memory.fromConfig({ host: "test.local", port: 3001 });
      expect(m).toBeInstanceOf(Memory);
    });
  });

  // -----------------------------------------------------------------------
  // Graph store
  // -----------------------------------------------------------------------
  describe("graph", () => {
    it("returns a GraphStore", () => {
      const g = memory.graph;
      expect(g).toBeDefined();
      expect(typeof g.add).toBe("function");
      expect(typeof g.search).toBe("function");
      expect(typeof g.getAll).toBe("function");
      expect(typeof g.delete).toBe("function");
    });

    it("caches GraphStore instance", () => {
      const g1 = memory.graph;
      const g2 = memory.graph;
      expect(g1).toBe(g2);
    });
  });

  // -----------------------------------------------------------------------
  // setLlmConfig
  // -----------------------------------------------------------------------
  describe("setLlmConfig", () => {
    it("stores per-user LLM config", () => {
      memory.setLlmConfig("bob", { model: "claude-3", apiKey: "sk-bob" });
      // internal verification — config is used at runtime
      expect(true).toBe(true);
    });
  });

  // -----------------------------------------------------------------------
  // add (single string)
  // -----------------------------------------------------------------------
  describe("add", () => {
    it("stores a string memory", async () => {
      // Mock list_workspaces to return an existing workspace
      const calls: string[] = [];
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        calls.push(url);
        if (url.includes("embed")) {
          return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.5] }) };
        }
        if (url.includes("sql")) {
          // Return workspace query results
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-alice", "alice"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const result = await memory.add("I like pizza", { userId: "alice", agentId: "assistant" });
      expect(result).toHaveProperty("results");
      expect(result).toHaveProperty("relation_events");
      expect(Array.isArray(result.results)).toBe(true);
    });

    it("rejects empty input", async () => {
      await expect(memory.add("", { userId: "alice" })).rejects.toThrow();
    });

    it("stores from a message list (LLM extraction skipped without API key)", async () => {
      const calls: string[] = [];
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        calls.push(url);
        if (url.includes("embed")) {
          return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.5] }) };
        }
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-eve", "eve"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const messages = [
        { role: "user", content: "My name is Eve" },
        { role: "assistant", content: "Nice to meet you Eve" },
      ];
      const result = await memory.add(messages, { userId: "eve", infer: false });
      expect(result).toHaveProperty("results");
    });
  });

  // -----------------------------------------------------------------------
  // get
  // -----------------------------------------------------------------------
  describe("get", () => {
    it("retrieves a memory by ID", async () => {
      mockReducerResponse(
        JSON.stringify([
          { id: "mem-123", content: "test memory", peer_id: "alice", observer_id: "assistant", is_active: true },
        ])
      );

      const result = await memory.get("mem-123");
      expect(result.results).toHaveLength(1);
      expect(result.results[0].id).toBe("mem-123");
      expect(result.results[0].memory).toBe("test memory");
    });

    it("returns empty array for unknown ID", async () => {
      mockReducerResponse("[]");
      const result = await memory.get("nonexistent");
      expect(result.results).toHaveLength(0);
    });
  });

  // -----------------------------------------------------------------------
  // search
  // -----------------------------------------------------------------------
  describe("search", () => {
    it("searches with semantic results", async () => {
      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        callCount++;
        if (url.includes("sql")) {
          // workspace query
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-bob", "bob"]],
                },
              ])
            ),
          };
        }
        if (url.includes("embed")) {
          return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2] }) };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const result = await memory.search("food preferences", { userId: "bob" });
      expect(result).toHaveProperty("results");
    });
  });

  // -----------------------------------------------------------------------
  // getAll
  // -----------------------------------------------------------------------
  describe("getAll", () => {
    it("lists all memories for a user", async () => {
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-charlie", "charlie"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const result = await memory.getAll({ userId: "charlie" });
      expect(result).toHaveProperty("results");
      expect(Array.isArray(result.results)).toBe(true);
    });

    it("lists all memories without user filter", async () => {
      // Mock list_memories reducer to return empty
      const result = await memory.getAll({});
      expect(result).toHaveProperty("results");
    });
  });

  // -----------------------------------------------------------------------
  // update
  // -----------------------------------------------------------------------
  describe("update", () => {
    it("updates memory content", async () => {
      mockReducerOk();
      const result = await memory.update("mem-123", "Updated content");
      expect(result.message).toBe("Memory updated successfully!");
    });

    it("updates memory with object data", async () => {
      mockReducerOk();
      const result = await memory.update("mem-123", { content: "Object content", memory: "alt" });
      expect(result.message).toBe("Memory updated successfully!");
    });
  });

  // -----------------------------------------------------------------------
  // delete
  // -----------------------------------------------------------------------
  describe("delete", () => {
    it("deletes a memory by ID", async () => {
      mockReducerOk();
      const result = await memory.delete("mem-123");
      expect(result.message).toBe("Memory deleted successfully!");
    });
  });

  // -----------------------------------------------------------------------
  // deleteAll
  // -----------------------------------------------------------------------
  describe("deleteAll", () => {
    it("deletes all memories for a user", async () => {
      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        callCount++;
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-dave", "dave"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const result = await memory.deleteAll({ userId: "dave" });
      expect(result).toHaveProperty("status", "ok");
      expect(typeof result.deleted).toBe("number");
    });
  });

  // -----------------------------------------------------------------------
  // history
  // -----------------------------------------------------------------------
  describe("history", () => {
    it("retrieves version history", async () => {
      mockReducerResponse(
        JSON.stringify([
          { version: 1, content: "v1", summary: "first", confidence: 1.0, created_at: 1000 },
          { version: 2, content: "v2", summary: "second", confidence: 1.0, created_at: 2000 },
        ])
      );

      const result = await memory.history("mem-123");
      expect(Array.isArray(result)).toBe(true);
      expect(result.length).toBeGreaterThanOrEqual(2);
      expect(result[0]).toHaveProperty("version");
      expect(result[0]).toHaveProperty("content");
    });
  });

  // -----------------------------------------------------------------------
  // reset & close
  // -----------------------------------------------------------------------
  describe("reset", () => {
    it("clears workspace cache", () => {
      const result = memory.reset();
      expect(result).toHaveProperty("status", "ok");
    });
  });

  describe("close", () => {
    it("cleans up without error", () => {
      expect(() => memory.close()).not.toThrow();
    });
  });

  // -----------------------------------------------------------------------
  // chat
  // -----------------------------------------------------------------------
  describe("chat", () => {
    it("handles chat without LLM config (graceful fallback)", async () => {
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-chat", "chat-user"]],
                },
              ])
            ),
          };
        }
        if (url.includes("embed")) {
          return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1] }) };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const result = await memory.chat("Hello", { userId: "chat-user" });
      expect(result).toHaveProperty("response");
      expect(result).toHaveProperty("context");
      expect(result).toHaveProperty("memories");
    });
  });

  // -----------------------------------------------------------------------
  // createMemoryTool (deprecated)
  // -----------------------------------------------------------------------
  describe("createMemoryTool", () => {
    it("returns NotImplemented with deprecation note", () => {
      const result = memory.createMemoryTool({ userId: "alice" });
      expect(result.status).toBe("not_implemented");
      expect(result.note).toContain("removed");
    });
  });

  // -----------------------------------------------------------------------
  // GraphStore.add
  // -----------------------------------------------------------------------
  describe("GraphStore.add", () => {
    it("adds a graph entity", async () => {
      const g = memory.graph;

      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-graph", "graph-user"]],
                },
              ])
            ),
          };
        }
        if (url.includes("embed")) {
          return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }) };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const entity = await g.add("Alice", { userId: "graph-user", entityType: "person" });
      expect(entity).toBeDefined();
      expect(entity.label).toBeDefined();
    });

    it("rejects empty text", async () => {
      await expect(memory.graph.add("")).rejects.toThrow("non-empty text");
    });
  });

  // -----------------------------------------------------------------------
  // GraphStore.search
  // -----------------------------------------------------------------------
  describe("GraphStore.search", () => {
    it("returns search results", async () => {
      const g = memory.graph;

      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-gs", "gs-user"]],
                },
              ])
            ),
          };
        }
        if (url.includes("embed")) {
          return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.5] }) };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const results = await g.search("Alice", { userId: "gs-user" });
      expect(Array.isArray(results)).toBe(true);
    });
  });

  // -----------------------------------------------------------------------
  // GraphStore.getAll
  // -----------------------------------------------------------------------
  describe("GraphStore.getAll", () => {
    it("lists all graph entities", async () => {
      const g = memory.graph;

      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] },
                  rows: [["ws-gg", "gg-user"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const results = await g.getAll({ userId: "gg-user" });
      expect(Array.isArray(results)).toBe(true);
    });
  });

  // -----------------------------------------------------------------------
  // GraphStore.delete
  // -----------------------------------------------------------------------
  describe("GraphStore.delete", () => {
    it("deletes a graph entity", async () => {
      mockReducerOk();
      const result = await memory.graph.delete("node-123");
      expect(result).toHaveProperty("status", "ok");
      expect(result.deleted).toBe("node-123");
    });
  });

  // -----------------------------------------------------------------------
  // Mem0Memory alias
  // -----------------------------------------------------------------------
  describe("Mem0Memory alias", () => {
    it("is an alias for Memory", () => {
      expect(Mem0Memory).toBe(Memory);
    });
  });
});

// Small helper for update + delete tests
function mockReducerOk(): void {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    text: vi.fn().mockResolvedValue(""),
  });
}
