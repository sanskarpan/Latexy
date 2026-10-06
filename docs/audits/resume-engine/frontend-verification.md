# Frontend engine verification

The implementation uses an immutable PDF artifact as the preview, then enables field overlays only when document identity, content revision, source hash, PDF hash, node revision, exact text and source span all match. Rotated pages, ambiguous mappings and opaque custom source remain read-only on the PDF; supported plain fields and advanced Source mode remain available.

The preview scheduler holds one admitted/running job and one replaceable latest source. Its adaptive debounce is 150–250 ms. Backend quota enforcement remains authoritative. A failed or ambiguous admission is not automatically repeated for unchanged source. Explicit accepted/rejected AI decisions rebuild the authoritative draft, including reject-all where the draft text is unchanged.

Managed documents use the persistent semantic run API with Quick, Standard and Deep effort. Provisional suggestions are informational. Decisions require the backend's terminal acceptance-ready receipt. Imported templates use a separate plain-language whole-document review; their custom layout is preserved. Candidate artifacts cannot be exported as accepted drafts. No paid model invocation was used for this verification.

## Reproduce

Run from the worktree root with its independent dependencies installed using `pnpm install --frozen-lockfile --ignore-scripts`, then run the frontend's `prepare:monaco` command.

```powershell
pnpm --filter Latexy-frontend typecheck
pnpm --filter Latexy-frontend exec vitest run src/__tests__/preview-scheduler.test.ts src/__tests__/artifact-geometry.test.ts src/__tests__/artifact-policy.test.ts src/__tests__/semantic-review-events.test.ts src/__tests__/job-stream-reducer.test.ts src/__tests__/job-stream-retrying.test.ts
```

The focused engine unit suite passed 51 tests. Full frontend ESLint passed. The initial full unit run passed 1,010 tests and found three mode-label source-contract expectations, five unchanged HEAD source-contract failures, and one Windows Vitest launcher import failure; the mode expectations were updated to preserve their accessibility and panel assertions. Final checks are recorded below. All three browser contracts passed without retries (57.8 seconds). The managed contract covers effort/source/revision admission, provisional and final patch reconciliation, candidate export refusal, reject/accept decisions, accepted revision rendering/export, and stale field conflict preservation. Browser contract coverage is in `frontend/e2e/quality/resume-engine-preview.spec.ts`: plain guest editing, revision CAS, exactly one admission, lazy Source mode and imperative copy, actual PDF rendering, fingerprint-bound geometry, keyboard selection and mobile field navigation. It can use installed Chrome through `ENGINE_QA_CHROME=1`.

The real browser probe is `frontend/scripts/benchmark-preview-browser.mjs`. It uses a fresh normal guest device and the three real trial admissions, against explicitly isolated local services at port 8530 and frontend port 5361. It records user-action-to-first-paint and verified-blob-to-paint separately, along with HTTP status and fingerprint comparison booleans. It never records device fingerprint values or resume source. The JSON records failures as well as successful samples; three samples do not establish production percentiles.

The frontend's declared development command uses Turbopack. Starting this Next version manually without `--turbopack` reproduces the upstream PDF.js/Webpack eval issue before PDF loading ([React-PDF issue 2031](https://github.com/wojtekmaj/react-pdf/issues/2031), [Next issue 89177](https://github.com/vercel/next.js/issues/89177)). The isolated browser server was corrected to use the declared development bundler. A previous-service diagnostic is preserved separately and does not represent final latency.

## Real browser observations

Functional probes used two independent normal guest contexts with real backend services. The first context produced an initial PDF in 2,331 ms, then an identical-input preview in 30,205 ms after respecting the existing five-minute trial cooldown. A separate ordinary first-use context saved a field before its first compile and painted the changed PDF in 29,259 ms. These uncontrolled local observations are not performance percentiles. Root backend trace confirms the identical input was a cache hit with zero TeX work; its delay occurred before artifact delivery, not PDF rendering. The field-edit WebSocket observed roughly 20.6 seconds between job start and artifact readiness. Verified-blob-to-paint was 654–1,602 ms.

The final field-edit probe received HTTP 200 for PDF, geometry and SyncTeX; all fingerprint comparison booleans matched the admission, with seven editable boxes and two conservative omissions. Actual keyboard selection and a 390-pixel mobile PDF-to-field selection succeeded. Resume mode did not mount Monaco; Source mode loaded it on demand. No final browser exceptions were recorded. Evidence: `preview-browser-two-samples.json`, `preview-browser-benchmark.json`, `guest-real-pdf-preview.png`, and `guest-real-pdf-mobile-fields.png`. Earlier pre-restart diagnostics remain explicitly separate because they exposed backend guest finalization and development bundler defects that were subsequently corrected.

An independent post-test review added post-await source guards to PDF download and Web Share, so a newer edit cannot silently export a response fetched for an older source. Artifact download completion and errors are also account/job/artifact fenced.


## Final post-rebase production verification — 2026-10-07

The reviewed snapshot passed all 1,054 frontend unit tests, full ESLint with zero warnings, and TypeScript checking in an independent Linux dependency volume using the canonical pnpm 10.10.0 frozen lockfile. The complete production build passed, generated all 40 static pages, assembled the standalone runtime, and passed the repository build-artifact validator. No Windows dependency junction, main checkout dependencies, ambient production credentials, or actual database connection was used. The build used an inert HTTPS authentication URL and an unused dummy database port.

Three Chromium browser contracts then passed against that actual Linux standalone production bundle, with zero retries (43.8 seconds): guest plain-field editing and a single quota-governed preview (10.8 seconds), managed provisional/final suggestion review and authoritative decisions (15.5 seconds), and exact-PDF keyboard/mobile field selection (5.5 seconds). These tests render real valid PDF bytes while mocking authenticated/API/stream contracts; they do not invoke paid AI services. The managed case also checks unavailable limited PDF checks remain informational and that missing job requirements show their frozen source excerpts rather than internal IDs. This verifies the production PDF.js bundle as well as the development path.

Post-rebase guard failures were verified as cross-platform test fixture issues: source assertions normalize CRLF, the SyncTeX page-mutation fixture matches either newline style, and environment assertions account for Windows case-insensitive aliases while retaining POSIX exact-key assertions and every credential-exclusion check. The parent-monitor fixture signals readiness before terminating its launcher and uses an independent Windows descendant to exercise cleanup. No guard assertion or timeout was removed. Linux snapshot test dependencies include the source-only authentication migration and canonical privacy policy.

The earlier three real guest probes remain functional evidence under CPU contention; these production browser contracts are mocked correctness checks and do not establish deployment latency percentiles.
