/**
 * Tests for cognitiveOps.ts TypeScript SDK module.
 *
 * These tests use vitest with mocked ClientLike instances to verify
 * that the wrapper functions call the correct reducers and query
 * the correct result tables.
 */
import { describe, it, expect, vi } from "vitest";
import {
  registerCognitiveOp,
  unregisterCognitiveOp,
  getCognitiveOps,
  executeCognitiveOp,
  getCognitivePipeline,
} from "../src/cognitiveOps";
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

const SAMPLE_COGNITIVE_OP = {
  id: "cop-001",
  workspace_id: "ws-test",
  name: "entity_extract",
  op_type: "extract",
  description: "Extract entities from text",
  config_json: '{"model":"default"}',
  pipeline_stage_type: "entity_extraction",
  created_at: 1000000,
  updated_at: 1000000,
};

const SAMPLE_RESULT = {
  id: "res-001",
  workspace_id: "ws-test",
  data: '{"entities":["Alice","Bob"]}',
  created_at: 1000000,
};

// -----------------------------------------------------------------------
// registerCognitiveOp
// -----------------------------------------------------------------------

describe("registerCognitiveOp", () => {
  it("calls register_cognitive_op reducer with correct args", async () => {
    const client = mockClient();
    (client._call as ReturnType<typeof vi.fn>).mockResolvedValue({ status: "ok" });

    const result = await registerCognitiveOp(
      client,
      "ws-test",
      "entity_extract",
      "extract",
      "Extract entities from text",
      '{"model":"default"}',
      "entity_extraction",
    );

    expect(client._call).toHaveBeenCalledWith("register_cognitive_op", [
      "ws-test", "", "entity_extract", "extract",
      "Extract entities from text", '{"model":"default"}', "entity_extraction",
    ]);
    expect(result).toEqual({ status: "ok" });
  });

  it("uses default values for optional parameters", async () => {
    const client = mockClient();

    await registerCognitiveOp(client, "ws-test", "simple_op", "observe");

    expect(client._call).toHaveBeenCalledWith("register_cognitive_op", [
      "ws-test", "", "simple_op", "observe",
      "", "{}", "",
    ]);
  });
});

// -----------------------------------------------------------------------
// unregisterCognitiveOp
// -----------------------------------------------------------------------

describe("unregisterCognitiveOp", () => {
  it("calls unregister_cognitive_op reducer with correct args", async () => {
    const client = mockClient();

    await unregisterCognitiveOp(client, "ws-test", "cop-001");

    expect(client._call).toHaveBeenCalledWith("unregister_cognitive_op", [
      "ws-test", "cop-001",
    ]);
  });
});

// -----------------------------------------------------------------------
// getCognitiveOps
// -----------------------------------------------------------------------

describe("getCognitiveOps", () => {
  it("calls get_cognitive_ops reducer and returns parsed ops", async () => {
    const client = mockClient();
    const ops = [
      { ...SAMPLE_COGNITIVE_OP, id: "cop-001", name: "entity_extract" },
      { ...SAMPLE_COGNITIVE_OP, id: "cop-002", name: "semantic_search", op_type: "observe" },
    ];
    const rows = [{ data: JSON.stringify(ops) }];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(rows);

    const result = await getCognitiveOps(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("get_cognitive_ops", ["ws-test", ""]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("cognitive_op_result"),
      expect.objectContaining({ ws: "ws-test" }),
    );
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe("entity_extract");
    expect(result[1].name).toBe("semantic_search");
  });

  it("returns empty array when no ops exist", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await getCognitiveOps(client, "ws-empty");

    expect(result).toEqual([]);
  });

  it("passes opTypeFilter to the reducer call", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    await getCognitiveOps(client, "ws-test", "extract");

    expect(client._call).toHaveBeenCalledWith("get_cognitive_ops", ["ws-test", "extract"]);
  });
});

// -----------------------------------------------------------------------
// executeCognitiveOp
// -----------------------------------------------------------------------

describe("executeCognitiveOp", () => {
  it("calls execute_cognitive_op reducer and returns parsed result", async () => {
    const client = mockClient();
    const resultData = { status: "ok", output: "processed" };
    const rows = [{ data: JSON.stringify(resultData) }];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(rows);

    const result = await executeCognitiveOp(client, "ws-test", "cop-001", { query: "test" });

    expect(client._call).toHaveBeenCalledWith("execute_cognitive_op", [
      "ws-test", "cop-001", JSON.stringify({ query: "test" }),
    ]);
    expect(result).toEqual(resultData);
  });

  it("returns error result when no data found", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await executeCognitiveOp(client, "ws-test", "cop-nonexistent");

    expect(result).toEqual({ status: "error", message: "No result found" });
  });
});

// -----------------------------------------------------------------------
// getCognitivePipeline
// -----------------------------------------------------------------------

describe("getCognitivePipeline", () => {
  it("calls get_cognitive_pipeline reducer and returns ordered pipeline", async () => {
    const client = mockClient();
    const pipeline = [
      { ...SAMPLE_COGNITIVE_OP, id: "cop-001", name: "semantic_search", op_type: "observe" },
      { ...SAMPLE_COGNITIVE_OP, id: "cop-002", name: "entity_extract", op_type: "extract" },
      { ...SAMPLE_COGNITIVE_OP, id: "cop-003", name: "categorize", op_type: "classify" },
    ];
    const rows = [{ data: JSON.stringify(pipeline) }];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(rows);

    const result = await getCognitivePipeline(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("get_cognitive_pipeline", ["ws-test"]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("cognitive_op_result"),
      expect.objectContaining({ ws: "ws-test" }),
    );
    expect(result).toHaveLength(3);
    expect(result[0].op_type).toBe("observe");
    expect(result[1].op_type).toBe("extract");
    expect(result[2].op_type).toBe("classify");
  });

  it("returns empty array when no pipeline data", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await getCognitivePipeline(client, "ws-empty");

    expect(result).toEqual([]);
  });
});
