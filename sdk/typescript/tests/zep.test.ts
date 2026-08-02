/**
 * Unit tests for the spacetime-memory Zep TS adapter.
 *
 * Mocks global fetch — no live SpacetimeDB needed. SQL queries are routed by
 * the table name in the request body; reducer calls are routed by URL suffix.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  ZepClient,
  RoleType,
  BadRequestError,
  NotFoundError,
  ConflictError,
} from "../zep";

// ---------------------------------------------------------------------------
// Mock infrastructure
// ---------------------------------------------------------------------------

/** Canned rows per table, set by each test. */
let tables: Record<string, Record<string, unknown>[]> = {};
/** Recorded reducer calls: [name, args]. */
let reducerCalls: [string, unknown[]][] = [];
let idCounter = 0;
let clock = 1_000_000;

function nextId(prefix: string): string {
  return `${prefix}${++idCounter}`;
}
function tick(): number {
  return (clock += 1_000_000);
}

/** Simulate server-side persistence for the reducers the adapter issues. */
function persist(name: string, args: unknown[]): void {
  switch (name) {
    case "create_workspace":
      (tables.workspace ??= []).push({
        id: String(args[2]), name: String(args[0]), workspace_id: String(args[2]), created_at: tick(),
      });
      break;
    case "create_peer":
      (tables.peer ??= []).push({
        id: nextId("p"), workspace_id: String(args[0]), name: String(args[1]),
        peer_type: String(args[2]), metadata: String(args[3]), created_at: tick(),
      });
      break;
    case "store_memory":
      (tables.memory ??= []).push({
        id: nextId("m"), workspace_id: String(args[0]), content: String(args[4]),
        summary: String(args[5]), source_session_id: String(args[8]),
        is_active: true, created_at: tick(),
      });
      break;
    case "add_fact":
      (tables.fact ??= []).push({
        id: nextId("f"), workspace_id: String(args[0]), content: String(args[4]),
        confidence: Number(args[5]), created_at: tick(),
      });
      break;
    case "create_node":
      (tables.kg_node ??= []).push({
        id: nextId("n"), workspace_id: String(args[0]), label: String(args[1]),
        node_type: String(args[2]), summary: String(args[3]), metadata: String(args[4]),
        created_at: tick(),
      });
      break;
    case "create_edge":
      (tables.kg_edge ??= []).push({
        id: nextId("e"), workspace_id: String(args[0]), source_node_id: String(args[1]),
        target_node_id: String(args[2]), relation: String(args[3]), metadata: String(args[6]),
        created_at: tick(),
      });
      break;
    case "batch_delete_memories": {
      const ids = JSON.parse(String(args[1])) as string[];
      for (const r of tables.memory ?? []) {
        if (ids.includes(String(r.id))) r.is_active = false;
      }
      break;
    }
    case "delete_peer":
      tables.peer = (tables.peer ?? []).filter((r) => r.id !== String(args[0]));
      break;
    case "delete_fact":
      tables.fact = (tables.fact ?? []).filter((r) => r.id !== String(args[0]));
      break;
    case "delete_node":
      tables.kg_node = (tables.kg_node ?? []).filter((r) => r.id !== String(args[0]));
      break;
    case "delete_edge":
      tables.kg_edge = (tables.kg_edge ?? []).filter((r) => r.id !== String(args[0]));
      break;
    case "query_table": {
      // Simulate query_table reducer: read from the named table,
      // apply filters, write results to query_result.
      const tableName = String(args[1]);
      const workspaceId = String(args[2]);
      const filterObj: Record<string, unknown> = JSON.parse(String(args[3]));
      const columns: string[] = JSON.parse(String(args[4]));
      const src = tables[tableName] ?? [];
      let filtered = src;
      if (workspaceId) filtered = filtered.filter((r) => r.workspace_id === workspaceId);
      for (const [k, v] of Object.entries(filterObj)) {
        filtered = filtered.filter((r) => String(r[k]) === String(v));
      }
      const queryId = String(args[0]);
      for (const row of filtered) {
        let projected: Record<string, unknown>;
        if (columns.length > 0) {
          projected = {};
          for (const c of columns) projected[c] = row[c];
        } else {
          projected = row;
        }
        (tables.query_result ??= []).push({
          id: nextId("qr"),
          query_id: queryId,
          table_name: tableName,
          row_json: JSON.stringify(projected),
          created_at: tick(),
        });
      }
      break;
    }
    default:
      break;
  }
}

