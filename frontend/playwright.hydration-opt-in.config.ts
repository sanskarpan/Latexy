import { defineConfig } from '@playwright/test'
import baseConfig from './playwright.config'

export default defineConfig({
  ...baseConfig,
  testMatch: '**/hydration-route-chunk.opt-in.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'line',
  timeout: 90_000,
  use: {
    ...baseConfig.use,
    trace: 'on',
  },
})
