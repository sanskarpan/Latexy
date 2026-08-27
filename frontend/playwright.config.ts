import { defineConfig, devices } from '@playwright/test'

// Latexy2 dev server uses slot 2 (port 5181) when slot 1 is taken by Latexy.
// Override with PLAYWRIGHT_PORT env var if needed.
const PORT = parseInt(process.env.PLAYWRIGHT_PORT ?? '5181')
const websocketUrl = process.env.PLAYWRIGHT_REQUIRE_BACKEND
    ? (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8030')
    : `ws://localhost:${PORT}`

export default defineConfig({
    testDir: './e2e',
    // The audit specs intentionally hit live services, write artifacts under
    // /tmp, and require the documented audit user fixture. Run them explicitly;
    // they are not deterministic members of the mocked regression suite.
    testIgnore: ['**/audit-*.spec.ts'],
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
        // Mocked suites point WebSockets here for routeWebSocket() interception. The
        // full-stack smoke opts into the real backend WebSocket URL instead.
        env: {
            NEXT_PUBLIC_WS_URL: websocketUrl,
        },
    },
})
