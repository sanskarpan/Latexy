import { defineConfig, devices } from '@playwright/test'

const port = Number(process.env.PLAYWRIGHT_PWA_POLICY_PORT ?? '5195')

// Optional-registration failures need the actual production entry, without a
// successful registration fixture. Keep the real 12-case lifecycle gate separate.
export default defineConfig({
  testDir: './e2e',
  testMatch: ['pwa-registration-policy.spec.ts'],
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 12_000 },
  outputDir: 'test-results/pwa-policy',
  reporter: [['list'], ['json', { outputFile: 'test-results/pwa-policy/report.json' }]],
  use: {
    baseURL: `http://localhost:${port}`,
    serviceWorkers: 'block',
    actionTimeout: 12_000,
    navigationTimeout: 60_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium-pwa-policy', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `node scripts/playwright-server.mjs --port ${port} --mode production`,
    url: `http://localhost:${port}/updates`,
    reuseExistingServer: false,
    timeout: 1_800_000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 },
  },
})