function sqlBody(rows: Record<string, unknown>[]): string {
  return JSON.stringify([
    {
      schema: {
        elements: Object.keys(rows[0] ?? { _empty: 1 }).map((name) => ({
          name: { some: name },
        })),
      },
      rows: rows.map((r) => Object.values(r)),
    },
  ]);
}

function routeSql(query: string): Record<string, unknown>[] {
  // Very small "WHERE col = 'val'" awareness for the common scoped queries.
  const match = (table: string): Record<string, unknown>[] => {
    const rows = tables[table] ?? [];
    const wsMatch = query.match(/workspace_id = '([^']*)'/);
    const idMatch = query.match(/(?:^| )\bid = '([^']*)'/);
    const qidMatch = query.match(/query_id = '([^']*)'/);
    const nameMatch = query.match(/name = '([^']*)'/);
    const contentMatch = query.match(/content = '([^']*)'/);
    const srcMatch = query.match(/source_node_id = '([^']*)'/);
    const tgtMatch = query.match(/target_node_id = '([^']*)'/);
    const sidMatch = query.match(/source_session_id = '([^']*)'/);
    let out = rows;
    if (wsMatch) out = out.filter((r) => r.workspace_id === wsMatch[1]);
    if (idMatch) out = out.filter((r) => r.id === idMatch[1]);
    if (qidMatch) out = out.filter((r) => r.query_id === qidMatch[1]);
    if (nameMatch) out = out.filter((r) => r.name === nameMatch[1]);
    if (contentMatch) out = out.filter((r) => r.content === contentMatch[1]);
    if (srcMatch) out = out.filter((r) => r.source_node_id === srcMatch[1]);
    if (tgtMatch) out = out.filter((r) => r.target_node_id === tgtMatch[1]);
    if (sidMatch) out = out.filter((r) => r.source_session_id === sidMatch[1]);
    if (/is_active = true/.test(query)) out = out.filter((r) => r.is_active !== false);
    return out;
  };
  if (/FROM workspace\b/.test(query)) return match("workspace");
  if (/FROM peer\b/.test(query)) return match("peer");
  if (/FROM memory\b/.test(query)) return match("memory");
  if (/FROM fact\b/.test(query)) return match("fact");
  if (/FROM kg_node\b/.test(query)) return match("kg_node");
  if (/FROM kg_edge\b/.test(query)) return match("kg_edge");
  if (/FROM session\b/.test(query)) return match("session");
  if (/FROM hybrid_result\b/.test(query)) return match("hybrid_result");
  if (/FROM query_result\b/.test(query)) return match("query_result");
  return [];
}

function installMock(): void {
  globalThis.fetch = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.includes("embeddings") || u.includes("rerank")) {
      return { ok: false, status: 503, text: vi.fn().mockResolvedValue("no embedder") };
    }
    if (u.includes("/sql")) {
      const rows = routeSql(String(init?.body ?? ""));
      return { ok: true, text: vi.fn().mockResolvedValue(sqlBody(rows)) };
    }
    const m = u.match(/\/call\/([a-z_]+)$/);
    if (m) {
      const args = JSON.parse(String(init?.body ?? "[]")) as unknown[];
      reducerCalls.push([m[1], args]);
      persist(m[1], args);
      return { ok: true, text: vi.fn().mockResolvedValue("") };
    }
    return { ok: false, status: 404, text: vi.fn().mockResolvedValue("unmocked: " + u) };
  });
}

