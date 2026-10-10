import { defineConfig, devices } from '@playwright/test'

const PORT = Number.parseInt(process.env.PLAYWRIGHT_QUALITY_PORT ?? '5182', 10)
const reuseExistingServer = process.env.PLAYWRIGHT_REUSE_EXISTING_SERVER === '1'

export default defineConfig({
    testDir: './e2e/quality',
    // Keep each engine's cases serial so browser process count and CI memory stay bounded.
    fullyParallel: false,
    forbidOnly: Boolean(process.env.CI),
    retries: process.env.CI ? 1 : 0,
    workers: 1,
    reporter: process.env.CI
        ? [['list'], ['html', { outputFolder: 'playwright-quality-report', open: 'never' }]]
        : 'list',
    // Exercise the deployed bundle; PDF.js cannot evaluate in Next 15's
    // Webpack development eval wrapper. Keep interaction failures bounded.
    timeout: 120_000,
    expect: { timeout: 12_000 },
    outputDir: 'test-results/quality',

    use: {
        baseURL: `http://localhost:${PORT}`,
        actionTimeout: 12_000,
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
        command: `node scripts/playwright-server.mjs --port ${PORT} --mode production`,
        url: `http://localhost:${PORT}`,
        reuseExistingServer,
        timeout: 1_800_000,
        gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
        env: {
            // Keep unmocked sockets away from the Next HTTP port; quality
            // cases that need a live backend opt in explicitly.
            NEXT_PUBLIC_WS_URL: `ws://127.0.0.1:${PORT + 1000}`,
            DATABASE_URL:
                process.env.PLAYWRIGHT_DATABASE_URL
                ?? 'postgresql://latexy:latexy_password@127.0.0.1:5434/latexy_test',
            BETTER_AUTH_SECRET:
                process.env.PLAYWRIGHT_BETTER_AUTH_SECRET
                ?? 'playwright-local-secret-with-at-least-32-characters',
        },
    },
})
