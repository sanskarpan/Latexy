import { defineConfig, devices } from '@playwright/test'

// Explicit selection always runs the production-only cases; a dedicated runner
// rejects missing, zero or skipped evidence. Never inherit a blocked worker.
process.env.PWA_PRODUCTION = '1'
const port = Number(process.env.PLAYWRIGHT_PWA_PORT ?? '5193')

export default defineConfig({
  testDir: './e2e',
  testMatch: ['**/pwa-production.spec.ts', '**/pwa-worker-lifecycle.spec.ts', '**/offline-compiled-pdf.spec.ts'],
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 12_000 },
  outputDir: 'test-results/pwa',
  reporter: [['list'], ['json', { outputFile: 'test-results/pwa/report.json' }]],
  use: {
    baseURL: `http://localhost:${port}`,
    serviceWorkers: 'allow',
    actionTimeout: 12_000,
    navigationTimeout: 60_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium-pwa', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'node scripts/pwa-acceptance-server.mjs',
    url: `http://localhost:${port}/sw.js`,
    reuseExistingServer: false,
    timeout: 1_800_000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 },
  },
})