function client(): ZepClient {
  return new ZepClient({ host: "127.0.0.1", port: "3001", db: "test-db" });
}

beforeEach(() => {
  tables = {};
  reducerCalls = [];
  idCounter = 0;
  clock = 1_000_000;
  installMock();
});

// ---------------------------------------------------------------------------
// memory proxy
// ---------------------------------------------------------------------------

describe("memory.add", () => {
  it("stores a string message and returns the persisted memory id", async () => {
    tables.workspace = [{ id: "sess1", name: "sess1", workspace_id: "sess1", created_at: 1_000_000 }];
    tables.peer = [{ id: "p1", name: "zep-user", workspace_id: "sess1", created_at: 1_000_000 }];
    tables.memory = [
      { id: "m1", workspace_id: "sess1", source_session_id: "sess1", created_at: 2_000_000 },
    ];
    const z = client();
    const res = await z.memory.add("sess1", "hello world");
    expect(res.memory_id).toBe("m1");
    expect(res.session_id).toBe("sess1");
    expect(res.messages[0].content).toBe("hello world");
    const store = reducerCalls.find(([n]) => n === "store_memory");
    expect(store).toBeDefined();
    expect(store![1][0]).toBe("sess1"); // workspace_id
    expect(store![1][3]).toBe("zep"); // memory_type
  });

  it("creates the workspace lazily when missing", async () => {
    tables.workspace = [];
    tables.peer = [{ id: "p1", name: "zep-user", workspace_id: "s2", created_at: 1 }];
    tables.memory = [];
    const z = client();
    await z.memory.add("s2", "hi");
    expect(reducerCalls.find(([n]) => n === "create_workspace")).toBeDefined();
  });

  it("creates the peer lazily when missing", async () => {
    tables.workspace = [{ id: "s3", name: "s3", workspace_id: "s3", created_at: 1 }];
    tables.peer = [];
    tables.memory = [];
    const z = client();
    await z.memory.add("s3", "hi");
    expect(reducerCalls.find(([n]) => n === "create_peer")).toBeDefined();
  });

  it("rejects empty message lists", async () => {
    tables.workspace = [{ id: "s4", name: "s4", workspace_id: "s4", created_at: 1 }];
    const z = client();
    await expect(z.memory.add("s4", [])).rejects.toThrow(BadRequestError);
  });
});

describe("memory.get", () => {
  it("maps rows to Zep messages in chronological order", async () => {
    tables.memory = [
      { id: "m2", workspace_id: "s", content: "second", is_active: true, created_at: 2_000_000 },
      { id: "m1", workspace_id: "s", content: "first", is_active: true, created_at: 1_000_000 },
    ];
    const z = client();
    const res = await z.memory.get("s");
    expect(res).not.toBeNull();
    expect(res!.messages.map((m) => m.content)).toEqual(["first", "second"]);
  });

  it("honours lastN", async () => {
    tables.memory = [
      { id: "m1", workspace_id: "s", content: "one", is_active: true, created_at: 1_000_000 },
      { id: "m2", workspace_id: "s", content: "two", is_active: true, created_at: 2_000_000 },
      { id: "m3", workspace_id: "s", content: "three", is_active: true, created_at: 3_000_000 },
    ];
    const z = client();
    const res = await z.memory.get("s", 2);
    expect(res!.messages.map((m) => m.content)).toEqual(["two", "three"]);
  });

  it("returns null when the session has no memories", async () => {
    tables.memory = [];
    const z = client();
    expect(await z.memory.get("nope")).toBeNull();
  });
});

describe("memory.delete", () => {
  it("soft-deletes all active memories in the session", async () => {
    tables.memory = [
      { id: "m1", workspace_id: "s", is_active: true, created_at: 1 },
      { id: "m2", workspace_id: "s", is_active: true, created_at: 2 },
    ];
    const z = client();
    await z.memory.delete("s");
    const call = reducerCalls.find(([n]) => n === "batch_delete_memories");
    expect(call).toBeDefined();
    expect(JSON.parse(String(call![1][1]))).toEqual(["m1", "m2"]);
  });
});

