# Resume engine release follow-up — October 7, 2026

The owner authorized continuing draft #1833 after its checkpoint pause. This
follow-up preserves the historical handoff rather than rewriting its results.
Draft #1834 is being completed separately; neither draft is release-certified.

## Integration and schema

- [x] Reconcile current main `5e42d42f` using three-way integration; preserve
  Google OAuth, mobile logout, private validation bounds and CI cancellation.
- [x] Preserve subsequently accepted main `b5e2735a` action pins. PR #1840
  completed protected CI, Modal rollout and Vercel production certification;
  production identity matched that commit and backend readiness was healthy.
- [x] The independently reviewable quota-log repair was accepted on main in
  PR #1844, preserving limited/unlimited policy. Main `0d628cba` passed CI,
  automatic Modal deployment and Vercel production certification; direct live
  identity matched that commit and backend DB/Redis/cache/storage were healthy.
- [x] Keep deployed OAuth revision `0059`; engine `0060` now descends from it.
- [x] Real isolated PostgreSQL: fresh initial schema through `0064`, upgrade
  from deployed-main `0059` through `0064`, and engine rollback to `0059` then
  upgrade through `0064` all succeeded. Both fresh and upgraded schemas retain
  `verification.value` as `TEXT NOT NULL`. Empty QA schema rollback is not a
  populated production-data rollback certificate.
- [ ] Combine and verify billing revisions `0065`–`0067` after engine `0064`.
- [ ] Freeze and pass complete backend, frontend and protected GitHub checks.

## Original PDF privacy and validation

- [x] Previously unrun original-PDF suite: five cases passed on real isolated
  PostgreSQL and Redis before follow-up changes.
