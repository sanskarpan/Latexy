# Frontend capability controls: validation

## Implemented

- Searchable capability inventory, category/control-type filters, descriptions, immutable reasons and parent relationships.
- Family defaults and individual-plan restrictions with inherited effective-off explanations. Missing values are displayed as disabled.
- Per-cell immediate write locks and cell-local optimistic updates/rollback; unrelated in-flight responses cannot replace the whole matrix.
- Anonymous and authenticated effective-map loading, identity epochs including A→B→A transitions, stale-response suppression, fail-closed unknown/error/loading states, explicit recovery allowlist, retry notice, and foreground refresh every 30 seconds.
- Optional tool mount boundaries, direct optional-route boundaries, editor commands/completions/keyboard adapters, auto-compile scheduling, PDF inspection/SyncTeX, source/visual mode, utility panels, import sources, structured interchange and extended exports.
- Retained builder drafts stay mounted during refresh/revocation. Owner/document-scoped application state can be downloaded locally as JSON, unsaved navigation shows a warning, and builder autosave pauses while unavailable.
- BYOK/developer key creation, OAuth connect/sync (including an already-open confirmation), share creation/privacy/review enable, and tracker mutations have disabled controls, explanations, and handler guards. Whole-link revocation, disconnect, deletion, alert pause, data reads, calendar export and copying remain available.
- Browser extension checks a fresh authenticated effective capability before extraction, capture, autofill and handoff. No additional host permissions. Clearing saved local profile/capture data remains available.
- `frontend/src/lib/capability-ui-policy.ts` maps explicit client enforcement points to source files. Backend wiring tests combine this map with server admission checks for full catalog accounting.

## Passed locally

Node 22.23.2, pinned dependency installation:

- Full TypeScript check (`tsc --noEmit`): passed
- Full frontend ESLint (`eslint . --max-warnings=0`): passed
- Full frontend Vitest: 179 files, 1,242 tests passed
- Focused policy/context tests: 19 passed
- Draft recovery/action-button tests: 7 passed; OAuth/sync control tests: 15 passed; focused tracker suite: 70 passed
- Browser-extension Node tests: 8 passed
- Extension JavaScript syntax and package/host-scope validation: passed

The frontend totals include the final capability-control edits and the independent plan-catalog quota tests.

A redundant full-suite rerun during concurrent build/backend work encountered worker-start timeouts and 5-second test timeouts, followed by mock-cleanup cascades (177 files completed instead of 179). The preceding full run passed all 1,242 tests; the only intervening code change replaced the confirmation dialog's accessibility-description attribute with `aria-describedby`. Final TypeScript and full ESLint checks passed after that correction. The final two-worker rerun (`vitest run --maxWorkers=2`) passed all 179 files / 1,242 tests after the accessibility correction, with unchanged test limits. The final serial production build also passed, including standalone artifacts. An earlier concurrent build exited 137 under memory pressure; the serial retry resolved it.

## Browser acceptance status

`frontend/e2e/capability-controls.spec.ts` defines API-mocked inventory and editor acceptance checks. These checks did **not** execute: system Chromium terminated during process startup with `process_singleton_posix.cc: socket() failed: Operation not permitted`. The permitted escalation retry had the same infrastructure failure. No screenshots were produced and no visual pass is claimed. Next.js did start with the test runner's explicit loopback hostname; network-restricted Google Fonts used fallback fonts during startup.

To run where Chromium is supported:

```
cd frontend
pnpm exec playwright test --config=playwright.capabilities.config.ts
```

Optionally set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to an installed Chromium. All business APIs in these scenarios are mocked; they do not invoke model, payment, email, compile or OAuth providers.

## Deliberate boundaries

Existing-data views, source recovery, manual compilation, PDF/source downloads, security settings, revocation/deletion and existing billing management remain reachable. Disabling review access alone still follows the backend sharing-update policy; when updates are unavailable, the modal explains that revoking the existing link removes all public access. UI restrictions supplement authoritative server admission; client code alone is not a security boundary.
