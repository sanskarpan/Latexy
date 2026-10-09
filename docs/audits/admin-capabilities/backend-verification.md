# Backend capability verification

## Result and scope

Final full regression: **4,649 passed, 12 failed, 4 skipped**. All remaining failures reproduce on clean main and concern this host’s TeX setup; no capability, quota, migration, accounting or generated-matrix test failed. See [acceptance](acceptance.md) and [exact environment comparison](environment-comparison.json).

- All 129 audited inventory IDs have an enforcement/baseline entry in `feature-matrix.json`: 107 gateable and 22 deliberate baselines.
- The matrix distinguishes 90 capabilities with automated backend policy evidence, 17 client-control capabilities without exhaustive per-capability behavior tests, and 22 always-on baselines. It does not claim 129 manually tested workflows.
- Current 20-file focused regression bundle: **548 passed; 1 generated-artifact freshness mismatch**. The mismatch was concurrent addition of B08 builder UI controls, not runtime behavior. The matrix was regenerated and its freshness test then passed separately.
- Earlier overlapping bundles: 299 core policy/admission/collaboration tests passed; 287 policy/template/builder/import/variant tests passed; 161 apply/collaboration/chat/email-status/outreach/analytics tests passed. These counts overlap and must not be summed.
- Python lint and `git diff --check` passed for the changed backend implementation, tests and generator.

A follow-up 56-test policy bundle passed after publication, adding explicit real-database `0060` seed preservation and round-trip coverage. This is additional test-only evidence; application code is unchanged.

## What the tests establish

- Real registered ASGI routes deny each declared static capability before handler database work, including existing builder updates, provider sync, snippet install/upvote and developer API dispatch.
- Dynamic policies cover anonymous alternate entry points, optimization/combined/ATS/auto-fit jobs, raw/saved exports, sharing modes, selected industry profiles and cleanup-safe changes.
- Existing provider keys cannot be decrypted when BYOK is disabled, and the denial cannot silently become a platform-funded fallback.
- A public review resolves the owner's grant. Disabled public sharing cannot issue another storage URL. Owned source remains readable, including after builder/sharing disablement.
- An already connected collaborator is closed before a post-disable frame is processed. Document ACL and viewer/editor protocol tests still apply.
- A real isolated PostgreSQL/Redis test admits and charges a job, disables optimization before worker start, denies a subsequent admission without charging, runs the admitted job to a controlled provider-configuration failure, refunds once, survives redelivery without a second refund, and preserves owned result/status access.
- Four industry-profile admission tests verify server-owned generic-only selection, overwriting client-supplied metadata, generic fallback, and preservation of the captured decision across a queue delay.

## Commands

Run the following with the repository's isolated test database and Redis configuration. This verification used local PostgreSQL 17 and Redis 8, with live OpenAI/email keys disabled. No production or provider mutation was performed.

```sh
.venv/bin/pytest \
  backend/test/test_capability_route_policy.py \
  backend/test/test_capability_job_admission.py \
  backend/test/test_capability_matrix.py \
  backend/test/test_entitlement_wiring.py \
  backend/test/test_entitlement_enforcement.py \
  backend/test/test_ats_capability_admission.py \
  backend/test/test_ats_routes.py \
  backend/test/test_modal_deployment_parity.py \
  backend/test/test_collaboration.py \
  backend/test/test_collaborator_chat.py \
  backend/test/test_email_status_routes.py \
  backend/test/test_outreach_routes.py \
  backend/test/test_resume_analytics.py \
  backend/test/test_apply.py \
  backend/test/test_template_routes.py \
  backend/test/test_regional_templates.py \
  backend/test/test_template_asset_preview_integrity.py \
  backend/test/test_resume_builder.py \
  backend/test/test_builder_import.py \
  backend/test/test_variant_visibility.py -q

.venv/bin/python backend/scripts/generate_capability_matrix.py
SKIP_INFRA_CHECK=true .venv/bin/pytest backend/test/test_capability_matrix.py -q
```

## Boundaries

Provider-backed successful generation, real OAuth exchanges, real payments, and manual end-to-end operation of all 129 features were not exercised by this backend verification. Initial broader orchestration runs exposed pre-existing mocked-PDF persistence fixture failures; those helpers were repaired separately from feature policy, and those failures are absent from the aggregate rerun.

Capability switches stop new admissions/external actions. Previously admitted jobs retain their original finalization/refund behavior. Already downloaded data cannot be recalled, and previously issued presigned storage URLs remain valid until expiry. See `docs/capability-enforcement.md` for the complete recovery and publication contract.

## Aggregate run and clean-main attribution

The aggregate backend run completed with **4,641 passed, 16 failed and 4 skipped** (4,661 tests). One failure was generated-matrix freshness while frontend controls were still being edited. The other 15 failing test IDs were reproduced exactly on clean main `bdee48926ce0e2e6c9c5e2b281d2ab07c4355b98`: the same eight files ran 287 tests, with 268 passed, 15 failed and four skipped. See `environment-comparison.json` for each failing test and its classification.

Three scraper unit fixtures mocked all HTTP but still relied on live DNS. Only those three contexts in `backend/test/test_scraper.py` now provide deterministic public DNS answers. The production SSRF implementation is unchanged. The full scraper, URL-import and URL-log-redaction suites then passed **121 tests**, including private/shared/mixed-address rejection, redirect guarding and DNS pinning.

The remaining 12 host-TeX failures are environmental: missing LuaLaTeX format files, unavailable pdfTeX font maps, and a recorder isolation rejection also reproduced on main (the exact blocked path was not logged). No security relaxation, production engine change or additional installation was used to hide these failures. The 121 targeted passes are a separate rerun, not a claim that the whole 4,661-test suite was rerun after the fixture correction.

```sh
.venv/bin/pytest backend/test/test_scraper.py backend/test/test_url_import.py backend/test/test_url_log_redaction.py -q
```
