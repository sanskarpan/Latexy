# Local production PWA acceptance

This suite supplements the HTTP-mocked quality project, which blocks service
workers. It runs Chromium with workers allowed and a disposable production Next
bundle. It preserves the existing offline PDF, logout, and account-switch specs;
those account/API responses remain synthetic fixtures, not real authentication
or deployed-backend acceptance.

From `frontend/`, using Node 22 and the frozen workspace dependencies:

```sh
pnpm exec playwright install chromium
node --test scripts/pwa-acceptance.test.mjs
node scripts/pwa-acceptance.mjs
```

The runner removes an old JSON report before starting and requires exactly 12
named cases passed, zero failures, skips or flaky retries, and the dedicated
`chromium-pwa` project. Running Playwright directly is useful for diagnosis but
does not run this fail-closed evidence check.

The server starts on loopback port 5193 by default. Set `PLAYWRIGHT_PWA_PORT` to
another unused local port if required. To reuse an already running **matching
production test build** rather than build again:

```sh
PWA_ACCEPTANCE_UPSTREAM_URL=http://127.0.0.1:5182/ node scripts/pwa-acceptance.mjs
```

Only an explicit loopback HTTP upstream is accepted. The fixture proxy forwards
normal UI/static requests unchanged. The first `/sw.js` version is byte-identical
to the generated worker. On update, it appends a harmless version comment so
Chromium performs an actual install/activate update. It records the original and
derived SHA-256 values and never rewrites
the build artifact. This is a controlled worker-update check, not a claim that
two independently built releases were rolled out.

A separate test fetches synthetic private API/PDF responses for two fixture
owners, checks unsigned denial and Cache Storage exclusion, and refuses offline
replay. These endpoints exist only in the local test proxy. They test active
worker caching behavior, not backend owner authorization.

Artifacts are under `test-results/pwa/`: `report.json`, failure traces/screenshots,
and the worker-identity/cache assertion attachments. CI should retain these
alongside its source revision and run the explicit runner, rather than count an
opt-in suite selected without `PWA_PRODUCTION` as successful coverage. Physical
installation, mobile-device behavior and production acceptance remain separate.
