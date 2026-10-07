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
- [ ] Fix and measure renderer module-load serialization after artifact arrival.
- [ ] Reproduce the previously observed 20–30 second pre-delivery delay with
  current isolated services, separating admission, queue, worker, storage and
  browser paint. Old contended samples are not current performance proof.
- [ ] Controlled fresh/cache distributions and production action-to-paint.
- [ ] Resolve template-font and test-package CI failures without weakening guards.
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
- A fresh full run at `a67647b9` / backend tree `76e2953b` is pending. An earlier
  rerun used the wrong Redis environment variable names and was interrupted;
  only the rerun with `TEST_REDIS_URL` / `TEST_REDIS_CACHE_URL` pointing at the
  isolated QA Redis instance is eligible for acceptance.
- Template CI now installs `fonts-texgyre`, matching the shipped EuropeCV face;
  the complete 92-case deployment-manifest guard suite passes. Actual Linux
  template compile acceptance still requires fresh protected CI.
- Native macOS does not certify Linux Lua confinement or Windows file-system
  guards. Real object-storage and browser acceptance remain separate gates.

The one-second fresh PDF and 500-ms cached-paint targets remain uncertified.
Broad Modal Lua capability stays closed. No paid model test, live billing charge,
production schema change, draft merge or engine-epic closure is claimed here.