describe("memory.search", () => {
  it("maps hybrid results into Zep search results", async () => {
    tables.hybrid_result = [
      { id: "h1", workspace_id: "s", query_hash: "000000005a930079", entity_type: "memory", entity_id: "m1", content: "", score: 0.9, strategy: "keyword", context_json: "{}", created_at: 1 },
    ];
    tables.memory = [{ id: "m1", workspace_id: "s", content: "hit content", is_active: true, created_at: 1 }];
    const z = client();
    const results = await z.memory.search("s", "query", 5);
    expect(results).toHaveLength(1);
    expect(results[0].memory.messages[0].content).toBe("hit content");
    expect(results[0].score).toBe(0.9);
  });
});

// ---------------------------------------------------------------------------
// facts
// ---------------------------------------------------------------------------

describe("facts", () => {
  it("addFact persists via add_fact and returns the uuid", async () => {
    tables.workspace = [{ id: "s", name: "s", workspace_id: "s", created_at: 1 }];
    tables.peer = [{ id: "p1", name: "zep-user", workspace_id: "s", created_at: 1 }];
    tables.fact = [{ id: "f1", workspace_id: "s", content: "sky is blue", created_at: 5_000_000 }];
    const z = client();
    const f = await z.memory.addFact("s", "sky is blue");
    expect(f.fact_uuid).toBe("f1");
    const call = reducerCalls.find(([n]) => n === "add_fact");
    expect(call).toBeDefined();
    expect(call![1][4]).toBe("sky is blue"); // content arg
  });

  it("getFact returns null for unknown uuids", async () => {
    tables.fact = [];
    const z = client();
    expect(await z.memory.getFact("missing")).toBeNull();
  });

  it("getFact maps row fields", async () => {
    tables.fact = [{ id: "f1", content: "fact text", confidence: 0.7, created_at: 9_000_000 }];
    const z = client();
    const f = await z.memory.getFact("f1");
    expect(f!.fact).toBe("fact text");
    expect(f!.score).toBe(0.7);
  });

  it("deleteFact calls delete_fact", async () => {
    const z = client();
    await z.memory.deleteFact("f1");
    expect(reducerCalls.find(([n]) => n === "delete_fact")![1][0]).toBe("f1");
  });

  it("listFacts maps all rows", async () => {
    tables.fact = [
      { id: "f1", workspace_id: "s", content: "a", confidence: 0.5, created_at: 1 },
      { id: "f2", workspace_id: "s", content: "b", confidence: 0.6, created_at: 2 },
    ];
    const z = client();
    const facts = await z.memory.listFacts("s");
    expect(facts.map((f) => f.fact)).toEqual(["a", "b"]);
  });
});

// ---------------------------------------------------------------------------
// user proxy
// ---------------------------------------------------------------------------

describe("user proxy", () => {
  it("add creates a peer and rejects duplicates", async () => {
    tables.workspace = [{ id: "_zep_users", name: "u", workspace_id: "_zep_users", created_at: 1 }];
    tables.peer = [];
    const z = client();
    const rec = await z.user.add({ user_id: "alice" });
    expect(rec.user_id).toBe("alice");
    expect(reducerCalls.find(([n]) => n === "create_peer")).toBeDefined();
    await expect(z.user.add({ user_id: "alice" })).rejects.toThrow(ConflictError);
  });

  it("get returns null for unknown users", async () => {
    tables.peer = [];
    const z = client();
    expect(await z.user.get("ghost")).toBeNull();
  });

  it("delete throws NotFoundError for unknown users", async () => {
    tables.peer = [];
    const z = client();
    await expect(z.user.delete("ghost")).rejects.toThrow(NotFoundError);
  });

  it("delete removes the backing peer", async () => {
    tables.peer = [{ id: "p1", workspace_id: "_zep_users", name: "bob", metadata: "{}", created_at: 1 }];
    const z = client();
    await z.user.delete("bob");
    expect(reducerCalls.find(([n]) => n === "delete_peer")![1][0]).toBe("p1");
  });

  it("listOrdered sorts by creation time", async () => {
    tables.peer = [
      { id: "p2", workspace_id: "_zep_users", name: "newer", metadata: "{}", created_at: 2_000_000 },
      { id: "p1", workspace_id: "_zep_users", name: "older", metadata: "{}", created_at: 1_000_000 },
    ];
    const z = client();
    const users = await z.user.listOrdered();
    expect(users.map((u) => u.user_id)).toEqual(["older", "newer"]);
  });
});

