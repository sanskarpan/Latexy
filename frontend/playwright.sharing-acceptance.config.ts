import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'sharing-capability-fullstack.spec.ts',
  workers: 1,
  retries: 0,
  expect: { timeout: 30_000 },
  reporter: [['list'], ['json', { outputFile: 'sharing-browser-results.json' }]],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://localhost:13420',
    actionTimeout: 30_000,
    navigationTimeout: 120_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: { args: ['--host-resolver-rules=MAP host.docker.internal 127.0.0.1'] },
  },
})
