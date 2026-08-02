/**
 * Unit tests for delta_sync.ts -- DeltaSync and ChangeEvent.
 *
 * Mocks the client's _call and _sql methods to avoid needing a live DB.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DeltaSync, ChangeEvent } from "../delta_sync";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ChangeEvent", () => {
  it("constructs a change event", () => {
    const ev: ChangeEvent = {
      id: "ev_001",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "insert",
      record_id: "mem_123",
      data_json: '{"content":"hello"}',
      created_at: 1000000,
      data: { content: "hello" },
    };
    expect(ev.id).toBe("ev_001");
    expect(ev.workspace_id).toBe("ws1");
    expect(ev.table_name).toBe("memory");
    expect(ev.operation).toBe("insert");
    expect(ev.record_id).toBe("mem_123");
    expect(ev.data).toEqual({ content: "hello" });
    expect(ev.created_at).toBe(1000000);
  });

  it("handles empty data_json gracefully", () => {
    const ev: ChangeEvent = {
      id: "ev_002",
      workspace_id: "ws1",
      table_name: "kg_node",
      operation: "delete",
      record_id: "node_456",
      data_json: "{}",
      created_at: 2000000,
      data: {},
    };
    expect(ev.data).toEqual({});
  });
});

describe("DeltaSync", () => {
  let mockClient: any;

  beforeEach(() => {
    vi.useFakeTimers();
    mockClient = {
      _call: vi.fn().mockResolvedValue(undefined),
      _sql: vi.fn(),
    };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("constructor", () => {
    it("creates instance with default poll interval", () => {
      const ds = new DeltaSync(mockClient);
      expect(ds.stats.poll_interval).toBe(0.1);
      expect(ds.stats.running).toBe(false);
    });

    it("clamps poll interval to minimum 0.01s", () => {
      const ds = new DeltaSync(mockClient, 0.001);
      expect(ds.stats.poll_interval).toBe(0.01);
    });

    it("auto-starts when autoStart=true", () => {
      mockClient._sql.mockResolvedValue([]);
      const ds = new DeltaSync(mockClient, 0.1, true);
      expect(ds.stats.running).toBe(true);
    });
  });

  describe("on / off", () => {
    it("registers a callback and returns a token", () => {
      const ds = new DeltaSync(mockClient);
      const cb = vi.fn();
      const token = ds.on("memory", "insert", cb);
      expect(token).toBeDefined();
      expect(ds.stats.callbacks).toBe(1);
    });

    it("unregisters a callback via token", () => {
      const ds = new DeltaSync(mockClient);
      const cb = vi.fn();
      const token = ds.on("memory", "insert", cb);
      expect(ds.stats.callbacks).toBe(1);
      ds.off(token);
      expect(ds.stats.callbacks).toBe(0);
    });

    it("supports wildcard table '*' ", () => {
      const ds = new DeltaSync(mockClient);
      const cb = vi.fn();
      ds.on("*", "insert", cb);
      expect(ds.stats.callbacks).toBe(1);
    });

    it("supports wildcard operation '*' ", () => {
      const ds = new DeltaSync(mockClient);
      const cb = vi.fn();
      ds.on("memory", "*", cb);
      expect(ds.stats.callbacks).toBe(1);
    });
  });

  describe("start / stop", () => {
    it("start() bootstraps cursor and starts polling", async () => {
      mockClient._sql.mockResolvedValueOnce([
        { events_json: JSON.stringify({ cursor: 42 }) },
      ]);

      const ds = new DeltaSync(mockClient);
      ds.start();
      await vi.advanceTimersByTimeAsync(10);

      expect(ds.stats.running).toBe(true);
      expect(mockClient._call).toHaveBeenCalledWith("get_latest_change_cursor", []);
      expect(ds.stats.cursor).toBe(42);
    });

    it("stop() stops polling", () => {
      const ds = new DeltaSync(mockClient);
      ds.start();
      expect(ds.stats.running).toBe(true);
      ds.stop();
      expect(ds.stats.running).toBe(false);
    });

    it("start() is idempotent", () => {
      const ds = new DeltaSync(mockClient);
      ds.start();
      ds.start();
      expect(ds.stats.running).toBe(true);
    });
  });

  describe("polling and dispatch", () => {
    it("polls, fetches events, and dispatches to matching callbacks", async () => {
      mockClient._sql.mockResolvedValueOnce([
        { events_json: JSON.stringify({ cursor: 10 }) },
      ]);

      const ds = new DeltaSync(mockClient);
      const cb = vi.fn();
      ds.on("memory", "insert", cb);
      ds.start();
      await vi.advanceTimersByTimeAsync(10);

      const eventsJson = JSON.stringify([
        {
          id: "ev_100",
          workspace_id: "ws1",
          table_name: "memory",
          operation: "insert",
          record_id: "mem_999",
          data_json: JSON.stringify({ content: "test" }),
          created_at: 100,
        },
      ]);

      mockClient._sql.mockResolvedValueOnce([{ events_json: eventsJson }]);
      await vi.advanceTimersByTimeAsync(200);

      expect(mockClient._call).toHaveBeenCalledWith("get_changes_since", [10]);
      expect(cb).toHaveBeenCalledTimes(1);

      const event = cb.mock.calls[0][0] as ChangeEvent;
      expect(event.id).toBe("ev_100");
      expect(event.table_name).toBe("memory");
      expect(event.operation).toBe("insert");
      expect(ds.stats.cursor).toBe(100);
    });

    it("does not dispatch to non-matching subscriptions", async () => {
      mockClient._sql.mockResolvedValueOnce([
        { events_json: JSON.stringify({ cursor: 0 }) },
      ]);

      const ds = new DeltaSync(mockClient);
      const cbMemory = vi.fn();
      const cbNode = vi.fn();
      ds.on("memory", "insert", cbMemory);
      ds.on("kg_node", "insert", cbNode);
      ds.start();
      await vi.advanceTimersByTimeAsync(10);

      const eventsJson = JSON.stringify([
        {
          id: "ev_200",
          workspace_id: "ws1",
          table_name: "memory",
          operation: "insert",
          record_id: "mem_555",
          data_json: "{}",
          created_at: 200,
        },
      ]);

      mockClient._sql.mockResolvedValueOnce([{ events_json: eventsJson }]);
      await vi.advanceTimersByTimeAsync(200);

      expect(cbMemory).toHaveBeenCalledTimes(1);
      expect(cbNode).toHaveBeenCalledTimes(0);
    });

    it("handles operation wildcard (*) dispatch", async () => {
      mockClient._sql.mockResolvedValueOnce([
        { events_json: JSON.stringify({ cursor: 0 }) },
      ]);

      const ds = new DeltaSync(mockClient);
      const cb = vi.fn();
      ds.on("memory", "*", cb);
      ds.start();
      await vi.advanceTimersByTimeAsync(10);

      const eventsJson = JSON.stringify([
        {
          id: "ev_300",
          workspace_id: "ws1",
          table_name: "memory",
          operation: "update",
          record_id: "mem_777",
          data_json: "{}",
          created_at: 300,
        },
      ]);

      mockClient._sql.mockResolvedValueOnce([{ events_json: eventsJson }]);
      await vi.advanceTimersByTimeAsync(200);

      expect(cb).toHaveBeenCalledTimes(1);
      expect(cb.mock.calls[0][0].operation).toBe("update");
    });

    it("recovers gracefully from bootstrap failure", async () => {
      mockClient._sql.mockResolvedValueOnce([]);

      const ds = new DeltaSync(mockClient);
      ds.start();
      await vi.advanceTimersByTimeAsync(10);

      expect(ds.stats.running).toBe(true);
      expect(ds.stats.cursor).toBe(0);
    });

    it("recovers gracefully from poll errors", async () => {
      mockClient._sql.mockResolvedValueOnce([
        { events_json: JSON.stringify({ cursor: 0 }) },
      ]);

      const ds = new DeltaSync(mockClient);
      const cb = vi.fn();
      ds.on("memory", "insert", cb);
      ds.start();
      await vi.advanceTimersByTimeAsync(10);

      mockClient._call.mockRejectedValueOnce(new Error("network error"));
      await vi.advanceTimersByTimeAsync(200);

      expect(ds.stats.errors).toBe(1);
      expect(cb).toHaveBeenCalledTimes(0);
    });
  });

  describe("stats", () => {
    it("returns running state and counters", () => {
      const ds = new DeltaSync(mockClient);
      const stats = ds.stats;
      expect(stats).toHaveProperty("running", false);
      expect(stats).toHaveProperty("cursor", 0);
      expect(stats).toHaveProperty("polls", 0);
      expect(stats).toHaveProperty("errors", 0);
      expect(stats).toHaveProperty("poll_interval", 0.1);
      expect(stats).toHaveProperty("callbacks", 0);
    });
  });
});