// ---------------------------------------------------------------------------
// graph proxy
// ---------------------------------------------------------------------------

describe("graph", () => {
  it("node.get returns null for unknown uuids", async () => {
    tables.kg_node = [];
    const z = client();
    expect(await z.graph.node.get("nope")).toBeNull();
  });

  it("node.add creates and returns the node", async () => {
    tables.kg_node = [
      { id: "n1", workspace_id: "w", label: "Alice", node_type: "entity", summary: "s", metadata: "{}", created_at: 1 },
    ];
    const z = client();
    const n = await z.graph.node.add("w", { name: "Alice", summary: "s" });
    expect(n.uuid).toBe("n1");
    expect(reducerCalls.find(([nm]) => nm === "create_node")).toBeDefined();
  });

  it("edge.getByNode merges both directions", async () => {
    tables.kg_edge = [
      { id: "e1", workspace_id: "w", source_node_id: "n1", target_node_id: "n2", relation: "knows", metadata: "{}", created_at: 1 },
      { id: "e2", workspace_id: "w", source_node_id: "n3", target_node_id: "n1", relation: "likes", metadata: "{}", created_at: 2 },
      { id: "e3", workspace_id: "w", source_node_id: "n4", target_node_id: "n5", relation: "other", metadata: "{}", created_at: 3 },
    ];
    const z = client();
    const edges = await z.graph.edge.getByNode("n1");
    expect(edges.map((e) => e.uuid).sort()).toEqual(["e1", "e2"]);
  });

  it("addTriplet creates an edge between the given nodes", async () => {
    tables.kg_edge = [];
    const z = client();
    const e = await z.graph.addTriplet({
      workspaceId: "w",
      sourceNodeUuid: "n1",
      targetNodeUuid: "n2",
      relationName: "works_at",
      fact: "Alice works at Acme",
    });
    expect(e.name).toBe("works_at");
    expect(e.source_node_uuid).toBe("n1");
    expect(e.target_node_uuid).toBe("n2");
    expect(e.fact).toBe("Alice works at Acme");
    const call = reducerCalls.find(([nm]) => nm === "create_edge");
    expect(call).toBeDefined();
    expect(call![1][3]).toBe("works_at"); // relation arg
  });

  it("graph.search filters nodes by substring without server-side LIKE", async () => {
    tables.kg_node = [
      { id: "n1", workspace_id: "u", label: "Alice", node_type: "entity", summary: "", metadata: "{}", created_at: 1 },
      { id: "n2", workspace_id: "u", label: "Bob", node_type: "entity", summary: "", metadata: "{}", created_at: 2 },
    ];
    tables.kg_edge = [];
    tables.memory = [];
    const z = client();
    const res = await z.graph.search("ali", { userId: "u", scope: "nodes" });
    expect(res.nodes.map((n) => n.name)).toEqual(["Alice"]);
    expect(res.edges).toEqual([]);
  });

  it("graph.search respects scope=edges", async () => {
    tables.kg_node = [{ id: "n1", workspace_id: "u", label: "knows", node_type: "entity", summary: "", metadata: "{}", created_at: 1 }];
    tables.kg_edge = [
      { id: "e1", workspace_id: "u", source_node_id: "a", target_node_id: "b", relation: "knows", metadata: "{}", created_at: 1 },
    ];
    tables.memory = [];
    const z = client();
    const res = await z.graph.search("knows", { userId: "u", scope: "edges" });
    expect(res.edges.map((e) => e.uuid)).toEqual(["e1"]);
    expect(res.nodes).toEqual([]);
  });

  it("episode.get maps a memory row", async () => {
    tables.memory = [{ id: "m1", content: "episode body", is_active: true, created_at: 4_000_000 }];
    const z = client();
    const ep = await z.graph.episode.get("m1");
    expect(ep!.uuid).toBe("m1");
    expect(ep!.labels).toContain("episode");
  });
});

