# Isolated engine verification — October 11, 2026

## Why another verification job is needed

The reviewed PR #1833 application snapshot is
`1da1c16e7344909f98c1e5bd55e3fd1e6a5d4782`. Its
[CI run 38088328730](https://github.com/sanskarpan/Latexy/actions/runs/38088328730)
passed all existing jobs. That result has important boundaries:

- [Template PDF Extraction Contract](https://github.com/sanskarpan/Latexy/actions/runs/38088328730/job/114319448912)
  compiled all **61** shipped templates using real LuaLaTeX on the Ubuntu
  runner, checked extracted text and required ToUnicode font maps. It did not
  execute the application's queue, storage or isolated Modal renderer.
- [Cross-Browser Quality](https://github.com/sanskarpan/Latexy/actions/runs/38088328730/job/114319448909)
  passed **142** quality cases, **82** explicit editor/builder/billing/Settings
  cases and **1** hydration case, with **3** explicit skips. Its job, artifact
  and provider responses are synthetic.
- [Full-Stack Smoke](https://github.com/sanskarpan/Latexy/actions/runs/38088328730/job/114320222182)
  checked startup, flags and editor navigation. Its log explicitly reports
  unavailable LaTeX and object storage. It did not start a Celery worker or
  compile a document. Its success must not be presented as end-to-end rendering
  proof.

The isolated verification work is intended to close this last functional gap
without deployment, production data, provider credentials or paid model calls.
The application snapshot above remains the comparison point; the final test
revision and its actual executed image must be recorded with new evidence.

## Required evidence from the additional job

1. Start only the candidate's API and worker, fresh PostgreSQL and Redis,
   and a private object-storage bucket. Use synthetic values, no developer
   dotenv files, no shared service reuse, no beat and no production endpoints.
2. Compile fixed repository-owned documents using the actual TeX engines and
   unchanged runtime confinement. Require successful terminal state, a valid
   PDF, matching stored/downloaded bytes and immutable manifest ownership.
3. Drive the candidate production frontend against that backend and verify
   actual PDF painting, the edited source's final output, and matching
   geometry/SyncTeX. Preserve the normal guest cooldown and authorization.
4. Exercise deterministic conversion errors with a local fake provider while
   using real disposable lifecycle/accounting storage. Check durable terminal
   state and exactly-once quota restoration, rather than only mock call counts.
5. Fail on missing required services, an empty certification matrix, failed
   fixtures or unexpectedly skipped required tests. Retain bounded, redacted
   evidence and clean up only the resources created by this run.

The existing guest smoke helper needs to retain its submitted fingerprint when
requesting protected artifacts. The existing template certification helper must
also return failure when its recorded matrix is empty or contains a failure.
Neither repair relaxes artifact ownership or compiler policy.

## Remaining limits after a successful isolated run

This is candidate Linux/container functional evidence. It cannot attest a
different Modal VM image, production configuration, cloud regions/capacity or
production user-action-to-paint percentiles.

The actual Modal route still requires an intended immutable bare TeX image,
its independently read asset fingerprint and a separately authorized execution
context. A bounded ephemeral functional run can test ordinary templates and
fonts without deploying the candidate or attaching production data. The
existing `certify_modal_vm_engine.py` additionally performs isolation probes;
it is not the ordinary functional smoke described here. The historical CJK
failure was not reproduced in the October 11 ordinary smoke below; its cause
and the separate candidate supported-profile/default-flow requirements remain
open in [MODAL_RENDERER_CAPABILITY.md](../../MODAL_RENDERER_CAPABILITY.md).

Do not set certification flags merely to pass configuration checks. The
deployment preflight's `certification_verified: false` is intentional, and the
billing and renderer guards remain required before any later rollout.

The slower retained local A/B samples, controlled cold/warm/cache/overlap
performance matrix, and actual configured-provider quality/usage acceptance
remain open as documented in the
[combined handoff](combined-integration-2026-10-10.md). A deterministic fake
provider can prove failure/accounting mechanics; it cannot prove live model
availability, answer quality or provider charges.

## Execution status

The additional harness is implemented and independently reviewed. Its first
[CI execution on revision 42282346](https://github.com/sanskarpan/Latexy/actions/runs/38111831084)
failed after successfully building the candidate image: the pinned Docker Hub
MinIO image could not be pulled anonymously, before any application container
or test started. No successful container/browser execution of this new gate is
claimed yet. The existing deployment-manifest test's exact job inventory initially
rejected the added job; the corrected inventory and isolation contract passed
all **96** deployment-manifest tests and independent review.

The failed isolated attempt's [artifact 11692107284](https://github.com/sanskarpan/Latexy/actions/runs/38111831084/artifacts/11692107284)
was downloaded and verified against SHA-256
`c3cd11c1981ccef0f4c8e598785c59de6ee661c00013487b2e12781fe212ad89`.
It records `success: false`, `cleanup_success: true`, no cleanup failures,
the actual GitHub merge-ref checkout `95130a5b3118a9462a3abde0f98832c43177dd38`,
and candidate image
`sha256:94d3bfa319082707bdf5a38a11c76fc4e726e088374269ba43dfdcf5f8ff92b8`.
No runtime or browser result may be inferred from this build-only checkpoint.

The corrected disposable storage fixture follows MinIO's documented
[source-only installation](https://github.com/minio/minio#install-from-source).
Its [official security release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z)
is pinned to source commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`
and checksum-verified Go module `v0.0.0-20251015172955-9e49d5e7a648`.
The official Go 1.24.8 builder is digest-pinned. A bounded 900-second build
produces an owned, non-root fixture image before the expensive candidate image
build; the evidence records its recipe, source and actual image identity.
No private registry login or third-party prebuilt image is substituted. The
overall 45-minute harness deadline, private network, fresh data and exact-owned
cleanup remain enforced.

The [second CI execution, 38112962998](https://github.com/sanskarpan/Latexy/actions/runs/38112962998),
on head `58f205bf`, built both images and passed private bucket creation,
migrations, **all 11 real-ledger cases with zero failures/errors/skips**, and
both actual LuaLaTeX template fixtures with zero glyph/font warnings. The
downloaded [artifact 11691799799](https://github.com/sanskarpan/Latexy/actions/runs/38112962998/artifacts/11691799799)
matches SHA-256 `6d4f4de4cbde09ddb0f91fad089c177b3c0ca00d7cedafd35a9b37da2368854b`.
It records actual merge-ref checkout `27fa4dea500209a6b860d5d045b76d2ddda568a8`,
candidate image `sha256:c3a5a474e9dfd8bc4ceb00663e59d1bf69139737e723bdb68251343122c0cdd4`,
renderer assets `92acced6b3d7da59623032c79d0ccdefc9d1a3da860523868a2197f8b0cf85e7`,
and successful cleanup. The English and Hindi direct two-pass fixture totals
were **1.783 seconds** and **2.985 seconds** respectively; two samples do not
establish percentile or application latency acceptance.

That run stopped before real API/worker submissions or browser execution because
Docker does not publish requested host ports for containers attached exclusively
to an internal bridge. The fixture must preserve its internal network rather than
give backend services an external route. Docker documents host access to the
internal bridge's container addresses in its
[port-publishing guide](https://docs.docker.com/engine/network/port-publishing/).
The correction uses ephemeral loopback-only TCP relays to the exact inspected,
run-owned API and PostgreSQL endpoints. It forwards the real protocol bytes,
retains backend egress isolation, adds no external network or host configuration,
and closes its own listeners/connections during cleanup. Bounded redacted
own-container diagnostics are retained on failure. **31** dependency-free guards
pass with warnings treated as errors, including duplex/half-close, target
ownership, deadlines and cleanup. The corrected host access path still requires
actual CI verification.

The second run's separate ordinary browser gate also retained one intermittent
React hydration error in the existing Settings token-rotation case. All owner
and callback checks completed; the trace places the error during the second
navigation, before its callback/status requests. No application/frontend runtime
code changed between the preceding passing run and this failure, and the exact
hydration cause is not yet established. A bounded failure-only replay of this
single synthetic case collects structural diagnostics if the same error recurs.
It preserves the original failed gate, zero-page-error and owner assertions,
zero retries and original artifacts. Instrumented replay output is diagnostic
evidence, never a replacement for the ordinary unmodified-bundle acceptance run.
The correction passes **97** deployment-manifest contracts; the optional
diagnostic has **six** focused unit regressions for its pinned hook, ordinary-case
opt-in, bounded capture, delivery ordering, timeout and origin restrictions.

The [third CI execution, 38114969613](https://github.com/sanskarpan/Latexy/actions/runs/38114969613),
on head `fb09cbc4`, verified the corrected host access path: the real API accepted
a guest compile, the broker/worker completed it, and its download returned a PDF.
The smoke reader then failed because it expected a flattened result, while the
public `JobResultResponse` wraps the worker payload under `result`. The reader
now validates both success flags, both job identities, `pdf_job_id`, error
consistency and the required nested artifact before accepting evidence. It does
not accept the obsolete flattened shape or substitute an absent artifact.
**37** dependency-free guards pass with warnings treated as errors, including
wire-shaped success/failure cases and the complete mocked reader protocol.
The actual artifact, private storage and real browser checks still need the next
CI run; a successfully downloaded PDF alone does not close those gates.

The downloaded [artifact 11692898534](https://github.com/sanskarpan/Latexy/actions/runs/38114969613/artifacts/11692898534)
matches SHA-256 `cab3c7c91695ce92d4e94c71708fb7bc2e4ac592868d0277605fc3aa3dbf974b`.
It records actual merge-ref checkout `82e54f9dc8f7cf8a6b9d5664b164b0c8e93c6310`,
candidate image `sha256:bccb7170a645a57bee67d018e5581d51c14ad4d9f3bc524b9490f1d0537c3234`,
renderer assets `da4fca5eb5b248b5d886bc83af75636329e444159f802e050aa98489360219d7`,
and successful cleanup. No application latency is inferred from the coarse
container log timestamps.

The third run's other **14 CI jobs passed**. Its broader browser quality suite
reported **141 passed, one flaky and three skipped** under its existing retry
policy; the explicit owner/editor matrix passed **82/82 with zero retries**, and
the dedicated hydration case passed. The quality flake was one React 418 during
the final signed-out homepage reload in the account-navigation case, with no
unmocked API or unexpected authentication requests. The passing retry used the
same three session reads. It does not establish the mismatched node, and the
original failure has no trace. This is retained as unresolved hydration evidence,
not reported as clean first-attempt browser acceptance. The Settings-only
failure diagnostic correctly did not run because that case passed.

The [fourth CI execution, 38116203352](https://github.com/sanskarpan/Latexy/actions/runs/38116203352),
on head `b5a92858`, passed both complete API/broker/worker/storage smoke cases:
the pdfLaTeX fixture produced a one-page **31,223-byte** PDF with one geometry
box, and the Hindi LuaLaTeX fixture produced a one-page **35,909-byte** PDF.
Both verified exact immutable preview/export bytes, source/PDF hashes,
SyncTeX, geometry, private object storage, durable PostgreSQL/Redis identity and
normal trial accounting. The Hindi fixture has no editable geometry boxes;
it is an international-text compilation fixture, not editable-overlay proof.
All **11** deterministic provider-failure ledger cases and both direct Lua
fixtures also passed, with no failed/skipped required case.

Its [artifact 11694310460](https://github.com/sanskarpan/Latexy/actions/runs/38116203352/artifacts/11694310460)
was downloaded and verified against SHA-256
`e3cd5434378595b0fd62236a07fb04496881a4754edca62d1d397621bb1cb3f2`.
It records actual merge-ref checkout `d682249178d9aff40ee2f67c8ea818088662ebf8`,
candidate image `sha256:4b35b069cba490a416408333513b7267db7ecdf091f2fbbe0bc8a17a68e9d5f3`,
renderer assets `e8f15ae16a39ecd2034a3cede8c9e532bf9ff00d0af9223bae9033d6f0894581`,
and successful cleanup.

The real production-built browser reached `/try`, but no compilation was
admitted: the harness used `ENVIRONMENT=staging`, whose existing backend CORS
policy deliberately strips loopback origins. Its direct HTTP helpers did not
exercise browser Origin handling. The browser therefore could not read engine
capabilities and correctly left Resume mode unavailable. The corrected local
harness uses the supported development CORS path with `DEBUG=false`, strong
fresh signing/encryption values and disabled billing/email/providers. It checks
one actual Origin capability GET and four normal browser OPTIONS contracts
before admitting jobs or building the browser, without credentials or quota
changes. Backend production CORS, capability guards and network isolation remain
unchanged. This local environment also exposes development documentation and
invite-preview branches; it does not claim production-policy equivalence.
**43** dependency-free guards and **97** deployment-manifest contracts pass.
The browser helper also binds observational state reads to the exact admitted
fingerprint and handles multiple line overlays for one exact semantic field;
its PDF/source/geometry identity and keyboard selection assertions remain.
**11** focused frontend tests, full TypeScript, focused lint and discovery of
exactly one browser case pass. The actual two-sample browser proof remains open
until a corrected run passes.

The fourth run's other **14 CI jobs passed**, including clean ordinary browser
results: **142 passed / three intentional skips**, **82/82 explicit owner/editor
cases with zero retries**, and **one hydration case passed**. Neither prior
intermittent React 418 reproduced; those historical observations are retained.

The new `test_converter_failure_ledger_integration.py` passed **11 cases, no
skips, in 3.89 seconds** with warnings treated as errors against disposable
PostgreSQL/Redis. Its final run also removed the optional `TEST_REDIS_*`
variables after conftest selection to verify the standard test defaults. Those cases cover
model 404, timeout and invalid output with normal/lost/throwing terminal events,
duplicate invocation/compensation, and durable recovery after lost success.
Only the provider HTTP transport and explicit event-delivery failures are
replaced. The task executes eagerly: this result does not prove broker delivery
or a real provider response. No application runtime edit was needed.

The final frontend passed **1,587 tests in 226 files**, TypeScript and full
ESLint. The initial harness passed **17 dependency-free guards**; the source-built
storage correction passes **20 guards** and scoped Python lint. The initial
harness and correction also passed independent read-only review. Its dedicated browser case was collected,
not executed locally. Actual browser execution is required in the isolated job
before this gap can be closed.

Append exact final revision, run, image and artifact evidence only after the
required stages have actually completed. The intended repository-root command
is:

```sh
python scripts/ci/isolated-real-compile.py --confirm-isolated-ci-run \
  --evidence-dir "$NEW_EVIDENCE_DIRECTORY"
```

It requires Docker, Node 22, installed locked frontend dependencies and the
Playwright-managed Chromium runtime. The evidence directory must not already
exist. It is a mutating local/CI test operation against newly created disposable
resources, not a read-only production diagnostic. Review the harness before
running it outside the dedicated CI job.

## Historical Modal functional evidence

The authorized October 11 ordinary smoke used the already existing immutable
image `im-1fho7eMXjj9Z60ziS7Kf6J`, without an image build. The actual compiler was
LuaHBTeX 1.15.0 / TeX Live 2022 (Debian). All three fixed synthetic documents
passed: English **1.920 s**, Hindi **0.612 s**, CJK **3.122 s**. Each produced a
valid PDF with the expected text and zero missing-glyph or font warnings.

[Redacted execution evidence](historical-modal-functional-2026-10-11.json)
records server-confirmed 300-second maximum lifetime, 2-core/2-GiB limits, blocked
network, no attached credentials or mounts, one sandbox creation, zero image
builds/retries and confirmed termination. Started-to-finished lifetime was
**6.255 seconds**. These durations are individual direct compiler samples,
not API/worker/browser latency or a distribution.

The image has no renderer marker or asset fingerprint. This result cannot
certify the candidate image, its renderer bridge, confinement checks, supported
profile or application default flow. The earlier CJK failure was not reproduced;
the missing original failure log still prevents establishing its cause.
