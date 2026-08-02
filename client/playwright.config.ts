import { defineConfig } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

// Read the STDB server token from the CLI config (never hardcode credentials).
function stdbToken(): string {
  try {
    const raw = readFileSync(join(homedir(), '.config/spacetime/cli.toml'), 'utf8');
    const m = raw.match(/spacetimedb_token\s*=\s*"([^"]+)"/);
    return m ? m[1] : '';
  } catch {
    return '';
  }
}

const TOKEN = stdbToken();

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: 1,
  // 48-core host: default workers (~24) all compile against the cold Vite
  // dev server on first load, causing heading-render flakes. Cap at 6 for
  // stability; runtime is still parallelized across spec files.
  workers: 6,
  use: {
    // Dedicated port: 5173 is claimed by other projects' dev servers
    // (amalgam, mrx-cc). --strictPort makes Vite fail loudly instead of
    // silently falling to a different port the config doesn't know about.
    // VITE_SPACETIMEDB_DB points at the live database and the token grants
    // private-table access so pages render real data (the default hash is a
    // stale dev DB with no tables).
    baseURL: 'http://localhost:5191',
    headless: true,
  },
  webServer: {
    command: `VITE_SPACETIMEDB_DB=spacetime-memory-v2 VITE_SPACETIMEDB_HOST=localhost:3001 VITE_SPACETIMEDB_WS=ws://localhost:3001 VITE_SPACETIMEDB_TOKEN=${TOKEN} npm run dev -- --port 5191 --strictPort`,
    url: 'http://localhost:5191',
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