// ---------------------------------------------------------------------------
// sessions
// ---------------------------------------------------------------------------

describe("sessions", () => {
  it("getSession returns null for unknown sessions", async () => {
    tables.workspace = [];
    const z = client();
    expect(await z.memory.getSession("ghost")).toBeNull();
  });

  it("getSession maps the backing workspace", async () => {
    tables.workspace = [{ id: "s1", name: "sess-one", workspace_id: "s1", created_at: 7_000_000 }];
    const z = client();
    const s = await z.memory.getSession("s1");
    expect(s!.session_id).toBe("s1");
    expect(s!.created_at).toBe(new Date(7_000_000 / 1000).toISOString());
  });

  it("summarizeMemory returns the newest summary", async () => {
    tables.memory = [
      { id: "m1", workspace_id: "s", summary: "old", is_active: true, created_at: 1_000_000 },
      { id: "m2", workspace_id: "s", summary: "new", is_active: true, created_at: 2_000_000 },
    ];
    const z = client();
    expect(await z.summarizeMemory("s")).toBe("new");
  });

  it("summarizeMemory returns null when empty", async () => {
    tables.memory = [];
    const z = client();
    expect(await z.summarizeMemory("s")).toBeNull();
  });
});

describe("graph.community", () => {
  it("list returns only community nodes with member counts", async () => {
    tables.kg_node = [
      { id: "c1", workspace_id: "u", label: "Dogs Club", node_type: "community", summary: "canines", metadata: "{}", created_at: 1 },
      { id: "n1", workspace_id: "u", label: "Entity", node_type: "entity", summary: "", metadata: "{}", created_at: 2 },
      { id: "c2", workspace_id: "other", label: "C2", node_type: "community", summary: "", metadata: "{}", created_at: 3 },
    ];
    tables.kg_edge = [
      { id: "e1", workspace_id: "u", source_node_id: "c1", target_node_id: "m1", relation: "contains", metadata: "{}", created_at: 1 },
      { id: "e2", workspace_id: "u", source_node_id: "c1", target_node_id: "m2", relation: "contains", metadata: "{}", created_at: 2 },
    ];
    const z = client();
    const list = await z.graph.community.list("u");
    expect(list.map((c) => c.uuid)).toEqual(["c1"]);
    expect(list[0].member_count).toBe(2);
    expect(list[0].members.sort()).toEqual(["m1", "m2"]);
  });

  it("build calls detect_communities + seed_communities reducers", async () => {
    tables.kg_node = [];
    const z = client();
    await z.graph.community.build("u");
    expect(reducerCalls.some(([nm]) => nm === "detect_communities")).toBe(true);
    expect(reducerCalls.some(([nm]) => nm === "seed_communities")).toBe(true);
  });

  it("search matches name or summary case-insensitively", async () => {
    tables.kg_node = [
      { id: "c1", workspace_id: "u", label: "Dogs Club", node_type: "community", summary: "All about canines", metadata: "{}", created_at: 1 },
      { id: "c2", workspace_id: "u", label: "Cats", node_type: "community", summary: "Felines only", metadata: "{}", created_at: 2 },
    ];
    tables.kg_edge = [];
    const z = client();
    const hits = await z.graph.community.search("DOGS", "u");
    expect(hits.map((c) => c.uuid)).toEqual(["c1"]);
  });

  it("get returns null for unknown community", async () => {
    tables.kg_node = [];
    const z = client();
    expect(await z.graph.community.get("nope", "u")).toBeNull();
  });
});
