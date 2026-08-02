/**
 * Unit tests for ws_subscription.ts -- WsSubscription.
 *
 * Mocks the WebSocket to avoid needing a live server.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WsSubscription, ChangeEvent } from "../ws_subscription";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Create a minimal mock WebSocket that we can control. */
function createMockWebSocket(): any {
  const mock: any = {
    readyState: 0,
    CONNECTING: 0,
    OPEN: 1,
    CLOSING: 2,
    CLOSED: 3,
    send: vi.fn(),
    close: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  return mock;
}

describe("WsSubscription", () => {
  let ws: WsSubscription;

  beforeEach(() => {
    ws = new WsSubscription("ws://localhost:8765", false);
  });

  afterEach(() => {
    ws.disconnect();
  });

  it("starts disconnected", () => {
    expect(ws.connected).toBe(false);
    expect(ws.stats.connected).toBe(false);
    expect(ws.stats.callbacks).toBe(0);
  });

  it("registers and unregisters callbacks", () => {
    const cb = vi.fn();
    const token = ws.on("memory", "insert", cb);
    expect(ws.stats.callbacks).toBe(1);

    ws.off(token);
    expect(ws.stats.callbacks).toBe(0);
  });

  it("dispatches change events to matching callbacks", () => {
    const cb = vi.fn();
    ws.on("memory", "insert", cb);

    const event: ChangeEvent = {
      id: "ev_001",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "insert",
      record_id: "mem_123",
      data_json: '{"content":"hello"}',
      created_at: 1000000,
      data: { content: "hello" },
    };

    (ws as any)._dispatch(event);

    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb).toHaveBeenCalledWith(event);
  });

  it("does not dispatch to non-matching callbacks", () => {
    const cb = vi.fn();
    ws.on("kg_node", "insert", cb);

    const event: ChangeEvent = {
      id: "ev_002",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "insert",
      record_id: "mem_456",
      data_json: "{}",
      created_at: 2000000,
      data: {},
    };

    (ws as any)._dispatch(event);
    expect(cb).not.toHaveBeenCalled();
  });

  it("dispatches to wildcard table callbacks", () => {
    const cb = vi.fn();
    ws.on("*", "insert", cb);

    const event: ChangeEvent = {
      id: "ev_003",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "insert",
      record_id: "mem_789",
      data_json: "{}",
      created_at: 3000000,
      data: {},
    };

    (ws as any)._dispatch(event);
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("dispatches to wildcard operation callbacks", () => {
    const cb = vi.fn();
    ws.on("memory", "*", cb);

    const event: ChangeEvent = {
      id: "ev_004",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "update",
      record_id: "mem_101",
      data_json: "{}",
      created_at: 4000000,
      data: {},
    };

    (ws as any)._dispatch(event);
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("handles multiple callbacks on the same table/operation", () => {
    const cb1 = vi.fn();
    const cb2 = vi.fn();
    ws.on("memory", "insert", cb1);
    ws.on("memory", "insert", cb2);

    const event: ChangeEvent = {
      id: "ev_005",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "insert",
      record_id: "mem_202",
      data_json: "{}",
      created_at: 5000000,
      data: {},
    };

    (ws as any)._dispatch(event);
    expect(cb1).toHaveBeenCalledTimes(1);
    expect(cb2).toHaveBeenCalledTimes(1);
  });

  it("handles callback errors gracefully", () => {
    const cb = vi.fn(() => { throw new Error("oops"); });
    ws.on("memory", "insert", cb);

    const event: ChangeEvent = {
      id: "ev_006",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "insert",
      record_id: "mem_303",
      data_json: "{}",
      created_at: 6000000,
      data: {},
    };

    expect(() => (ws as any)._dispatch(event)).not.toThrow();
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("parses events correctly", () => {
    const raw = {
      id: "ev_007",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "insert",
      record_id: "mem_404",
      data_json: '{"content":"parsed"}',
      created_at: 7000000,
    };

    const parsed = (ws as any)._parseEvent(raw);
    expect(parsed.id).toBe("ev_007");
    expect(parsed.data).toEqual({ content: "parsed" });
  });

  it("handles invalid JSON in data_json", () => {
    const raw = {
      id: "ev_008",
      workspace_id: "ws1",
      table_name: "memory",
      operation: "insert",
      record_id: "mem_505",
      data_json: "not-json",
      created_at: 8000000,
    };

    const parsed = (ws as any)._parseEvent(raw);
    expect(parsed.data).toEqual({});
  });

  it("sends messages when connected", () => {
    const mockWs = createMockWebSocket();
    mockWs.readyState = 1; // WebSocket.OPEN
    (ws as any)._ws = mockWs;
    (ws as any)._connected = true;

    (ws as any)._sendMessage({ type: "ping" });
    expect((ws as any)._messagesSent).toBe(1);
  });

  it("queues messages when not connected", () => {
    (ws as any)._connected = false;
    (ws as any)._sendMessage({ type: "ping" });
    expect((ws as any)._outbox.length).toBe(1);
  });

  it("drains outbox on connection", () => {
    const mockWs = createMockWebSocket();
    (ws as any)._ws = mockWs;
    (ws as any)._connected = true;
    (ws as any)._outbox.push({ type: "ping" });
    (ws as any)._drainOutbox();
    expect(mockWs.send).toHaveBeenCalledTimes(1);
  });

  it("provides stats", () => {
    const stats = ws.stats;
    expect(stats.connected).toBe(false);
    expect(stats.uri).toBe("ws://localhost:8765");
    expect(stats.callbacks).toBe(0);
    expect(stats.messages_sent).toBe(0);
    expect(stats.errors).toBe(0);
    expect(stats.reconnects).toBe(0);
  });
});
