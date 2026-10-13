import { defineConfig } from '@playwright/test'

// Real loopback HTTP request contracts need no browser or Next server.
export default defineConfig({
  testDir: './e2e',
  testMatch: ['d14-http-admission.spec.ts'],
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: 'list',
  outputDir: 'test-results/d14-http',
})
