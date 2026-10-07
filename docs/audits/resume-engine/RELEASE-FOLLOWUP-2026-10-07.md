# Resume engine release follow-up — October 7, 2026

The owner authorized continuing draft #1833 after its checkpoint pause. This
follow-up preserves the historical handoff rather than rewriting its results.
Draft #1834 is being completed separately; neither draft is release-certified.

## Integration and schema

- [x] Reconcile current main `5e42d42f` using three-way integration; preserve
  Google OAuth, mobile logout, private validation bounds and CI cancellation.
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
- [x] Expanded suite: eleven cases passed, including cross-owner adaptation,
  discard and saved-attachment refusal; expired-original refusal; hash-tamper
  refusal; exact-byte retention and idempotent adaptation. Changed files pass
  Ruff. An actual Ghostscript-encrypted fixture is now rejected and the ordinary
  fixture remains accepted. Repair commits `21688c57` and `c6f9b01f`.
- [ ] Production import/adaptation and retention acceptance, supported-template
  visual review and complete source/field/structure concurrency checks.

## Performance and deployment gates

- [ ] Fix and measure renderer module-load serialization after artifact arrival.
- [ ] Reproduce the previously observed 20–30 second pre-delivery delay with
  current isolated services, separating admission, queue, worker, storage and
  browser paint. Old contended samples are not current performance proof.
- [ ] Controlled fresh/cache distributions and production action-to-paint.
- [ ] Resolve template-font and test-package CI failures without weakening guards.
- [ ] Independent review, protected checks, production rollout and live QA.

The one-second fresh PDF and 500-ms cached-paint targets remain uncertified.
Broad Modal Lua capability stays closed. No paid model test, live billing charge,
production schema change, draft merge or engine-epic closure is claimed here.
