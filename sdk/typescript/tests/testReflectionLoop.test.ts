/**
 * Tests for reflectionLoop.ts TypeScript SDK module.
 *
 * These tests use vitest with mocked ClientLike instances to verify
 * that the wrapper functions call the correct reducers and query
 * the correct result tables.
 */
import { describe, it, expect, vi } from "vitest";
import {
  createReflectionSession,
  startReflectionCycle,
  storeReflectionInsight,
  completeReflectionSession,
  getReflectionSessions,
  getReflectionInsights,
  deleteReflectionSession,
} from "../src/reflectionLoop";
import type { ClientLike } from "../src/types";

// -----------------------------------------------------------------------
// Mocks
// -----------------------------------------------------------------------

function mockClient(): ClientLike {
  return {
    _call: vi.fn().mockResolvedValue(undefined),
    _callWithResult: vi.fn().mockResolvedValue('"ok"'),
    _sql: vi.fn().mockResolvedValue([]),
    _sqlExec: vi.fn().mockResolvedValue([]),
    _embed: vi.fn().mockResolvedValue([]),
    _query: vi.fn().mockResolvedValue([]),
    _authHeaders: vi.fn().mockReturnValue({}),
    embedderUrl: "http://localhost:9090/v1",
    mcpUrl: "http://localhost:8099",
    tantivyUrl: "http://localhost:9091",
    baseUrl: "http://localhost:3001",
    host: "localhost",
    port: "3001",
    database: "test",
    token: "",
    _metricsCollector: null,
  };
}

// -----------------------------------------------------------------------
// Sample data
// -----------------------------------------------------------------------

const SAMPLE_SESSION = {
  id: "rs-001",
  workspace_id: "ws-test",
  peer_id: "peer-alice",
  config_json: '{"depth":3,"types":["pattern","contradiction"]}',
  cycles_completed: 0,
  status: "active",
  insight_count: 0,
  started_at: 1000000,
  completed_at: null,
  created_at: 1000000,
};

const SAMPLE_INSIGHT = {
  id: "ri-001",
  workspace_id: "ws-test",
  session_id: "rs-001",
  content: "Agent Alice consistently prefers collaborative approaches",
  confidence: 0.85,
  insight_type: "pattern",
  source_memory_ids: '["mem-1","mem-3"]',
  source_note_ids: '[]',
  cycle: 1,
  created_at: 1100000,
};

// -----------------------------------------------------------------------
// createReflectionSession
// -----------------------------------------------------------------------

describe("createReflectionSession", () => {
  it("calls create_reflection_session reducer with correct args", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_SESSION]);

    const result = await createReflectionSession(
      client,
      "ws-test",
      "peer-alice",
      { depth: 3, types: ["pattern", "contradiction"] },
    );

    expect(client._call).toHaveBeenCalledWith("create_reflection_session", [
      "ws-test",
      "peer-alice",
      '{"depth":3,"types":["pattern","contradiction"]}',
    ]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("reflection_session_result"),
      expect.objectContaining({ ws: "ws-test" }),
    );
    expect(result).toBeDefined();
    expect(result.id).toBe("rs-001");
  });

  it("works with minimal (empty config) arguments", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([{ ...SAMPLE_SESSION, config_json: "{}" }]);

    const result = await createReflectionSession(client, "ws-empty", "peer-bob");

    expect(client._call).toHaveBeenCalledWith(
      "create_reflection_session",
      ["ws-empty", "peer-bob", "{}"],
    );
    expect(result.config_json).toBe("{}");
  });
});

// -----------------------------------------------------------------------
// startReflectionCycle
// -----------------------------------------------------------------------

describe("startReflectionCycle", () => {
  it("calls start_reflection_cycle reducer and returns updated session", async () => {
    const client = mockClient();
    const updated = {
      ...SAMPLE_SESSION,
      cycles_completed: 1,
      updated_at: 1200000,
    };
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([updated]);

    const result = await startReflectionCycle(client, "ws-test", "rs-001");

    expect(client._call).toHaveBeenCalledWith("start_reflection_cycle", [
      "ws-test",
      "rs-001",
    ]);
    expect(result.cycles_completed).toBe(1);
  });
});

// -----------------------------------------------------------------------
// storeReflectionInsight
// -----------------------------------------------------------------------

