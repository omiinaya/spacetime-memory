/**
 * E2E pipeline tests: exercise multi-step workflows via mocked HTTP.
 *
 * These tests simulate complete round-trip flows (store → search, create node →
 * query graph, create note → get backlinks) using mocked fetch responses. They
 * verify that the TS SDK client's method chain works correctly end-to-end
 * without requiring a running SpacetimeDB instance.
 *
 * Run with: npx vitest run tests/e2e.test.ts
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { Client, Compounder } from "../client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a smart mock that returns OK for reducers, empty for SQL, and embed data. */
function smartMock() {
  return vi.fn().mockImplementation(async (_url: string, _opts?: RequestInit) => {
    const urlStr = typeof _url === "string" ? _url : String(_url);
    if (urlStr.includes("embed")) {
      return {
        ok: true,
        json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }),
      };
    }
    if (urlStr.includes("call")) {
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    }
    if (urlStr.includes("sql")) {
      return {
        ok: true,
        text: vi.fn().mockResolvedValue(
          JSON.stringify([
            {
              schema: { elements: [{ name: { some: "status" } }] },
              rows: [],
            },
          ]),
        ),
      };
    }
    return { ok: true, text: vi.fn().mockResolvedValue("") };
  });
}

// ---------------------------------------------------------------------------
// Pipeline: Store -> Search
// ---------------------------------------------------------------------------

