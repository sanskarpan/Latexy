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
it is not the ordinary functional smoke described here. Its historical CJK
failure and the separate supported-profile/default-flow requirements remain
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

The additional harness is being implemented and independently reviewed. No
successful container/browser execution of this new gate is claimed yet.

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
ESLint. The harness passed **17 dependency-free guards**, scoped Python lint,
and an independent read-only review. Its dedicated browser case was collected,
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