describe("storeReflectionInsight", () => {
  it("stores an insight with all fields and returns it", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_INSIGHT]);

    const result = await storeReflectionInsight(
      client,
      "ws-test",
      "rs-001",
      "Agent Alice consistently prefers collaborative approaches",
      0.85,
      "pattern",
      ["mem-1", "mem-3"],
      [],
    );

    expect(client._call).toHaveBeenCalledWith("store_reflection_insight", [
      "ws-test",
      "rs-001",
      "Agent Alice consistently prefers collaborative approaches",
      0.85,
      "pattern",
      '["mem-1","mem-3"]',
      "[]",
    ]);
    expect(result.insight_type).toBe("pattern");
    expect(result.confidence).toBe(0.85);
  });

  it("uses default values for optional parameters", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_INSIGHT]);

    await storeReflectionInsight(client, "ws-test", "rs-001", "Test insight");

    expect(client._call).toHaveBeenCalledWith("store_reflection_insight", [
      "ws-test",
      "rs-001",
      "Test insight",
      0.5,
      "observation",
      "[]",
      "[]",
    ]);
  });
});

// -----------------------------------------------------------------------
// completeReflectionSession
// -----------------------------------------------------------------------

describe("completeReflectionSession", () => {
  it("completes a session with 'completed' status", async () => {
    const client = mockClient();
    const completed = {
      ...SAMPLE_SESSION,
      status: "completed",
      cycles_completed: 3,
      completed_at: 2000000,
    };
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([completed]);

    const result = await completeReflectionSession(
      client,
      "ws-test",
      "rs-001",
      "completed",
    );

    expect(client._call).toHaveBeenCalledWith("complete_reflection_session", [
      "ws-test",
      "rs-001",
      "completed",
    ]);
    expect(result.status).toBe("completed");
    expect(result.completed_at).toBe(2000000);
  });

  it("defaults status to 'completed'", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([{ ...SAMPLE_SESSION, status: "completed" }]);

    await completeReflectionSession(client, "ws-test", "rs-001");

    expect(client._call).toHaveBeenCalledWith(
      "complete_reflection_session",
      ["ws-test", "rs-001", "completed"],
    );
  });
});

// -----------------------------------------------------------------------
// getReflectionSessions
// -----------------------------------------------------------------------

describe("getReflectionSessions", () => {
  it("calls the get reducer and returns all sessions for workspace", async () => {
    const client = mockClient();
    const sessions = [
      { ...SAMPLE_SESSION, id: "rs-001" },
      { ...SAMPLE_SESSION, id: "rs-002", peer_id: "peer-bob" },
    ];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(sessions);

    const result = await getReflectionSessions(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("get_reflection_sessions", [
      "ws-test",
    ]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("reflection_session_result"),
      expect.objectContaining({ ws: "ws-test" }),
    );
    expect(result).toHaveLength(2);
  });

  it("returns empty array when no sessions exist", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await getReflectionSessions(client, "ws-empty");

    expect(result).toEqual([]);
  });
});

// -----------------------------------------------------------------------
// getReflectionInsights
// -----------------------------------------------------------------------

describe("getReflectionInsights", () => {
  it("returns insights for a specific session", async () => {
    const client = mockClient();
    const insights = [
      SAMPLE_INSIGHT,
      { ...SAMPLE_INSIGHT, id: "ri-002", insight_type: "contradiction", confidence: 0.9 },
    ];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(insights);

    const result = await getReflectionInsights(client, "ws-test", "rs-001");

    expect(client._call).toHaveBeenCalledWith("get_reflection_insights", [
      "ws-test",
      "rs-001",
    ]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("reflection_insight_result"),
      expect.objectContaining({ ws: "ws-test", sid: "rs-001" }),
    );
    expect(result).toHaveLength(2);
    expect(result[0].insight_type).toBe("pattern");
    expect(result[1].insight_type).toBe("contradiction");
  });
});

// -----------------------------------------------------------------------
// deleteReflectionSession
// -----------------------------------------------------------------------

describe("deleteReflectionSession", () => {
  it("calls delete_reflection_session reducer", async () => {
    const client = mockClient();

    await deleteReflectionSession(client, "ws-test", "rs-001");

    expect(client._call).toHaveBeenCalledWith("delete_reflection_session", [
      "ws-test",
      "rs-001",
    ]);
  });
});

// -----------------------------------------------------------------------
// Workspace isolation
// -----------------------------------------------------------------------

describe("workspace isolation", () => {
  it("getReflectionSessions returns different results for different workspaces", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce([{ ...SAMPLE_SESSION, workspace_id: "ws-a" }])
      .mockResolvedValueOnce([]);

    const resultA = await getReflectionSessions(client, "ws-a");
    const resultB = await getReflectionSessions(client, "ws-b");

    expect(client._call).toHaveBeenNthCalledWith(1, "get_reflection_sessions", ["ws-a"]);
    expect(client._call).toHaveBeenNthCalledWith(2, "get_reflection_sessions", ["ws-b"]);
    expect(resultA).toHaveLength(1);
    expect(resultB).toHaveLength(0);
  });

  it("createReflectionSession scopes session to workspace", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_SESSION]);

    await createReflectionSession(client, "ws-test", "peer-alice");

    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("workspace_id = :ws"),
      expect.objectContaining({ ws: "ws-test" }),
    );
  });
});