- [x] Reproduce [#1841](https://github.com/sanskarpan/Latexy/issues/1841): an
  actual encrypted PDF with an empty user password was accepted. A deterministic
  negative regression failed before the repair.
- [x] Reject readable encrypted originals; reject oversized bytes before parsing;
  stop page validation at page 51. Validation uses PDFMiner directly because
  PDFPlumber cleanup materializes its entire page list even after rejection.
  This bounds yielded pages, not internal page-tree traversal, parser memory or
  CPU time; those remain separate hardening considerations.
- [x] Expanded suite: eleven cases passed, including cross-owner adaptation,
  discard and saved-attachment refusal; expired-original refusal; hash-tamper
  refusal; exact-byte retention and idempotent adaptation. Changed files pass
  Ruff. An actual Ghostscript-encrypted fixture is now rejected and the ordinary
  fixture remains accepted. Repair commits `21688c57` and `c6f9b01f`.
- [ ] Production import/adaptation and retention acceptance, supported-template
  visual review and complete source/field/structure concurrency checks.

## Performance and deployment gates

- [x] Restore five-second typing quiet time and a ten-second minimum automatic
  admission interval in the draft scheduler. Explicitly saved field/structure
  and review decisions remain prompt but share the single-running-preview
  fence and backend quotas. Scheduler and existing auto-compile tests: 21 passed.
- [x] Preload and share the browser-only renderer promise before artifacts arrive;
  retry rejected chunk loads. Actual production Chromium test passed and proved
  the PDF.js bundle loaded before preview admission. This proves ordering, not a
  measured speedup or an end-to-end latency target.
- [x] Correct the full-stack smoke to select Source before expecting Monaco;
  verify initial Resume mode keeps Monaco unloaded. The local real-backend
  Chromium smoke passed 1/1 in 5.5 seconds. This is route/editor interaction
  proof, not live OAuth, semantic optimization or compile-latency acceptance.
- [x] Explicitly install `fonts-texgyre` in the shared Modal TeX image and both
  Docker renderer images. A new static regression failed before the repair;
  all 121 deployment/parity guards passed afterward. CI-only installation would
  not have fixed deployment images. Fresh image build/compile remains required.
- [ ] Reproduce the previously observed 20–30 second pre-delivery delay with
  current isolated services, separating admission, queue, worker, storage and
  browser paint. Old contended samples are not current performance proof.
- [ ] Controlled fresh/cache distributions and production action-to-paint.
- [x] Resolve template-font and test-package CI failures without weakening guards;
  fresh Linux template extraction and backend CI passed at `66a76a0c`.
- [ ] Independent review, protected checks, production rollout and live QA.

## Current reproducibility checks

- Complete backend collection now succeeds with consistent package-relative
  test imports. The first attempted repair exposed seven legacy import errors;
  that failed run was retained, not presented as acceptance.
- Full backend run at `34a29f23` / backend tree `a634831f` produced 4,714 passed,
  16 failed, 13 skipped and eight errors. Acceptance/skill fixture shape,
  host-dependent renderer selection and an undeclared `pdftotext` test dependency
  were investigated and repaired without dropping security assertions. The five
  renderer fixture files independently passed all 57 cases.
- A fresh full run with backend tree `76e2953b` produced 4,735 passed, three failed,
  13 skipped and one existing deprecation warning in 1,077 seconds. The streaming
  response, incremental semantic patch and pre-header provider watchdog checks
  all passed a serial rerun in 17 seconds without changing assertions/deadlines.
  The contended full-suite failure is not waived or reported as a green suite.
  An earlier
  rerun used the wrong Redis environment variable names and was interrupted;
  only the rerun with `TEST_REDIS_URL` / `TEST_REDIS_CACHE_URL` pointing at the
  isolated QA Redis instance is eligible for acceptance.
- A subsequent frozen full run at `0f75149c`, backend tree `02f3edd1`, passed
  **4,760 tests with 13 skips**, zero errors/failures and one existing warning
  in 388.50 seconds. JUnit independently records 4,773 tests, 13 skips and zero
  failures/errors. This includes the initial keyed credential-scope repair,
  but not the later private-stage-context follow-up. No production credentials,
  provider calls or skipped infrastructure checks were used for this result.
- Template CI now installs `fonts-texgyre`, matching the shipped EuropeCV face;
  the complete 92-case deployment-manifest guard suite passes. GitHub run
  `37659795432` at `66a76a0c` subsequently passed the actual Linux template PDF
  extraction contract and Backend Tests. Full-stack smoke failed in that run;
  investigation and cross-browser results remain separate gates.
- Native macOS does not certify Linux Lua confinement or Windows file-system
  guards. Real object-storage and browser acceptance remain separate gates.
- Frontend tree `0a8340cf` passed 1,093 unit tests, typecheck, full lint, a fresh
  production build and one production-bundle Chromium field/preview contract.
  This is not complete cross-browser or production semantic-edit acceptance.
- New Linux QA image build was stopped before exhausting this Mac's disk
  (three GiB free during the attempt); Homebrew Poppler installation also failed
  in Homebrew's Ruby JSON initialization. Existing unrelated images/worktrees
  were preserved. An exact kernel-only probe in the existing ARM64 TeX image
  found Landlock syscall 444 unavailable (`ENOSYS`) under unchanged Docker
  protections, so no Linux confinement denial certificate was established.

## Modal default-renderer blockers

New managed resumes, template uses and PDF adaptations persist LuaLaTeX by
default. Its Modal capability remains closed until the intended pinned image
and assets pass actual multilingual, isolation and default-flow acceptance.

- The first operator attempt lacked the optional Modal SDK in the backend venv;
  it did not create a VM. The installed CLI environment has pinned SDK 1.5.4.
- Actual bounded cached-image probing retained the CJK error: the harness reused
  Hindi's `resume.aux` in an unrelated Japanese fixture and accepted a stale
  `resume.pdf` presence. Per-case job names now isolate outputs, with six offline
  regression cases passing; no security probes were removed.
- A tighter actual Python 3.12 / Modal 1.5.4 / PDFMiner 20260107 probe observed no
  renderer fingerprint in cached image `im-1fho7eMXjj9Z60ziS7Kf6J`. Latin and all
  three hostile probes passed. Hindi compiled with exit zero but extracted as
  `\ufffdहंदी`, not `हिंदी`; bundled pypdf independently corroborated that result.
  The run stopped at this extraction check; CJK was not recertified by this
  tightened pass. No production safety gate was opened.
- Correction after independent PDF inspection: the Hindi PDF contains the
  original characters in a marked-content `/ActualText` span. Its rendered
  page is correct and actual Poppler 22.12.0 `pdftotext` extracts exactly
  `हिंदी`. PDFMiner and pypdf do not use that span here; their agreement was
  not independent proof of corrupted PDF generation. The certification must
  use the production-primary Poppler parser, retaining exact Unicode and
  missing-glyph checks. PDF.js text extraction also omitted the span in a
  diagnostic; browser selection/search interoperability remains a separate
  item to verify, not a demonstrated compiler defect.
- The Poppler diagnostic used a small Debian QA image, no network during
  inspection, a read-only fixture mount and unchanged Docker protections.
  This is parser evidence, not a certified production renderer image or a
  browser latency measurement. The cached Modal image's missing immutable
  asset fingerprint remains a genuine release blocker regardless of the
  Hindi parser correction.
- The corrected Poppler certifier passed eleven offline regressions and an
  actual read-only Poppler verification of the retained Hindi PDF. Extraction
  has byte/time limits and strict UTF-8/exit-code checks; missing Poppler fails
  before VM creation. Fingerprint discovery is explicitly not a comparison
  against an independently configured expected production pin.

## Security and combined-release review

- Fresh CodeQL at `66a76a0c` reported seven findings: three unkeyed credential
  scopes, quota logging and three generated-code test fixtures. Tracked in
  [#1843](https://github.com/sanskarpan/Latexy/issues/1843); no dismissal or check
  override was used. These scopes are not password verifiers, but unkeyed
  fingerprints permit offline credential candidate confirmation/correlation.
  The initial keyed scope repair passed 79 focused helper/ledger/checkpoint/
  fairness tests and the frozen full suite. Its fresh scan cleared the log and
  generated-test-code findings but still reported two hashing findings. One
  follows the SHA-256 primitive inside a keyed HMAC; the other follows the
  generic stage-context checksum. Neither was dismissed or suppressed; narrow
  follow-up and a fresh scan remain required before security acceptance.
- Quota outage logs now omit owner identifiers and preserve the existing
  unlimited-plan fail-open versus limited-plan fail-closed policy. All 40 quota
  tests passed, including two new privacy/injection regressions.
- Lifecycle fixture child programs now receive paths/modules through argv,
  not interpolated executable code. All eight focused Node 22 tests and lint
  passed; a fresh CodeQL scan must confirm those findings are cleared.
- A no-checkout merge-tree check of engine `8763acb4` and billing `9a5d4a09`
  found ten conflicted files: migration `0060`, route registration, Playwright
  server, four frontend contract tests, landing page, trial editor and workspace
  editor. Other shared files auto-merged, which is not semantic verification.
  Neither worktree nor draft was overwritten; combined release verification is
  still required. Each candidate passing alone is not combined acceptance.

Raw diagnostic logs and fabricated PDF scratch files remain local, not committed.
Full-run log SHA-256: `cac560cdfe7a363b74322631b7c75472facbf5b30c3e0190a77cf6559dbf40c9`.
Successful frozen follow-up full-run log SHA-256:
`8306f03604470889572e058b5425948c4fd69c280d34747f82445ed73742f96b`.

The one-second fresh PDF and 500-ms cached-paint targets remain uncertified.
Broad Modal Lua capability stays closed. No paid model test, live billing charge,
production schema change, draft merge or engine-epic closure is claimed here.
