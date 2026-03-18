import { defineConfig, devices } from '@playwright/test'

// Latexy2 dev server uses slot 2 (port 5181) when slot 1 is taken by Latexy.
// Override with PLAYWRIGHT_PORT env var if needed.
const PORT = parseInt(process.env.PLAYWRIGHT_PORT ?? '5181')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 1,
  workers: process.env.CI ? 2 : 2,
  reporter: 'html',
  timeout: 30_000,
  expect: { timeout: 12_000 },

  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  /* Start dev server automatically if not already running */
  webServer: {
    command: `pnpm dev --port ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