describe("E2E: Store -> Search pipeline", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("stores a memory then searches for it (keyword)", async () => {
    const wsId = "ws-e2e-store-search";
    const callUrls: string[] = [];

    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      if (url.includes("embed")) {
        return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }) };
      }
      if (url.includes("call/store_memory")) {
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      }
      if (url.includes("call/index_entity")) {
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      }
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([
              {
                schema: {
                  elements: [
                    { name: { some: "id" } }, { name: { some: "entity_id" } },
                    { name: { some: "entity_type" } }, { name: { some: "content" } },
                    { name: { some: "workspace_id" } }, { name: { some: "memory_type" } },
                    { name: { some: "created_at" } },
                  ],
                },
                rows: [["mem-1", "mem-1", "memory", "The capital of France is Paris.", wsId, "fact", 1712345678000000]],
              },
            ]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.store(wsId, "The capital of France is Paris.", { peerId: "test-bot", memoryType: "fact" });
    expect(callUrls.some((u) => u.includes("call/store_memory"))).toBe(true);

    const results = await client.search(wsId, "capital of France", { semantic: false, limit: 5 });
    expect(results.length).toBeGreaterThanOrEqual(1);
    expect(results.some((r) => (r as any).content?.includes("Paris"))).toBe(true);
  });

  it("stores then searches with multiple results", async () => {
    const wsId = "ws-e2e-multi-results";

    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("embed")) {
        return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }) };
      }
      if (url.includes("call/store_memory") || url.includes("call/index_entity")) {
        return { ok: true, text: vi.fn().mockResolvedValue("") };
      }
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([
              {
                schema: {
                  elements: [
                    { name: { some: "id" } }, { name: { some: "entity_id" } },
                    { name: { some: "entity_type" } }, { name: { some: "content" } },
                    { name: { some: "workspace_id" } }, { name: { some: "created_at" } },
                  ],
                },
                rows: [
                  ["r1", "r1", "memory", "Python is dynamically typed.", wsId, 1712345678000000],
                  ["r2", "r2", "memory", "Python supports multiple paradigms.", wsId, 1712345678000001],
                ],
              },
            ]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.store(wsId, "Python is great", { peerId: "bot" });
    const results = await client.search(wsId, "Python", { semantic: false, limit: 5 });
    expect(results.length).toBeGreaterThanOrEqual(1);
    const contents = results.map((r) => (r as any).content || "");
    expect(contents.some((c) => c.includes("dynamically typed"))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Create Node -> Query Graph
// ---------------------------------------------------------------------------

describe("E2E: Create Node -> Query Graph pipeline", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("creates KG nodes and an edge", async () => {
    globalThis.fetch = smartMock();
    await client.createNode("ws-e2e-kg", "Paris", "location");
    await client.createNode("ws-e2e-kg", "France", "location");
    const calls = (globalThis.fetch as any).mock.calls;
    expect(calls.filter((c: any[]) => c[0].includes("call/create_node")).length).toBe(2);
  });

  it("creates a node then queries graph", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      if (url.includes("embed")) return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }) };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "id" } }, { name: { some: "label" } }, { name: { some: "node_type" } }] }, rows: [["n1", "Paris", "location"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.createNode("ws-graph", "Paris", "location");
    const nodes = await client.queryGraph("ws-graph", "Paris");
    expect(nodes.length).toBeGreaterThanOrEqual(1);
    expect(nodes[0]).toHaveProperty("label", "Paris");
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Create Note -> Get Backlinks
// ---------------------------------------------------------------------------

describe("E2E: Create Note -> Get Backlinks pipeline", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("creates a note then retrieves backlinks", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call/create_note")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      if (url.includes("call/get_backlinks")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "source_note_id" } }, { name: { some: "target_note_id" } }, { name: { some: "display_text" } }] }, rows: [["note-euro-geo", "note-paris", "[[Paris]]"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.createNote("ws-bl", "Paris", "Paris is the capital of France.");
    const backlinks = await client.getBacklinks("note-paris");
    expect(backlinks.length).toBeGreaterThanOrEqual(1);
    expect(backlinks[0]).toHaveProperty("target_note_id", "note-paris");
  });

  it("creates a note then retrieves outgoing links", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "target_note_id" } }, { name: { some: "relation" } }, { name: { some: "display_text" } }] }, rows: [["note-fr", "wikilink", "[[France]]"], ["note-eiffel", "wikilink", "[[Eiffel Tower]]"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.createNote("ws-out", "Visiting Paris", "See [[France]] and the [[Eiffel Tower]].");
    const outgoing = await client.getOutgoingLinks("note-visiting-paris");
    expect(outgoing.length).toBe(2);
    expect(outgoing.map((l) => l.target_note_id)).toContain("note-fr");
    expect(outgoing.map((l) => l.target_note_id)).toContain("note-eiffel");
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Multi-step compound workflow
// ---------------------------------------------------------------------------

describe("E2E: Multi-step memory lifecycle", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("stores fact, creates KG entity, creates note -- all succeed", async () => {
    const callLog: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callLog.push(url);
      if (url.includes("embed")) return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }) };
      if (url.includes("call")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      if (url.includes("sql")) return { ok: true, text: vi.fn().mockResolvedValue("[]") };
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.store("ws-multi", "E = mc/b2", { peerId: "physics-bot" });
    await client.createNode("ws-multi", "Mass-Energy Equivalence", "concept");
    await client.createNote("ws-multi", "Einstein's Insight", "Mass-energy equivalence principle.");

    expect(callLog.length).toBeGreaterThanOrEqual(3);
    const allUrls = callLog.join(" ");
    expect(allUrls).toContain("store_memory");
    expect(allUrls).toContain("create_node");
    expect(allUrls).toContain("create_note");
  });

  it("creates a note then retrieves it via listNotes", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "id" } }, { name: { some: "title" } }, { name: { some: "content" } }, { name: { some: "workspace_id" } }] }, rows: [["note-abc", "Test Note", "Test content here.", "ws-notes"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.createNote("ws-notes", "Test Note", "Test content here.");
    const notes = await client.listNotes("ws-notes");
    expect(notes.length).toBeGreaterThanOrEqual(1);
    expect(notes[0]).toHaveProperty("title", "Test Note");
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Workspace lifecycle
// ---------------------------------------------------------------------------

describe("E2E: Workspace lifecycle", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("creates workspace, lists it, updates, and deletes", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }, { name: { some: "description" } }] }, rows: [["ws-1", "My Workspace", "A test workspace"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.createWorkspace("My Workspace", "A test workspace");
    expect(callUrls.some((u) => u.includes("call/create_workspace"))).toBe(true);

    const workspaces = await client.listWorkspaces();
    expect(workspaces.length).toBeGreaterThanOrEqual(1);
    expect(workspaces[0]).toHaveProperty("name", "My Workspace");

    await client.updateWorkspace("ws-1", "Renamed", "Updated desc");
    expect(callUrls.some((u) => u.includes("call/update_workspace"))).toBe(true);

    await client.deleteWorkspace("ws-1");
    expect(callUrls.some((u) => u.includes("call/delete_workspace"))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Memory lifecycle
// ---------------------------------------------------------------------------

describe("E2E: Memory lifecycle", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("stores, retrieves, updates, rates, and deletes a memory", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      if (url.includes("embed")) return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1, 0.2, 0.3] }) };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "id" } }, { name: { some: "content" } }, { name: { some: "workspace_id" } }] }, rows: [["mem-1", "test content", "ws-1"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.store("ws-1", "test content", { peerId: "peer-1" });
    expect(callUrls.some((u) => u.includes("store_memory"))).toBe(true);

    const mems = await client.getMemory("mem-1");
    expect(mems.length).toBeGreaterThanOrEqual(1);
    expect(mems[0]).toHaveProperty("content", "test content");

    await client.updateMemory("mem-1", "updated content", "summary", 0.9);
    await client.rateMemory("mem-1", "helpful", "peer-1");
    expect(callUrls.some((u) => u.includes("rate_memory"))).toBe(true);

    await client.deleteMemory("mem-1");
    expect(callUrls.some((u) => u.includes("deactivate_memory"))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Tags lifecycle
// ---------------------------------------------------------------------------

describe("E2E: Tags lifecycle", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("creates, applies, batches, and deletes tags", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.createTag("ws-1", "important", "#ff0000");
    await client.tagMemory("tag-1", "mem-1");
    await client.listTags("ws-1");
    await client.batchTagMemories("tag-1", ["mem-1", "mem-2"]);
    await client.batchUntagMemories("tag-1", ["mem-1"]);
    await client.deleteTag("tag-1");

    expect(callUrls.filter((u) => u.includes("call/")).length).toBe(6);
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Facts lifecycle
// ---------------------------------------------------------------------------

describe("E2E: Facts lifecycle", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("creates, lists, searches, updates, and deletes a fact", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "fact_id" } }, { name: { some: "content" } }] }, rows: [["f1", "Alice likes pizza"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.addFact("ws-1", "peer-1", "Alice likes pizza");
    const facts = await client.listFacts("ws-1", "peer-1");
    expect(facts).toHaveLength(1);
    expect(facts[0]).toHaveProperty("fact_id", "f1");

    const searchResults = await client.searchFacts("ws-1", "pizza");
    expect(searchResults).toHaveLength(1);

    await client.updateFact("f1", "updated content", 0.9);
    await client.deleteFact("f1");
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Session lifecycle
// ---------------------------------------------------------------------------

describe("E2E: Session lifecycle", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("creates, joins, steps through, and leaves a session", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "step" } }, { name: { some: "step_type" } }] }, rows: [["hello", "action"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.createSession("ws-1", "my session");
    await client.joinSession("sess-1");
    await client.addAgentStep("sess-1", "step text", "action");
    const steps = await client.getSessionSteps("sess-1");
    expect(steps).toHaveLength(1);
    await client.leaveSession("sess-1");

    expect(callUrls.filter((u) => u.includes("call/")).length).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Tour lifecycle
// ---------------------------------------------------------------------------

describe("E2E: Tour lifecycle", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("creates, stops, and deletes a tour", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await client.createTour("ws-1", "My Tour", "A guided walk");
    await client.addTourStop("tour-1", "node-1", 1);
    await client.removeTourStop("stop-1");
    await client.deleteTour("tour-1");

    expect(callUrls.filter((u) => u.includes("call/")).length).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Compounder pipeline
// ---------------------------------------------------------------------------

describe("E2E: Compounder pipeline", () => {
  let client: Client;
  let compounder: Compounder;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
    compounder = new Compounder(client);
  });

  it("crossLinks returns link stats", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "id" } }, { name: { some: "content" } }] }, rows: [["m1", "content A"], ["m2", "content B"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    const result = await compounder.crossLink("ws-1");
    expect(result).toHaveProperty("linksCreated");
    expect(result).toHaveProperty("pairsChecked");
  });

  it("generateOverviewPage returns note with overview", async () => {
    const callUrls: string[] = [];
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callUrls.push(url);
      if (url.includes("embed")) return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1] }) };
      if (url.includes("call")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      // _query needs query_result format (table_name + row_json columns)
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "table_name" } }, { name: { some: "row_json" } }] }, rows: [["note", JSON.stringify({ id: "n1", title: "_overview", content: "## Overview" })]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    const result = await compounder.generateOverviewPage("ws-1");
    expect(result).toHaveProperty("note");
    expect(callUrls.some((u) => u.includes("call/create_note"))).toBe(true);
  });

  it("lintWorkspace checks for orphan nodes", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      // _query needs query_result format
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "table_name" } }, { name: { some: "row_json" } }] }, rows: [] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    const result = await compounder.lintWorkspace("ws-1");
    expect(result).toHaveProperty("orphans");
    expect(result).toHaveProperty("summary");
    expect(result.summary).toHaveProperty("totalIssues");
  });

  it("exportWorkspace returns markdown and files", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("call")) return { ok: true, text: vi.fn().mockResolvedValue("") };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "table_name" } }, { name: { some: "row_json" } }] }, rows: [["note", JSON.stringify({ id: "n1", title: "Note 1", content: "Hello world" })]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    const md = await compounder.exportWorkspace("ws-1");
    expect(md).toHaveProperty("markdown");
    expect(md).toHaveProperty("files");
  });

  it("storeAnswer creates note and extracts entities", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("embed")) return { ok: true, json: vi.fn().mockResolvedValue({ embedding: [0.1] }) };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "id" } }, { name: { some: "title" } }] }, rows: [["n1", "Test Note"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    const result = await compounder.storeAnswer("What is AI?", "Artificial Intelligence is a field of CS.");
    expect(result).toHaveProperty("note");
    expect(result).toHaveProperty("entities");
    expect(result.entities.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Cross-encoder rerank
// ---------------------------------------------------------------------------

describe("E2E: Cross-encoder rerank pipeline", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("reranks candidates with correct payload", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        result: JSON.stringify([
          { id: "a", score: 0.9, memory_content: "first" },
          { id: "b", score: 0.7, memory_content: "second" },
        ]),
      }),
    });

    const results = await client.crossEncoderRerank("test query", [
      { id: "a", memory_content: "first" },
      { id: "b", memory_content: "second" },
    ], { topK: 5 });
    expect(results).toHaveLength(2);
    expect(results[0]).toHaveProperty("score", 0.9);
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Ping and health
// ---------------------------------------------------------------------------

describe("E2E: Ping and health", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("ping returns status ok on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, text: vi.fn().mockResolvedValue("ok") });
    const result = await client.ping();
    expect(result).toHaveProperty("status", "ok");
  });

  it("ping returns status error on failure", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("network error"));
    const result = await client.ping();
    expect(result).toHaveProperty("status", "error");
  });
});

