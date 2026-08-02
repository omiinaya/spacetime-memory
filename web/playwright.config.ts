import { defineConfig } from "@playwright/test";

/**
 * Spacetime Memory dashboard E2E suite.
 *
 * Runs against the live dashboard (Vite dev server on :5187) with the real
 * backend stack: STDB (:3001), stdb-sql-proxy (:5190), embedder collector (:9190).
 *
 * Config notes (see e2e-testing-playwright skill):
 *  - workers: 1 + fullyParallel: false — single Vite dev server, parallel
 *    workers cause transpilation contention and timeouts.
 *  - timeout: 90s — Vite dev server degrades under sustained navigation;
 *    90s gives cold-start compilation room.
 *  - retries: 1 — catches the rare Vite hiccup, keeps runtime predictable.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 1,
  workers: 1,
  timeout: 90000,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: "http://127.0.0.1:5187",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
