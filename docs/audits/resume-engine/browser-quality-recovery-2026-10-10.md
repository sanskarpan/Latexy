# Browser quality recovery, 2026-10-10

## What was actually failing

Historical head `fed556813b68a999e03813bf2ecdf170259ba834` completed [CI run 37829214371](https://github.com/sanskarpan/Latexy/actions/runs/37829214371) with **43 failed, 44 passed, 3 skipped** browser cases in 1.8 hours. Its previously recorded “still installing browsers” status was only an interim observation. The cadence and hydration steps were skipped after the quality step failed.

The frontend was unchanged by the subsequent backend-instrumentation commits through `7ab3cc0dbc12a2d554d48e645d5aaf7d76baaac2`. These failures must not be attributed to that instrumentation or reported as a browser pass.

Evidence: GitHub artifact `11580060459`, `playwright-quality-report`, SHA-256 `9bc3a242651d41e238bd2ae9257342fff34fb0d46403f056c5923e60048d38c9`. The archive includes the HTML report, error contexts, screenshots, and retry traces under `test-results/quality/`. Three separate causes were confirmed:

1. **PDF.js module evaluation, before rendering.** Import review, mapped-PDF keyboard selection, and structure-editing Chromium retry traces show `Object.defineProperty called on non-object`, through `__webpack_require__.r`, `pdfjs-dist/build/pdf.mjs`, and `ReactPdfClient.tsx`. WebKit reports the equivalent object-definition error. No PDF worker request occurs. The Next development error boundary then replaces the editor, explaining both missing canvases and long control-locator timeouts. The installed Next 15.5.27 bundles Webpack 5.98.0; this matches the [upstream development-eval runtime collision](https://github.com/webpack/webpack/issues/20095). The existing `frontend-verification.md` had recorded the problem, but its claimed development-launcher correction was absent from the tracked launcher.
2. **Unsupported browser fixture assumptions.** Firefox/WebKit reject the Chromium clipboard permission names. WebKit's intercepted multipart request exposes framing without the file bytes: its import handler assertion throws before returning the mocked receipt. See the [Playwright multipart interception limitation](https://github.com/microsoft/playwright/issues/6479).
3. **Stale API/UI fixtures.** Hardcoded API ports 8030/8530 do not match the quality launcher's isolated backend port 7182. This lets template requests escape the held-request test and produces unmocked WebKit API errors. The public mobile test also expects the old `Recompile` label while Resume mode now exposes `Update PDF`. A mobile cancellation test needs to select the PDF pane to reach its Stop control, then return to the Editor pane.

## Scoped repairs

- Run quality tests through the existing isolated **production** launcher, keeping the shared launcher and product rendering code unchanged. This tests the deployed bundling behavior rather than the broken development-eval wrapper. Give the one-time build the same 30-minute budget as the existing production harness, while bounding individual interactions at 12 seconds.
- Mock ancillary API paths independently of the chosen local port, preserving document/RSC navigation and all engine-specific request handlers. Add unit checks for multiple ports, navigation pass-through, and source-bound public projections.
- Preserve the real canvas, field-overlay, exact-source, revision, authentication, receipt-integrity, and request-count assertions.
- Capture the Copy button's actual `clipboard.writeText` argument across engines. Inspect the existing Monaco test hook for the newer-source race, rather than depending on OS clipboard permissions.
- Observe the actual FormData File bytes supplied to fetch and then call the original fetch. Continue checking upload authorization and multipart metadata. No browser is skipped to avoid the WebKit limitation.

## Validation and limits

- Targeted launcher/fixture unit tests: **16 passed**.
- Changed-file ESLint, full TypeScript check, and `git diff --check` passed before publication.
- Local browser execution did **not** reach test assertions: Chromium's process-singleton socket failed with `Operation not permitted`, including an approved escalated retry. This environment failure is not a product failure or a browser pass. No security settings were changed.
- Exact published-head Linux browser CI remains the acceptance authority for these repairs. Record its terminal result in the PR before marking the gate complete.
- All browser APIs, auth, PDFs, and engine responses in these contracts are synthetic fixtures. They do not measure production queueing, cold starts, provider execution, storage latency, or real action-to-PDF paint. The production latency acceptance plan in `latency-instrumentation-2026-10-10.md` remains open.
