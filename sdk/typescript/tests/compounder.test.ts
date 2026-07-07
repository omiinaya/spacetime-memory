/**
 * Tests for the Compounder class and its exports.
 *
 * Covers:
 *  - Module-level re-exports from client.ts
 *  - Instantiation and method parity (14 public methods matching Python SDK)
 */
import { describe, it, expect } from "vitest";
import { Compounder } from "../client";
import { Client } from "../client";

describe("Compounder exports", () => {
  it("should export Compounder class from main entry point", () => {
    expect(Compounder).toBeDefined();
    expect(typeof Compounder).toBe("function");
  });

  it("should construct Compounder with a Client", () => {
    const client = new Client({ host: "localhost", port: 3001 });
    const cp = new Compounder(client);
    expect(cp).toBeDefined();
    expect(cp instanceof Compounder).toBe(true);
  });

  it("should have 14 public compounder methods", () => {
    const publicMethods = Object.getOwnPropertyNames(Compounder.prototype)
      .filter(k => k !== "constructor" && !k.startsWith("_"));
    expect(publicMethods.length).toBeGreaterThanOrEqual(14);

    // All expected method names (matches Python SDK compounder public API)
    const expected = [
      "searchEntities",
      "findNearDuplicates",
      "storeAnswer",
      "storeAnswers",
      "crossLink",
      "suggestConnections",
      "lintWorkspace",
      "ingestSource",
      "createEntityPage",
      "updateEntityPage",
      "createConceptPage",
      "createComparisonPage",
      "exportWorkspace",
      "generateOverviewPage",
    ];
    for (const method of expected) {
      expect(publicMethods).toContain(method);
    }
  });
});
