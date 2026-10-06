import { defineConfig, devices } from '@playwright/test'

// Latexy2 dev server uses slot 2 (port 5181) when slot 1 is taken by Latexy.
// Override with PLAYWRIGHT_PORT env var if needed.
const PORT = parseInt(process.env.PLAYWRIGHT_PORT ?? '5181')
const auditMode = process.env.PLAYWRIGHT_AUDIT === '1'
const reuseExistingServer = process.env.PLAYWRIGHT_REUSE_EXISTING_SERVER === '1'
const serverMode = process.env.PLAYWRIGHT_SERVER_MODE === 'production' ? 'production' : 'development'
const serverTimeout = serverMode === 'production' ? 1_800_000 : 900_000
// Once a production bundle is available, a route should never need the
// multi-minute Webpack cold-compile allowance used by development mode. Keep
// a bounded per-test budget so a genuinely hung `next start` fails promptly;
// the larger serverTimeout above is reserved for the one-time build.
const testTimeout = serverMode === 'production' ? 120_000 : 900_000
const navigationTimeout = serverMode === 'production' ? 60_000 : 900_000
const editorWarmupPath = '/workspace/ffffffff-ffff-ffff-ffff-ffffffffffff/edit'
const websocketUrl = process.env.PLAYWRIGHT_REQUIRE_BACKEND
    ? (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8030')
    // Unmocked sockets should fail closed on an unused port. Pointing them at
    // the Next server makes its HTTP handler receive WebSocket upgrades and
    // emit internal `originalResponse.bind` errors; routeWebSocket mocks still
    // intercept the /ws/jobs URL before any network connection is attempted.
    : `ws://127.0.0.1:${PORT + 1000}`

export default defineConfig({
    testDir: './e2e',
    // Audit specs intentionally hit live services and require the documented
    // audit user fixture. Keep them out of the mocked suite, but provide a real
    // opt-in path; an unconditional ignore also ignored explicitly named files.
    testIgnore: auditMode ? [] : ['**/audit-*.spec.ts'],
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 1 : 1,
    // The editor route has a large module graph; one worker keeps the
    // disposable webpack server deterministic and bounded on local machines.
    workers: 1,
    reporter: 'html',
    // A cold webpack route compile can take several minutes for editor-heavy
    // pages. Keep assertion waits
    // narrow below, but allow navigation/setup to cover that cold-start cost.
    // Non-editor pages can still trigger a cold webpack compilation after the
    // disposable server is ready. Keep assertions fast while giving the test
    // body enough budget to finish that one-time compilation.
    timeout: testTimeout,
    expect: { timeout: 12_000 },

    use: {
        baseURL: `http://localhost:${PORT}`,
        // Keep interaction failures fast while allowing cold webpack navigations
        // to use the same long budget as the editor/webServer startup.
        actionTimeout: 12_000,
        navigationTimeout,
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
        // Start from an ignored disposable copy so Next cannot rewrite the
        // shared checkout's tsconfig/next-env or generated .next tree.
        command: `node scripts/playwright-server.mjs --port ${PORT} --mode ${serverMode}`,
        // Readiness also warms the editor bundle. On a clean checkout this is
        // the largest webpack route and can take materially longer than the
        // root page, which otherwise charges cold compilation to the first test.
        url: `http://localhost:${PORT}${editorWarmupPath}`,
        reuseExistingServer,
        timeout: serverTimeout,
        // Let playwright-server remove its disposable tree before Playwright
        // falls back to force-killing the process group.
        gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
        // Mocked suites point WebSockets here for routeWebSocket() interception. The
        // full-stack smoke opts into the real backend WebSocket URL instead.
        env: {
            NEXT_PUBLIC_WS_URL: websocketUrl,
            // Never inherit a production database from .env during browser
            // tests. A few auth-route assertions intentionally reach the real
            // Next handler, so isolate their rate-limit writes in the migrated
            // test database instead of contacting Supabase.
            DATABASE_URL: process.env.PLAYWRIGHT_DATABASE_URL
                ?? 'postgresql://latexy:latexy_password@127.0.0.1:5434/latexy_test',
            BETTER_AUTH_SECRET: process.env.PLAYWRIGHT_BETTER_AUTH_SECRET
                ?? 'playwright-local-secret-with-at-least-32-characters',
        },
    },
})
