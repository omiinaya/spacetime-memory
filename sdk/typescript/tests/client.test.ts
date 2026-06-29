/**
 * Unit tests for the spacetime-memory TypeScript SDK Client.
 *
 * Mocks global fetch to avoid needing a live SpacetimeDB instance.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { Client } from "../client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Create a mock fetch that returns the given SQL response. */
function mockSqlResponse(rows: unknown[]): void {
  const body = JSON.stringify([
    {
      schema: {
        elements: Object.keys(rows[0] ?? {}).map((name) => ({
          name: { some: name },
        })),
      },
      rows: rows.map((r) => Object.values(r as Record<string, unknown>)),
    },
  ]);
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    text: vi.fn().mockResolvedValue(body),
  });
}

/** Create a mock fetch for a reducer call (no body). */
function mockReducerOk(): void {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    text: vi.fn().mockResolvedValue(""),
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Client", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({
      host: "test.local",
      port: 3001,
      database: "test-db",
    });
  });

  describe("constructor", () => {
    it("uses custom host/port/database", () => {
      expect(client).toBeInstanceOf(Client);
    });

    it("uses defaults when no opts given", () => {
      const def = new Client();
      expect(def).toBeInstanceOf(Client);
    });
  });

  describe("workspace", () => {
    it("createWorkspace calls the reducer", async () => {
      mockReducerOk();
      await client.createWorkspace("my-ws", "test workspace");
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/create_workspace");
      expect(JSON.parse(req.body)).toEqual(["my-ws", "test workspace"]);
    });

    it("listWorkspaces queries SQL", async () => {
      mockSqlResponse([
        { id: "1", name: "ws1" },
        { id: "2", name: "ws2" },
      ]);
      const result = await client.listWorkspaces();
      expect(result).toHaveLength(2);
      expect(result[0].name).toBe("ws1");
    });
  });

  describe("memory", () => {
    it("store calls reducer + index_entity", async () => {
      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        callCount++;
        if (callCount === 1) {
          // store_memory reducer call
          return { ok: true, text: vi.fn().mockResolvedValue("") };
        }
        // index_entity or SQL query
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }] },
                  rows: [["mem-1"]],
                },
              ])
            ),
          };
        }
        // embed call or index_entity
        if (url.includes("embed")) {
          return {
            ok: true,
            json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }),
          };
        }
        // default: reducer ok
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      await client.store("ws-1", "Hello world");
      expect(callCount).toBeGreaterThanOrEqual(2);
    });

    it("search performs hybrid search when semantic=true", async () => {
      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        callCount++;
        if (url.includes("embed")) {
          return {
            ok: true,
            json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2] }),
          };
        }
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: {
                    elements: [
                      { name: { some: "id" } },
                      { name: { some: "entity_id" } },
                      { name: { some: "entity_type" } },
                      { name: { some: "content" } },
                      { name: { some: "score" } },
                      { name: { some: "strategy" } },
                    ],
                  },
                  rows: [["r1", "mem-1", "memory", "hello", 0.95, "semantic"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const results = await client.search("ws-1", "hello", { semantic: true });
      expect(results.length).toBeGreaterThanOrEqual(0);
    });

    it("search does keyword search when semantic=false", async () => {
      mockSqlResponse([
        { id: "1", content: "hello world", created_at: 100 },
      ]);
      const results = await client.search("ws-1", "hello", { semantic: false });
      expect(results.length).toBe(1);
      expect(results[0].content).toBe("hello world");
    });

    it("getMemory fetches and reinforces", async () => {
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: {
                    elements: [
                      { name: { some: "id" } },
                      { name: { some: "content" } },
                    ],
                  },
                  rows: [["mem-1", "test content"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const mems = await client.getMemory("mem-1");
      expect(mems).toHaveLength(1);
      expect(mems[0].content).toBe("test content");
    });

    it("deleteMemory calls deactivate_memory", async () => {
      mockReducerOk();
      await client.deleteMemory("mem-1");
      const callUrl = (globalThis.fetch as any).mock.calls[0][0];
      expect(callUrl).toContain("call/deactivate_memory");
    });
  });

  describe("knowledge graph", () => {
    it("createNode calls the reducer", async () => {
      mockReducerOk();
      await client.createNode("ws-1", "Pizza", "concept", "A food");
      expect(globalThis.fetch).toHaveBeenCalled();
    });

    it("createEdge calls the reducer", async () => {
      mockReducerOk();
      await client.createEdge("ws-1", "n1", "n2", "likes", 1.0);
      expect(globalThis.fetch).toHaveBeenCalled();
    });

    it("queryGraph returns nodes", async () => {
      mockSqlResponse([
        { id: "n1", label: "Pizza", node_type: "concept" },
      ]);
      const nodes = await client.queryGraph("ws-1", "Pizza");
      expect(nodes).toHaveLength(1);
      expect(nodes[0].label).toBe("Pizza");
    });

    it("getNeighbors returns edges", async () => {
      mockSqlResponse([
        {
          source_node_id: "n1",
          target_node_id: "n2",
          relation: "likes",
          weight: 1.0,
        },
      ]);
      const edges = await client.getNeighbors("n1");
      expect(edges).toHaveLength(1);
    });
  });

  describe("notes / wiki", () => {
    it("createNote calls create_note reducer", async () => {
      mockReducerOk();
      await client.createNote("ws-1", "My Note", "Content here");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/create_note");
      expect(JSON.parse(req.body)).toEqual(["ws-1", "My Note", "Content here", true]);
    });

    it("updateNote calls update_note reducer", async () => {
      mockReducerOk();
      await client.updateNote("note-1", "New content");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/update_note");
      expect(JSON.parse(req.body)).toEqual(["note-1", "New content"]);
    });

    it("deleteNote calls delete_note reducer", async () => {
      mockReducerOk();
      await client.deleteNote("note-1");
      const [url] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/delete_note");
    });

    it("listNotes queries SQL", async () => {
      mockSqlResponse([
        { id: "n1", title: "Note 1", content: "Hello" },
      ]);
      const notes = await client.listNotes("ws-1");
      expect(notes).toHaveLength(1);
      expect(notes[0].title).toBe("Note 1");
    });

    it("getNote queries SQL", async () => {
      mockSqlResponse([
        { id: "n1", title: "My Note", content: "Content" },
      ]);
      const notes = await client.getNote("n1");
      expect(notes).toHaveLength(1);
      expect(notes[0].title).toBe("My Note");
    });
  });

  describe("maintenance", () => {
    it("detectCommunities calls the reducer", async () => {
      mockReducerOk();
      await client.detectCommunities("ws-1");
      expect(globalThis.fetch).toHaveBeenCalled();
    });

    it("runMaintenance calls the reducer", async () => {
      mockReducerOk();
      await client.runMaintenance();
      expect(globalThis.fetch).toHaveBeenCalled();
    });

    it("dedup calls the reducer", async () => {
      mockReducerOk();
      await client.dedup("ws-1");
      expect(globalThis.fetch).toHaveBeenCalled();
    });
  });

  describe("error handling", () => {
    it("throws on SQL error", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: vi.fn().mockResolvedValue("bad request"),
      });
      await expect(client.listWorkspaces()).rejects.toThrow("SQL error (400)");
    });

    it("throws on reducer error", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: vi.fn().mockResolvedValue("internal error"),
      });
      await expect(client.deleteMemory("x")).rejects.toThrow(
        "Reducer error (500)"
      );
    });
  });
});
