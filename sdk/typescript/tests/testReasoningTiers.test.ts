/**
 * Tests for reasoningTiers.ts TypeScript SDK module.
 *
 * These tests use vitest with mocked ClientLike instances to verify
 * that the wrapper functions call the correct reducers and query
 * the correct result tables.
 */
import { describe, it, expect, vi } from "vitest";
import {
  createReasoningTier,
  updateReasoningTier,
  deleteReasoningTier,
  getReasoningTiers,
  getDefaultReasoningTier,
  setDefaultTier,
  applyReasoningTierToMemory,
  DEFAULT_REASONING_TIERS,
} from "../src/reasoningTiers";
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

const SAMPLE_TIER = {
  id: "tier-001",
  workspace_id: "ws-test",
  name: "balanced",
  description: "Default balanced reasoning tier for most queries",
  max_tokens: 1024,
  temperature: 0.7,
  top_p: 0.9,
  max_context_memories: 15,
  min_confidence: 0.5,
  requires_reflection: false,
  requires_graph_traversal: false,
  priority: 20,
  is_default: true,
  created_at: 1000000,
  updated_at: 1000000,
};

// -----------------------------------------------------------------------
// DEFAULT_REASONING_TIERS
// -----------------------------------------------------------------------

describe("DEFAULT_REASONING_TIERS", () => {
  it("has all 4 expected tier definitions", () => {
    const names = Object.keys(DEFAULT_REASONING_TIERS);
    expect(names.sort()).toEqual(["balanced", "deep", "quick", "research"]);
  });

  it("has balanced as the default tier", () => {
    expect(DEFAULT_REASONING_TIERS.balanced.is_default).toBe(true);
  });

  it("orders tiers by priority correctly", () => {
    expect(DEFAULT_REASONING_TIERS.quick.priority).toBeLessThan(
      DEFAULT_REASONING_TIERS.research.priority,
    );
  });

  it("research tier has max depth settings", () => {
    expect(DEFAULT_REASONING_TIERS.research.max_tokens).toBe(8192);
    expect(DEFAULT_REASONING_TIERS.research.requires_reflection).toBe(true);
    expect(DEFAULT_REASONING_TIERS.research.requires_graph_traversal).toBe(true);
  });
});

// -----------------------------------------------------------------------
// createReasoningTier
// -----------------------------------------------------------------------

describe("createReasoningTier", () => {
  it("calls create_reasoning_tier reducer with correct args", async () => {
    const client = mockClient();
    (client._call as ReturnType<typeof vi.fn>).mockResolvedValue({ status: "ok" });

    const result = await createReasoningTier(
      client,
      "ws-test",
      "custom-tier",
      "Custom description",
      512,
      0.5,
      0.8,
      10,
      0.6,
      true,
      false,
      15,
      false,
    );

    expect(client._call).toHaveBeenCalledWith("create_reasoning_tier", [
      "ws-test", "", "custom-tier", "Custom description",
      512, 0.5, 0.8,
      10, 0.6,
      true, false,
      15, false,
    ]);
    expect(result).toEqual({ status: "ok" });
  });

  it("uses default values for optional parameters", async () => {
    const client = mockClient();

    await createReasoningTier(client, "ws-test", "quick");

    expect(client._call).toHaveBeenCalledWith("create_reasoning_tier", [
      "ws-test", "", "quick", "",
      1024, 0.7, 0.9,
      15, 0.5,
      false, false,
      20, false,
    ]);
  });
});

// -----------------------------------------------------------------------
// updateReasoningTier
// -----------------------------------------------------------------------

describe("updateReasoningTier", () => {
  it("calls update_reasoning_tier reducer with updated fields", async () => {
    const client = mockClient();
    (client._call as ReturnType<typeof vi.fn>).mockResolvedValue({ status: "ok" });

    const result = await updateReasoningTier(
      client,
      "ws-test",
      "tier-001",
      "new-name",
      "",
      2048,
      0.5,
      0.95,
      25,
      0.3,
      true,
      true,
      30,
      true,
    );

    expect(client._call).toHaveBeenCalledWith("update_reasoning_tier", [
      "ws-test", "tier-001", "new-name", "",
      2048, 0.5, 0.95,
      25, 0.3,
      true, true,
      30, true,
    ]);
    expect(result).toEqual({ status: "ok" });
  });
});

// -----------------------------------------------------------------------
// deleteReasoningTier
// -----------------------------------------------------------------------

describe("deleteReasoningTier", () => {
  it("calls delete_reasoning_tier reducer with correct args", async () => {
    const client = mockClient();

    await deleteReasoningTier(client, "ws-test", "tier-001");

    expect(client._call).toHaveBeenCalledWith("delete_reasoning_tier", [
      "ws-test", "tier-001",
    ]);
  });
});

// -----------------------------------------------------------------------
// getReasoningTiers
// -----------------------------------------------------------------------

describe("getReasoningTiers", () => {
  it("calls get_reasoning_tiers and returns parsed tiers", async () => {
    const client = mockClient();
    const tiers = [
      { ...SAMPLE_TIER, id: "tier-001", name: "quick" },
      { ...SAMPLE_TIER, id: "tier-002", name: "balanced" },
    ];
    const rows = [{ data: JSON.stringify(tiers) }];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(rows);

    const result = await getReasoningTiers(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("get_reasoning_tiers", ["ws-test"]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("reasoning_tier_result"),
      expect.objectContaining({ ws: "ws-test" }),
    );
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe("quick");
    expect(result[1].name).toBe("balanced");
  });

  it("returns empty array when no tiers exist", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await getReasoningTiers(client, "ws-empty");

    expect(result).toEqual([]);
  });
});

// -----------------------------------------------------------------------
// getDefaultReasoningTier
// -----------------------------------------------------------------------

describe("getDefaultReasoningTier", () => {
  it("returns the default tier from result data", async () => {
    const client = mockClient();
    const defaultTier = { ...SAMPLE_TIER, name: "balanced", is_default: true };
    const rows = [{ data: JSON.stringify(defaultTier) }];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(rows);

    const result = await getDefaultReasoningTier(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("get_default_reasoning_tier", ["ws-test"]);
    expect(result).not.toBeNull();
    expect(result!.name).toBe("balanced");
    expect(result!.is_default).toBe(true);
  });

  it("returns null when no default tier set", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await getDefaultReasoningTier(client, "ws-empty");

    expect(result).toBeNull();
  });
});

// -----------------------------------------------------------------------
// setDefaultTier
// -----------------------------------------------------------------------

describe("setDefaultTier", () => {
  it("calls set_default_tier reducer with correct args", async () => {
    const client = mockClient();

    await setDefaultTier(client, "ws-test", "tier-001");

    expect(client._call).toHaveBeenCalledWith("set_default_tier", [
      "ws-test", "tier-001",
    ]);
  });
});

// -----------------------------------------------------------------------
// applyReasoningTierToMemory
// -----------------------------------------------------------------------

describe("applyReasoningTierToMemory", () => {
  it("calls apply_reasoning_tier_to_memory reducer with correct args", async () => {
    const client = mockClient();

    await applyReasoningTierToMemory(client, "ws-test", "mem-001", "tier-001");

    expect(client._call).toHaveBeenCalledWith("apply_reasoning_tier_to_memory", [
      "ws-test", "mem-001", "tier-001",
    ]);
  });
});