// ---------------------------------------------------------------------------
// Pipeline: Error recovery
// ---------------------------------------------------------------------------

describe("E2E: Error recovery in pipelines", () => {
  let client: Client;

  beforeEach(() => {
    vi.restoreAllMocks();
    client = new Client({ host: "localhost", port: 3001, database: "test-db" });
  });

  it("recovers from a failed reducer call and continues", async () => {
    let callCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      callCount++;
      if (callCount === 1) return { ok: false, status: 500, text: vi.fn().mockResolvedValue("internal error") };
      if (url.includes("sql")) {
        return {
          ok: true,
          text: vi.fn().mockResolvedValue(
            JSON.stringify([{ schema: { elements: [{ name: { some: "id" } }, { name: { some: "name" } }] }, rows: [["ws-1", "My Workspace"]] }]),
          ),
        };
      }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await expect(client.deleteMemory("x")).rejects.toThrow("Reducer error (500)");
    const workspaces = await client.listWorkspaces();
    expect(workspaces).toHaveLength(1);
  });

  it("handles SQL error gracefully, other operations succeed", async () => {
    let sqlFailed = false;
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes("sql") && !sqlFailed) { sqlFailed = true; return { ok: false, status: 400, text: vi.fn().mockResolvedValue("bad request") }; }
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    });

    await expect(client.listWorkspaces()).rejects.toThrow("SQL error (400)");
    await expect(client.createTag("ws-1", "important", "#ff0000")).resolves.not.toThrow();
  });
});
