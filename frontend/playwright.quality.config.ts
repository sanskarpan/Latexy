import { defineConfig, devices } from '@playwright/test'

const PORT = Number.parseInt(process.env.PLAYWRIGHT_QUALITY_PORT ?? '5182', 10)

export default defineConfig({
    testDir: './e2e/quality',
    // Keep each engine's cases serial so browser process count and CI memory stay bounded.
    fullyParallel: false,
    forbidOnly: Boolean(process.env.CI),
    retries: process.env.CI ? 1 : 0,
    workers: process.env.CI ? 3 : 5,
    reporter: process.env.CI
        ? [['list'], ['html', { outputFolder: 'playwright-quality-report', open: 'never' }]]
        : 'list',
    // Cold Next.js route compilation is shared by several engines in CI.
    timeout: 120_000,
    expect: { timeout: 12_000 },
    outputDir: 'test-results/quality',

    use: {
        baseURL: `http://localhost:${PORT}`,
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
    },

    projects: [
        {
            name: 'desktop-chromium',
            use: { ...devices['Desktop Chrome'] },
            metadata: { mobile: false },
        },
        {
            name: 'desktop-firefox',
            use: { ...devices['Desktop Firefox'] },
            metadata: { mobile: false },
        },
        {
            name: 'desktop-webkit',
            use: { ...devices['Desktop Safari'] },
            metadata: { mobile: false },
        },
        {
            name: 'mobile-chromium',
            use: { ...devices['Pixel 7'] },
            metadata: { mobile: true },
        },
        {
            name: 'mobile-webkit',
            use: { ...devices['iPhone 14 Pro'] },
            metadata: { mobile: true },
        },
    ],

    webServer: {
        command: `pnpm dev --port ${PORT}`,
        url: `http://localhost:${PORT}`,
        reuseExistingServer: true,
        timeout: 60_000,
        env: {
            NEXT_PUBLIC_WS_URL: `ws://localhost:${PORT}`,
        },
    },
})
