/**
 * Tests for server-side pattern detection TypeScript SDK wrappers.
 *
 * These tests use vitest with mocked ClientLike instances to verify
 * that the wrapper functions call the correct reducers and query
 * the correct result tables.
 */
import { describe, it, expect, vi } from "vitest";
import {
  detectTemporalClusters,
  detectEntityCooccurrences,
  detectTopicClusters,
} from "../src/patternDetection";
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

const SAMPLE_TEMPORAL = {
  id: "tc-001",
  workspace_id: "ws-test",
  start_time: 1000000,
  end_time: 1001800,
  count: 3,
  memory_ids: '["m1","m2","m3"]',
  summary_terms: '["deploy","server","production"]',
  created_at: 2000000,
};

const SAMPLE_COOCCUR = {
  id: "ec-001",
  workspace_id: "ws-test",
  entity_a: "alice",
  entity_b: "bob",
  count: 5,
  strength: 0.625,
  created_at: 2000000,
};

const SAMPLE_TOPIC = {
  id: "tp-001",
  workspace_id: "ws-test",
  topic: "python",
  count: 4,
  memory_ids: '["m1","m2","m3","m4"]',
  top_terms: '["python","code","test"]',
  avg_confidence: 0.85,
  created_at: 2000000,
};

// -----------------------------------------------------------------------
// detectTemporalClusters
// -----------------------------------------------------------------------

describe("detectTemporalClusters", () => {
  it("calls the correct reducer and queries the result table", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_TEMPORAL]);

    const result = await detectTemporalClusters(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("detect_temporal_clusters", ["ws-test"]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("temporal_cluster_result"),
      expect.objectContaining({ ws: "ws-test" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].start_time).toBe(1000000);
    expect(result[0].count).toBe(3);
  });

  it("returns empty array when no clusters found", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await detectTemporalClusters(client, "ws-empty");

    expect(result).toEqual([]);
  });
});

// -----------------------------------------------------------------------
// detectEntityCooccurrences
// -----------------------------------------------------------------------

describe("detectEntityCooccurrences", () => {
  it("calls the correct reducer and queries the result table", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_COOCCUR]);

    const result = await detectEntityCooccurrences(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("detect_entity_cooccurrences", ["ws-test"]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("entity_cooccurrence_result"),
      expect.objectContaining({ ws: "ws-test" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].entity_a).toBe("alice");
    expect(result[0].entity_b).toBe("bob");
    expect(result[0].count).toBe(5);
  });

  it("returns empty array when no co-occurrences found", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await detectEntityCooccurrences(client, "ws-empty");

    expect(result).toEqual([]);
  });
});

// -----------------------------------------------------------------------
// detectTopicClusters
// -----------------------------------------------------------------------

describe("detectTopicClusters", () => {
  it("calls the correct reducer and queries the result table", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_TOPIC]);

    const result = await detectTopicClusters(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("detect_topic_clusters", ["ws-test"]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("topic_cluster_result"),
      expect.objectContaining({ ws: "ws-test" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].topic).toBe("python");
    expect(result[0].count).toBe(4);
  });

  it("returns empty array when no topic clusters found", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await detectTopicClusters(client, "ws-empty");

    expect(result).toEqual([]);
  });
});
