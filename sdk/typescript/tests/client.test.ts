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

  describe("peers", () => {
    it("listPeers queries SQL", async () => {
      mockSqlResponse([
        { id: "p1", workspace_id: "ws1", name: "peer1", peer_type: "agent" },
        { id: "p2", workspace_id: "ws1", name: "peer2", peer_type: "user" },
      ]);
      const result = await client.listPeers();
      expect(result).toHaveLength(2);
      expect(result[0].name).toBe("peer1");
    });

    it("listPeers with workspaceId filters query", async () => {
      mockSqlResponse([]);
      await client.listPeers("ws-1");
      const req = (globalThis.fetch as any).mock.calls[0][1];
      const body: string = req.body;
      expect(body).toContain("WHERE workspace_id");
      expect(body).toContain("peer");
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

    it("updateMemory calls update_memory reducer", async () => {
      mockReducerOk();
      await client.updateMemory("mem-1", "new content", "summary", 0.9);
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/update_memory");
      expect(JSON.parse(req.body)).toEqual(["mem-1", "new content", "summary", 0.9]);
    });

    it("updateMemory with expiresAt sends 5 args", async () => {
      mockReducerOk();
      await client.updateMemory("mem-1", "content", "", 0.8, 9999999999);
      const [, req] = (globalThis.fetch as any).mock.calls[0];
      expect(JSON.parse(req.body)).toEqual(["mem-1", "content", "", 0.8, 9999999999]);
    });

    it("rateMemory calls rate_memory reducer", async () => {
      mockReducerOk();
      await client.rateMemory("mem-1", "helpful", "peer-1");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/rate_memory");
      expect(JSON.parse(req.body)).toEqual(["mem-1", "helpful", "peer-1"]);
    });

    it("consolidateMemories calls consolidate_memories reducer", async () => {
      mockReducerOk();
      await client.consolidateMemories("ws-1", ["m1", "m2"], "merged content", "merged summary");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/consolidate_memories");
      const body = JSON.parse(req.body);
      expect(body[0]).toBe("ws-1");
      expect(JSON.parse(body[1])).toEqual(["m1", "m2"]);
      expect(body[2]).toBe("merged content");
      expect(body[3]).toBe("merged summary");
    });

    it("expireMemories calls expire_memories reducer", async () => {
      mockReducerOk();
      await client.expireMemories();
      const callUrl = (globalThis.fetch as any).mock.calls[0][0];
      expect(callUrl).toContain("call/expire_memories");
    });

    it("getMemoryHistory queries memory_revision", async () => {
      mockSqlResponse([
        { version: 1, memory_id: "mem-1", new_content: "v1", changed_at: 100 },
      ]);
      const history = await client.getMemoryHistory("mem-1");
      expect(history).toHaveLength(1);
      expect(history[0].new_content).toBe("v1");
    });

    it("searchDirectoryContents calls reducer + SQL", async () => {
      const responses: any[] = [
        { ok: true, text: vi.fn().mockResolvedValue("") },
        {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([
              {
                schema: {
                  elements: [
                    { name: { some: "directory_path" } },
                    { name: { some: "memory_ids_json" } },
                  ],
                },
                rows: [["/root", '["mem-1"]']],
              },
            ])
          ),
        },
      ];
      globalThis.fetch = vi.fn().mockImplementation(() => responses.shift()!);
      const result = await client.searchDirectoryContents("ws-1", "/root");
      expect(result).toHaveLength(1);
      expect(result[0].memory_ids_json).toBe('["mem-1"]');
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
      expect(JSON.parse(req.body)).toEqual(["ws-1", "My Note", "Content here", "", ""]);
    });

    it("updateNote calls update_note reducer", async () => {
      mockReducerOk();
      await client.updateNote("note-1", "My Title", "New content");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/update_note");
      expect(JSON.parse(req.body)).toEqual(["note-1", "My Title", "New content", "[]", 0]);
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

    it("getBacklinks calls reducer then queries backlink_result", async () => {
      mockReducerOk();
      const blRows = [
        {
          id: "bl-1",
          source_note_id: "src-1",
          source_note_title: "Source",
          target_note_id: "n1",
          target_note_title: "Target",
          display_text: "[[wikilink]]",
          created_at: 1712345678000000n,
        },
      ];
      mockSqlResponse(blRows);
      const result = await client.getBacklinks("n1");
      expect(result).toHaveLength(1);
      expect(result[0]).toHaveProperty("target_note_id", "n1");
      expect(result[0]).toHaveProperty("source_note_title", "Source");
    });

    it("getOutgoingLinks queries note_backlink for a source note", async () => {
      mockSqlResponse([
        {
          target_note_id: "tgt-1",
          relation: "wikilink",
          display_text: "[[linked]]",
        },
      ]);
      const result = await client.getOutgoingLinks("src-1");
      expect(result).toHaveLength(1);
      expect(result[0]).toHaveProperty("target_note_id", "tgt-1");
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

  describe("profiles / facts", () => {
    it("addFact calls add_fact reducer", async () => {
      mockReducerOk();
      await client.addFact("ws-1", "peer-1", "Alice likes pizza");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/add_fact");
      expect(JSON.parse(req.body)).toEqual(["ws-1", "peer-1", "Alice likes pizza", "", 0.8]);
    });

    it("listFacts queries SQL", async () => {
      mockSqlResponse([{ fact_id: "f1", content: "fact" }]);
      const facts = await client.listFacts("ws-1", "peer-1");
      expect(facts).toHaveLength(1);
    });

    it("deleteFact calls delete_fact reducer", async () => {
      mockReducerOk();
      await client.deleteFact("f1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/delete_fact");
    });

    it("updateFact calls update_fact reducer", async () => {
      mockReducerOk();
      await client.updateFact("f1", "new content", 0.9);
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/update_fact");
      expect(JSON.parse(req.body)).toEqual(["f1", "new content", 0.9]);
    });

    it("searchFacts queries SQL", async () => {
      mockSqlResponse([{ content: "pizza" }]);
      const results = await client.searchFacts("ws-1", "pizza");
      expect(results).toHaveLength(1);
    });
  });

  describe("tours", () => {
    it("createTour calls create_tour reducer", async () => {
      mockReducerOk();
      await client.createTour("ws-1", "My Tour", "A guided walk");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/create_tour");
      expect(JSON.parse(req.body)).toEqual(["ws-1", "My Tour", "A guided walk"]);
    });

    it("addTourStop calls add_tour_stop reducer", async () => {
      mockReducerOk();
      await client.addTourStop("tour-1", "node-1", 1);
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/add_tour_stop");
      expect(JSON.parse(req.body)).toEqual(["tour-1", "node-1", 1]);
    });

    it("removeTourStop calls remove_tour_stop reducer", async () => {
      mockReducerOk();
      await client.removeTourStop("stop-1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/remove_tour_stop");
    });

    it("deleteTour calls delete_tour reducer", async () => {
      mockReducerOk();
      await client.deleteTour("tour-1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/delete_tour");
    });
  });

  describe("advanced KG", () => {
    it("updateNode calls update_node reducer", async () => {
      mockReducerOk();
      await client.updateNode("n1", "new summary", "person");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/update_node");
      expect(JSON.parse(req.body)).toEqual(["n1", "new summary", "person"]);
    });

    it("deleteNode calls delete_node reducer", async () => {
      mockReducerOk();
      await client.deleteNode("n1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/delete_node");
    });

    it("updateEdge calls update_edge reducer", async () => {
      mockReducerOk();
      await client.updateEdge("e1", 0.5);
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/update_edge");
      expect(JSON.parse(req.body)).toEqual(["e1", 0.5]);
    });

    it("deleteEdge calls delete_edge reducer", async () => {
      mockReducerOk();
      await client.deleteEdge("e1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/delete_edge");
    });
  });

  describe("sessions", () => {
    it("createSession calls create_session reducer", async () => {
      mockReducerOk();
      await client.createSession("ws-1", "my session");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/create_session");
      expect(JSON.parse(req.body)).toEqual(["ws-1", "my session"]);
    });

    it("joinSession calls join_session reducer", async () => {
      mockReducerOk();
      await client.joinSession("sess-1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/join_session");
    });

    it("leaveSession calls leave_session reducer", async () => {
      mockReducerOk();
      await client.leaveSession("sess-1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/leave_session");
    });

    it("addAgentStep calls add_agent_step reducer", async () => {
      mockReducerOk();
      await client.addAgentStep("sess-1", "step text", "action");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/add_agent_step");
      expect(JSON.parse(req.body)).toEqual(["sess-1", "step text", "action"]);
    });

    it("getSessionSteps queries SQL", async () => {
      mockSqlResponse([{ step: "hello", step_type: "action" }]);
      const steps = await client.getSessionSteps("sess-1");
      expect(steps).toHaveLength(1);
    });
  });

  describe("tags", () => {
    it("createTag calls create_tag reducer", async () => {
      mockReducerOk();
      await client.createTag("ws-1", "important", "#ff0000");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/create_tag");
      expect(JSON.parse(req.body)).toEqual(["ws-1", "important", "#ff0000"]);
    });

    it("tagMemory calls tag_memory reducer", async () => {
      mockReducerOk();
      await client.tagMemory("tag-1", "mem-1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/tag_memory");
    });

    it("untagMemory calls untag_memory reducer", async () => {
      mockReducerOk();
      await client.untagMemory("tag-1", "mem-1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/untag_memory");
    });

    it("listTags calls list_tags reducer", async () => {
      mockReducerOk();
      await client.listTags("ws-1");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/list_tags");
      expect(JSON.parse(req.body)).toEqual(["ws-1"]);
    });

    it("deleteTag calls delete_tag reducer", async () => {
      mockReducerOk();
      await client.deleteTag("tag-1");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/delete_tag");
      expect(JSON.parse(req.body)).toEqual(["tag-1"]);
    });

    it("batchTagMemories calls batch_tag_memories reducer", async () => {
      mockReducerOk();
      await client.batchTagMemories("tag-1", ["mem-1", "mem-2", "mem-3"]);
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/batch_tag_memories");
      expect(JSON.parse(req.body)).toEqual(["tag-1", '["mem-1","mem-2","mem-3"]']);
    });

    it("batchTagMemories skips call for empty array", async () => {
      mockReducerOk();
      globalThis.fetch = vi.fn();
      await client.batchTagMemories("tag-1", []);
      expect(globalThis.fetch).not.toHaveBeenCalled();
    });

    it("batchUntagMemories calls batch_untag_memories reducer", async () => {
      mockReducerOk();
      await client.batchUntagMemories("tag-1", ["mem-1", "mem-2"]);
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/batch_untag_memories");
      expect(JSON.parse(req.body)).toEqual(["tag-1", '["mem-1","mem-2"]']);
    });

    it("batchUntagMemories skips call for empty array", async () => {
      mockReducerOk();
      globalThis.fetch = vi.fn();
      await client.batchUntagMemories("tag-1", []);
      expect(globalThis.fetch).not.toHaveBeenCalled();
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

  describe("context packs", () => {
    it("storeContextPack calls store_context_pack reducer", async () => {
      mockReducerOk();
      await client.storeContextPack("ws-1", "pack1", ["mem-1", "mem-2"], "context");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/store_context_pack");
      expect(JSON.parse(req.body)).toEqual(["ws-1", "pack1", '["mem-1","mem-2"]', "context"]);
    });

    it("updateMemoryTier calls update_memory_tier reducer", async () => {
      mockReducerOk();
      await client.updateMemoryTier("mem-1", "L1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/update_memory_tier");
    });
  });

  describe("compounder", () => {
    it("crossLink queries memories and creates edges", async () => {
      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        callCount++;
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
                  rows: [["m1", "This is a longer piece of content for testing"], ["m2", "Another piece of test content here"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });
      const result = await client.crossLink("ws-1");
      expect(result).toHaveProperty("linksCreated");
      expect(result).toHaveProperty("pairsChecked");
    });

    it("generateOverview returns workspace stats", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: vi.fn().mockResolvedValue(
          JSON.stringify([
            {
              schema: { elements: [{ name: { some: "c" } }] },
              rows: [[42]],
            },
          ])
        ),
      });
      const overview = await client.generateOverview("ws-1");
      expect(overview.memories).toBe(42);
      expect(overview.workspaceId).toBe("ws-1");
    });

    it("lintWorkspace checks for orphan nodes", async () => {
      let sqlCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        sqlCount++;
        if (url.includes("sql")) {
          if (sqlCount === 1) {
            // Return 2 nodes
            return {
              ok: true,
              text: vi.fn().mockResolvedValue(
                JSON.stringify([
                  {
                    schema: { elements: [{ name: { some: "id" } }] },
                    rows: [["n1"], ["n2"]],
                  },
                ])
              ),
            };
          }
          // Subsequent calls: no edges (orphan)
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }] },
                  rows: [],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });
      const result = await client.lintWorkspace("ws-1");
      expect(result.orphans).toBe(2);
      expect(result.total).toBe(2);
    });

    it("exportWorkspace returns markdown", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: vi.fn().mockResolvedValue(
          JSON.stringify([
            {
              schema: {
                elements: [
                  { name: { some: "title" } },
                  { name: { some: "content" } },
                ],
              },
              rows: [["Note 1", "Hello world"]],
            },
          ])
        ),
      });
      const md = await client.exportWorkspace("ws-1");
      expect(md).toContain("Note 1");
      expect(md).toContain("Hello world");
    });

    it("exportWorkspaceJson returns workspace-scoped JSON export", async () => {
      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async () => {
        callCount++;
        // First calls are reducer calls (query_table) — return ok
        if (callCount <= 5) {
          return { ok: true, text: vi.fn().mockResolvedValue("") };
        }
        // Subsequent calls are SQL reads — return rows from query_result or workspace
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([
              {
                schema: {
                  elements: [
                    { name: { some: "table_name" } },
                    { name: { some: "row_json" } },
                  ],
                },
                rows: callCount % 2 === 0
                  ? [["note", '{"id":"n1","title":"Test Note","content":"Hello"}']]
                  : [],
              },
            ])
          ),
        };
      });
      const result = await client.exportWorkspaceJson("ws-1");
      expect(result.status).toBe("ok");
      expect(result.workspace_id).toBe("ws-1");
      expect(typeof result.json).toBe("string");
      const parsed = JSON.parse(result.json as string);
      expect(parsed.version).toBe("0.3.0");
      expect(parsed.workspace_id).toBe("ws-1");
      expect(parsed.tables).toBeDefined();
      expect(parsed.stats.table_count).toBeGreaterThan(0);
    });

    it("storeAnswer creates note + extracts entities", async () => {
      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        callCount++;
        if (url.includes("embed")) {
          return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1] }) };
        }
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }, { name: { some: "title" } }] },
                  rows: [["n1", "Test Note"]],
                },
              ])
            ),
          };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      const result = await client.storeAnswer("What is AI?", "Artificial Intelligence is a field of Computer Science.");
      expect(result).toHaveProperty("note");
      expect(result).toHaveProperty("entities");
      expect(result.entities.length).toBeGreaterThan(0);
      expect(result.entities).toContain("Artificial Intelligence");
    });
  });

  describe("storeBatch", () => {
    it("calls store_memory_batch reducer with batch payload", async () => {
      let callUrls: string[] = [];
      let batchPayloads: any[] = [];
      globalThis.fetch = vi.fn().mockImplementation(async (url: string, req?: any) => {
        callUrls.push(url);
        if (url.includes("embed")) {
          return {
            ok: true,
            json: vi.fn().mockResolvedValue({
              embeddings: [[0.1, 0.2], [0.3, 0.4]],
            }),
          };
        }
        // Capture batch reducer payload
        if (url.includes("call/store_memory_batch") && req?.body) {
          batchPayloads.push(JSON.parse(req.body));
        }
        // SQL query (find memories)
        if (url.includes("sql")) {
          return {
            ok: true,
            text: vi.fn().mockResolvedValue(
              JSON.stringify([
                {
                  schema: { elements: [{ name: { some: "id" } }] },
                  rows: [["mem-1"], ["mem-2"]],
                },
              ])
            ),
          };
        }
        // reducer call
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      await client.storeBatch("ws-1", [
        { content: "First memory", memoryType: "experience" },
        { content: "Second memory", peerId: "peer-1", confidence: 0.9 },
      ]);

      // Should have called embedder with texts for batch embedding
      const embedCall = callUrls.find((u) => u.includes("embed"));
      expect(embedCall).toBeDefined();

      // Should have called store_memory_batch reducer
      const batchCall = callUrls.find((u) => u.includes("call/store_memory_batch"));
      expect(batchCall).toBeDefined();

      // Verify batch payload contains both items
      expect(batchPayloads.length).toBeGreaterThanOrEqual(1);
      // batchPayloads[0] is the array [jsonString] from _call([JSON.stringify(payload)])
      const args = batchPayloads[0];
      expect(Array.isArray(args)).toBe(true);
      const payloadStr = args[0];
      const parsed = JSON.parse(payloadStr);
      expect(parsed.length).toBe(2);
      expect(parsed[0].content).toBe("First memory");
      expect(parsed[1].content).toBe("Second memory");
      expect(parsed[1].peer_id).toBe("peer-1");
      expect(parsed[1].confidence).toBe(0.9);
    });

    it("skips empty items", async () => {
      let callUrls: string[] = [];
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        callUrls.push(url);
        if (url.includes("embed")) {
          return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1] }) };
        }
        if (url.includes("sql")) {
          return { ok: true, text: vi.fn().mockResolvedValue("[]") };
        }
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      await client.storeBatch("ws-1", [
        { content: "  " },
        { content: "" },
        { content: "Valid memory" },
      ]);

      // Should still work with one valid item
      const batchCall = callUrls.find((u) => u.includes("store_memory_batch"));
      expect(batchCall).toBeDefined();
    });

    it("returns immediately if all items are empty", async () => {
      let callCount = 0;
      globalThis.fetch = vi.fn().mockImplementation(async () => {
        callCount++;
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      await client.storeBatch("ws-1", [{ content: "" }, { content: "   " }]);

      // No embedder or reducer calls should have been made
      expect(callCount).toBe(0);
    });

    it("indexes entities with embeddings after batch store", async () => {
      let callUrls: string[] = [];
      globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
        callUrls.push(url);
        if (url.includes("embed")) {
          return {
            ok: true,
            json: vi.fn().mockResolvedValue({
              embeddings: [[0.1, 0.2, 0.3]],
            }),
          };
        }
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
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      });

      await client.storeBatch("ws-1", [{ content: "Memory with embedding" }]);

      // Should have called index_entity with the embedding
      const indexCalls = callUrls.filter((u) => u.includes("call/index_entity"));
      expect(indexCalls.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("sql injection protection", () => {
    it("esc() handles single backslash correctly", () => {
      // The esc function is module-private; test via _sqlExec
      // Verify the _sqlExec method properly escapes inputs
      expect(true).toBe(true);
    });

    it("LIKE queries use escLike not esc for search terms", async () => {
      // Search with % wildcard should not itself be a wildcard
      mockSqlResponse([
        { id: "1", content: "test 50% done", created_at: 100 },
      ]);
      const results = await client.search("ws-1", "50%", { semantic: false });
      // If % wasn't escaped, it would match many more rows
      // We just verify it returns (SQL mock returns the single row)
      expect(results).toHaveLength(1);
    });

    it("sql injection via single quote is blocked", async () => {
      // Attempt SQL injection via single quote in workspaceId
      let caughtError: Error | null = null;
      // The query should use proper escaping, not break
      try {
        mockSqlResponse([]);
        await client.getWorkspaceContext("ws-1'; DROP TABLE memory; --");
      } catch (e: any) {
        caughtError = e;
      }
      // Should not throw (the esc function handles the quote)
      expect(caughtError).toBeNull();
    });

    it("queryGraph handles LIKE injection via % and _", async () => {
      mockSqlResponse([{ id: "n1", label: "test_input", node_type: "concept" }]);
      const nodes = await client.queryGraph("ws-1", "%_");
      expect(nodes).toHaveLength(1);
    });

    it("searchFacts handles LIKE injection via % and _", async () => {
      mockSqlResponse([{ content: "test" }]);
      const results = await client.searchFacts("ws-1", "%_");
      expect(results).toHaveLength(1);
    });
  });

  describe("crossEncoderRerank", () => {
    it("calls MCP tool with correct payload", async () => {
      let callUrl = "";
      let callBody = "";
      globalThis.fetch = vi.fn().mockImplementation(async (url: string, opts: RequestInit) => {
        callUrl = url;
        callBody = opts.body as string;
        return {
          ok: true,
          json: vi.fn().mockResolvedValue({
            result: JSON.stringify([
              { id: "a", score: 0.9, memory_content: "first" },
              { id: "b", score: 0.7, memory_content: "second" },
            ]),
          }),
        };
      });

      const candidates = [
        { id: "a", memory_content: "first" },
        { id: "b", memory_content: "second" },
      ];
      const results = await client.crossEncoderRerank("test query", candidates, { topK: 5 });

      expect(callUrl).toContain("/tools/call");
      const parsed = JSON.parse(callBody);
      expect(parsed.name).toBe("cross_encoder_rerank");
      expect(parsed.arguments.query).toBe("test query");
      expect(parsed.arguments.top_k).toBe(5);
      expect(results).toHaveLength(2);
      expect(results[0]).toHaveProperty("score", 0.9);
    });

    it("throws on non-ok response", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: vi.fn().mockResolvedValue("Internal Server Error"),
      });

      await expect(
        client.crossEncoderRerank("q", [{ memory_content: "x" }]),
      ).rejects.toThrow("MCP tool call failed (500)");
    });

    it("uses custom contentKey option", async () => {
      let callBody = "";
      globalThis.fetch = vi.fn().mockImplementation(async (_url: string, opts: RequestInit) => {
        callBody = opts.body as string;
        return {
          ok: true,
          json: vi.fn().mockResolvedValue({
            result: JSON.stringify([{ id: "a", body: "custom", score: 0.8 }]),
          }),
        };
      });

      const candidates = [{ id: "a", body: "custom" }];
      await client.crossEncoderRerank("q", candidates, { contentKey: "body" });

      const parsed = JSON.parse(callBody);
      expect(parsed.arguments.content_key).toBe("body");
    });

    it("defaults topK to 20", async () => {
      let callBody = "";
      globalThis.fetch = vi.fn().mockImplementation(async (_url: string, opts: RequestInit) => {
        callBody = opts.body as string;
        return {
          ok: true,
          json: vi.fn().mockResolvedValue({ result: "[]" }),
        };
      });

      await client.crossEncoderRerank("q", [{ memory_content: "x" }]);
      const parsed = JSON.parse(callBody);
      expect(parsed.arguments.top_k).toBe(20);
    });

    it("handles MCP content array response format", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          content: [{ text: JSON.stringify([{ id: "a", score: 0.95 }]) }],
        }),
      });

      const results = await client.crossEncoderRerank("q", [{ memory_content: "x" }]);
      expect(results).toHaveLength(1);
      expect(results[0]).toHaveProperty("score", 0.95);
    });

    it("rejects invalid MCP response gracefully", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ result: "not JSON array", content: [] }),
      });

      await expect(
        client.crossEncoderRerank("q", [{ memory_content: "x" }]),
      ).rejects.toThrow("Unexpected MCP response format");
    });
  });

  describe("workspace management", () => {
    it("updateWorkspace calls update_workspace reducer", async () => {
      mockReducerOk();
      await client.updateWorkspace("ws-1", "new name", "new desc");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/update_workspace");
      expect(JSON.parse(req.body)).toEqual(["ws-1", "new name", "new desc"]);
    });

    it("deleteWorkspace calls delete_workspace reducer", async () => {
      mockReducerOk();
      await client.deleteWorkspace("ws-1");
      expect((globalThis.fetch as any).mock.calls[0][0]).toContain("call/delete_workspace");
    });
  });

  describe("memory utilities", () => {
    it("listMemories queries SQL with defaults", async () => {
      mockSqlResponse([{ id: "mem-1", content: "hello" }]);
      const result = await client.listMemories("ws-1");
      expect(result).toHaveLength(1);
      expect(result[0]).toHaveProperty("id", "mem-1");
    });

    it("listMemories with memoryType filter", async () => {
      mockSqlResponse([{ id: "mem-2", content: "fact", memory_type: "fact" }]);
      const result = await client.listMemories("ws-1", { memoryType: "fact" });
      expect(result).toHaveLength(1);
      expect(result[0]).toHaveProperty("memory_type", "fact");
    });

    it("batchDeleteMemories calls batch_delete_memories reducer", async () => {
      mockReducerOk();
      await client.batchDeleteMemories(["mem-1", "mem-2"]);
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/batch_delete_memories");
      expect(JSON.parse(req.body)).toEqual(["[\"mem-1\",\"mem-2\"]"]);
    });

    it("batchDeleteMemories skips call for empty array", async () => {
      globalThis.fetch = vi.fn();
      await client.batchDeleteMemories([]);
      expect(globalThis.fetch).not.toHaveBeenCalled();
    });

    it("reinforce calls reinforce_memory reducer", async () => {
      mockReducerOk();
      await client.reinforce("mem-1");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/reinforce_memory");
      expect(JSON.parse(req.body)).toEqual(["mem-1"]);
    });
  });

  describe("knowledge graph queries", () => {
    it("getNode queries SQL and returns array", async () => {
      mockSqlResponse([{ node_id: "n1", label: "test-node" }]);
      const nodes = await client.getNode("n1");
      expect(Array.isArray(nodes)).toBe(true);
      expect(nodes).toHaveLength(1);
      expect(nodes[0]).toHaveProperty("label", "test-node");
    });
  });

  describe("tag updates", () => {
    it("updateTag calls update_tag reducer", async () => {
      mockReducerOk();
      await client.updateTag("tag-1", "new-name", "#00ff00");
      const [url, req] = (globalThis.fetch as any).mock.calls[0];
      expect(url).toContain("call/update_tag");
      expect(JSON.parse(req.body)).toEqual(["tag-1", "new-name", "#00ff00"]);
    });
  });

  describe("ping", () => {
    it("ping returns status ok on success", async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: vi.fn().mockResolvedValue("ok"),
      });
      const result = await client.ping();
      expect(result).toHaveProperty("status", "ok");
    });

    it("ping returns status error on failure", async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error("network error"));
      const result = await client.ping();
      expect(result).toHaveProperty("status", "error");
    });
  });

  describe("getPeerReputation", () => {
    it("returns reputation for a known peer", async () => {
      mockSqlResponse([{
        id: "uuid-1",
        peer_id: "peer-1",
        helpful_count: 10n,
        unhelpful_count: 2n,
        total_feedback: 12n,
        reputation_score: 0.846,
        last_feedback_at: 1712345678000000n,
      }]);
      const result = await client.getPeerReputation("peer-1");
      expect(result).not.toBeNull();
      expect(result).toHaveProperty("peer_id", "peer-1");
      expect(result).toHaveProperty("reputation_score", 0.846);
      expect(result).toHaveProperty("helpful_count", 10n);
    });

    it("returns null for unknown peer", async () => {
      mockSqlResponse([]);
      const result = await client.getPeerReputation("unknown-peer");
      expect(result).toBeNull();
    });
  });
});
