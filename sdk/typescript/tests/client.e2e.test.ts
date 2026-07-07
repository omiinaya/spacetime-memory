/**
 * E2E tests for the spacetime-memory TypeScript SDK Client.
 *
 * Tests against the live SpacetimeDB instance at 127.0.0.1:3001.
 * These tests require a running SpacetimeDB server and module.
 */

import { describe, it, expect } from "vitest";
import { Client } from "../client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STDB_OPTS = {
  host: "127.0.0.1",
  port: 3001,
  database: "spacetime-memory",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Client E2E (live STDB)", () => {
  let client: Client;

  beforeEach(() => {
    client = new Client(STDB_OPTS);
  });

  // -- Connectivity ---------------------------------------------------------

  it("connects to STDB and queries a public table", async () => {
    const rows = await (client as any)._sql(
      "SELECT * FROM user_memory_result LIMIT 1",
    );
    expect(Array.isArray(rows)).toBe(true);
  });

  it("queries peer_reputation public table", async () => {
    const rows = await (client as any)._sql(
      "SELECT * FROM peer_reputation LIMIT 1",
    );
    expect(Array.isArray(rows)).toBe(true);
  });

  it("queries hybrid_result public table", async () => {
    const rows = await (client as any)._sql(
      "SELECT * FROM hybrid_result LIMIT 1",
    );
    expect(Array.isArray(rows)).toBe(true);
  });

  it("queries context_directory public table", async () => {
    const rows = await (client as any)._sql(
      "SELECT * FROM context_directory LIMIT 1",
    );
    expect(Array.isArray(rows)).toBe(true);
  });

  it("queries graph_traversal_result public table", async () => {
    const rows = await (client as any)._sql(
      "SELECT * FROM graph_traversal_result LIMIT 1",
    );
    expect(Array.isArray(rows)).toBe(true);
  });

  // -- SQL error handling ---------------------------------------------------

  it("throws on invalid SQL query", async () => {
    await expect(
      (client as any)._sql("SELECT * FROM nonexistent_table"),
    ).rejects.toThrow();
  });

  // -- Reducer calls --------------------------------------------------------

  it("calling ping returns status (ok or error)", async () => {
    const result = await client.ping();
    expect(result).toHaveProperty("status");
    expect(["ok", "error"]).toContain(result.status);
  });

  // -- SQL injection safety (live) -----------------------------------------

  it("SQL injection attempt does not crash the server", async () => {
    try {
      await (client as any)._sqlExec(
        "SELECT * FROM user_memory_result WHERE id = :id",
        { id: "'; DROP TABLE user_memory_result; --" },
      );
    } catch {
      // Error is acceptable; the server must survive
    }
    const rows = await (client as any)._sql(
      "SELECT * FROM user_memory_result LIMIT 1",
    );
    expect(Array.isArray(rows)).toBe(true);
  });
});
