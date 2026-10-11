import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  // Keep the integrity guard native ESM: the CommonJS test transform otherwise
  // rewrites its imports but leaves import.meta, preventing proof collection.
  build: { external: ['**/scripts/next-hydration-backport.mjs'] },
  testDir: './e2e',
  testMatch: ['**/hydration-session-store.opt-in.ts', '**/hydration-host-replay.opt-in.ts'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  globalTimeout: 240_000,
  reporter: 'line',
  use: { ...devices['Desktop Chrome'] },
})
