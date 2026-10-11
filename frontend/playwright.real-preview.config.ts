import { defineConfig, devices } from '@playwright/test'
import { resolve } from 'node:path'
import { localHttpOrigin } from './scripts/real-preview-contract.mjs'

// The isolated harness owns startup and teardown. Refuse implicit/prod URLs.
const baseURL = localHttpOrigin(process.env.REAL_PREVIEW_BASE_URL)
localHttpOrigin(process.env.REAL_PREVIEW_API_URL)
const evidence = resolve(process.env.CI_ISOLATED_EVIDENCE_DIR ?? 'test-results/real-preview')

export default defineConfig({
  testDir: './e2e/real-preview',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  // Two real guest admissions include the unchanged five-minute cooldown.
  timeout: 660_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['junit', { outputFile: resolve(evidence, 'real-preview.xml') }]],
  outputDir: resolve(evidence, 'playwright'),
  use: {
    baseURL,
    viewport: { width: 1440, height: 1000 },
    actionTimeout: 15_000,
    navigationTimeout: 60_000,
    // Do not capture request bodies, tokens, source or browser identities in
    // traces. The spec emits only a redacted identity/transport summary.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [{ name: 'real-chromium', use: { ...devices['Desktop Chrome'] } }],
})
