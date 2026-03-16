import { defineConfig, devices } from '@playwright/test'

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
    baseURL: 'http://localhost:5180',
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
    command: 'pnpm dev --port 5180',
    url: 'http://localhost:5180',
    reuseExistingServer: true,
    timeout: 30_000,
  },
})
