# Modal spawn acceptance harness

`modal_spawn_acceptance.py` is an opt-in nonproduction test. It does not change
the deployment workflow or certify a renderer image. It accepts reviewed
immutable IDs for the API/LaTeX test image, disposable services image, and bare
renderer image/fingerprint tuple. A passing run checks the API-to-worker path,
synthetic document compilation, PDF finalization, and accepted-PDF visibility.

## Renderer modes

The default `--renderer-mode boundary` preserves the existing path and requires
all five confirmations: `--confirm-isolated-modal-run`,
`--confirm-nonproduction-environment`,
`--confirm-nonproduction-renderer-binding`, `--confirm-default-egress`, and
`--confirm-renderer-boundary-probe`. Its renderer adapter performs image
identity preflight and `_VM_BOUNDARY_PREFLIGHT` checks for `/proc/1` access and
outbound network denial. A passing boundary run still does not certify the
image or populate production variables.

`--renderer-mode functional-only` runs the same API/worker/PDF functional flow
but sets a distinct test-only renderer binding. It requires
`--confirm-functional-renderer-binding` along with the isolated-run,
nonproduction-environment, and default-egress confirmations. It rejects
`--confirm-renderer-boundary-probe` so this mode cannot be mistaken for a
boundary-probe run. No functional-acceptance Environment is currently
approved in source, so functional-only mode fails closed for every name before
it imports the Modal SDK. The historical billing Environment is quarantined
because its existing resource bindings were not verified; the named synthetic
Environment also remains unverified. Neither an environment name, a CLI
acknowledgement, nor a caller-set test flag establishes isolation.

To prepare a candidate, run the read-only inventory command shown below only
after access to that account is authorized. It reports the Modal Environment
object ID, counts of named Secrets, Volumes, and active Apps, and a fingerprint
over their names and object IDs. It never outputs Secret names or values. An
empty result is only evidence for review. To enable a future run, a reviewed
source change must add the exact Environment name, Modal object ID, inventory
fingerprint, and a reviewable evidence reference to
`functional_acceptance_policy.py`; regression tests must bind all four fields.
If Modal SDK inventory is unavailable or incomplete, the check fails closed.

The runtime backend and adapter also require the approved object ID and
fingerprint alongside `ENVIRONMENT=test`, `DEPLOY_TARGET=modal`, and the exact
`MODAL_ENVIRONMENT`. The renderer image ID and asset fingerprint remain
well-formed, and the functional backend identity is noncacheable and distinct
from the certified policy. `MODAL_ENGINE_VM_CERTIFIED` is explicitly blanked
(including any image-layer assertion). A functional report says
`renderer_boundary_probe: not_run` and
`production_certification_claimed: false`.

The direct temporary API/worker Functions explicitly set
`MODAL_DEPLOYMENT_TRAFFIC_HOLD=false`, because Modal-tagged API processes now
default to held. This is scoped to the reviewed nonproduction harness Functions;
it does not change the deployment workflow's production hold or release approval.

Functional-only mode skips only `_VM_BOUNDARY_PREFLIGHT`. It retains the
renderer image/asset preflight, `block_network=True`, and the actual renderer
compile. The API and worker receive only generated synthetic credentials in an
inline Secret; the renderer Sandbox receives no Secrets or Volumes. The
test-only setting cannot be combined with `MODAL_ENGINE_VM_CERTIFIED=true`, and
the adapter refuses to skip the boundary probe outside its exact reviewed
nonproduction configuration.

## Resource scope and environment

Both modes require an existing Modal Environment selected with
`--environment-name` and the explicit `--confirm-nonproduction-environment`
attestation. Before creating an app, queue, or service, the harness checks
existence using the read-only `modal.Environment.objects.list()` SDK method. It
never creates an Environment and rejects `main`, `prod`, and `production`.
The selected environment name is passed explicitly to the ephemeral queues,
service App run, dispatch App deployment, and preflight Function lookup.
Modal's `MODAL_ENVIRONMENT` runtime variable is not overridden by the harness.

The harness creates uniquely named `latexy-harness-*` Modal apps and generated
test credentials in an inline `Secret.from_dict`. It never attaches named
production Secrets, a Volume, or a public tunnel. PostgreSQL 15,
password-protected Redis, and Moto S3 run in one disposable I6PN service
Function. Service, caller, and worker report only provider/region labels and
Redis/S3 reachability. The caller and worker check Redis DB 0 and DB 1 plus S3
`HeadBucket` before API submission. The spawned worker checks again and compares
its provider/region to the caller before compilation. Unknown or mismatched
placement stops before compile. The service, caller, and worker use Modal's
default outbound egress; I6PN does not block internet egress.

## Functional-only preparation and invocation

Use Modal's read-only CLI inventory first, then the SDK inventory required to
bind the stable object ID and safe resource manifest:

```powershell
modal environment list --json
python scripts/qa/modal_functional_environment_inventory.py `
  --environment-name <candidate-environment>
```

The first command is Modal's documented Environment listing command. The
second performs read-only `Environment.objects.list()`,
`Secret.objects.list(environment_name=...)`, and
`Volume.objects.list(environment_name=...)` calls. For Apps, it uses
`Environment.apps.list()` when available. On SDKs before 1.6 it uses the
documented `python -m modal app list --env <candidate-environment> --json`
command and filters stopped/disabled records in memory. Neither path reads
Secret contents, and the report omits resource names. Failures include a fixed
code and operation stage, with the exception class when available; raw exception
text is omitted. An empty candidate inventory is
ready for source review, but does not authorize a run. After its exact
identity and fingerprint have been approved in source, fresh API/services test
images must be built from that source revision, plus the already accepted bare
renderer tuple below. Replace placeholders only with reviewed values:

```powershell
python scripts/qa/modal_spawn_acceptance.py `
  --image-id <current-source-api-test-image-id> `
  --services-image-id <nonproduction-services-image-id> `
  --renderer-image-id im-mF0rpCXgH2MBjw3TKMYXEf `
  --renderer-assets-fingerprint db98401df2e8c2d2b5a158ef96dcca6be5cfc36f2fc8451c693cb4018bf6c4a9 `
  --renderer-mode functional-only `
  --region us-east `
  --environment-name <reviewed-environment> `
  --private-report <private-path-outside-checkout> `
  --confirm-isolated-modal-run `
  --confirm-nonproduction-environment `
  --confirm-default-egress `
  --confirm-functional-renderer-binding
```

Modal's current `modal image` CLI exposes build-log and named-image management
commands, but no direct `image build` subcommand. Build each current-source
image from a separate, nonproduction image-build script using Modal's
`Image.build(app)` API, then pass the resulting immutable image IDs here; do
not use `modal deploy` on the production application as an image-build shortcut.
Modal documents this independent image-build-script flow in its
[Named Images guide](https://modal.com/docs/guide/named-images).

Before a later run, the operator must approve the two exact test image IDs and
their source provenance, the exact Environment name/object ID and fresh
resource inventory, the test-only binding of the accepted renderer tuple,
generated test credentials sent to Modal, isolated app/environment and private
networking, bounded paid compute, outer Modal control-plane access, Functions'
default egress, and a private report destination. Functional-only mode does
not run renderer boundary probes. It does not repeat or invalidate the
historical 61-template acceptance evidence. That evidence and the accepted
renderer tuple do not validate backend/adapter source changed in this branch;
the functional-only run checks this branch's current API/worker/PDF path. The
API/services images must include the exact source revision carrying this
harness and backend path.

For a boundary run, omit `--renderer-mode` or pass `boundary`, retain the old
`--confirm-nonproduction-renderer-binding` acknowledgement, and add
`--confirm-renderer-boundary-probe` instead of the functional-only binding
acknowledgement.

## Reports and cleanup

The detailed report is written only to the required `--private-report` path
outside this checkout. The harness rejects report paths inside the checkout but
does not set filesystem permissions or ACLs. Standard output includes only a
status and fixed failure code. No raw endpoint, provider exception, job/user
identifier, or credential is included. Teardown failure turns a would-be pass
into a failed final report and exit status. Dispatch App stop is attempted even
if deployment raises after partially creating the unique app; Moto, Redis, and
PostgreSQL stop results are checked independently, and cleanup failures do not
suppress report writing.

## Synthetic tests

Run the dependency-free harness regressions with
`python scripts/qa/run_modal_spawn_diagnostics.py`. The runner discovers the
dedicated test module and requires a minimum test count. The suite uses no Modal
credentials, SDK calls, or infrastructure.

## Production launch smoke

`production-launch-smoke.mjs` checks the deployed frontend and backend and
writes machine-readable, redacted evidence. The default mode is read-only: it
issues only `GET` requests, sends no credentials, and changes no data. Runs are
safe to repeat. Job creation, compiles, saves, deep ATS analysis, and share-link
creation require explicit flags and are never part of the default run.

### Prerequisites

- Node.js 22 or newer. The script uses built-in `fetch`, `parseArgs`, and
  filesystem APIs.
- Optional browser checks use `@playwright/test` and Chromium. The script
  resolves the frontend workspace devDependency dynamically, so a read-only run
  does not require Playwright. Install the browser once with:

  ```powershell
  pnpm --dir frontend exec playwright install chromium
  ```

- Optional account checks need a Playwright storage state for a dedicated QA
  account. Keep that file outside the checkout and never commit it: it contains
  a live session cookie. The script rejects a storage state path inside the
  repository. One way to create it is:

  ```powershell
  pnpm --dir frontend exec playwright codegen --save-storage="$env:TEMP\latexy-qa-state.json" https://latexy.xyz/login
  ```

  Sign in with the QA account, close the codegen window, and keep the resulting
  file private. Use an account that is explicitly reserved for QA: the
  `--account` flow compiles, saves, and may create a new resume.

### Read-only run

From the repository root, in PowerShell or a POSIX shell:

```bash
node scripts/qa/production-launch-smoke.mjs
```

Defaults:

- Frontend: `https://latexy.xyz`
- Backend: `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`
- Evidence: `qa-evidence/production-smoke-<timestamp>.json`

Override targets or the evidence path explicitly:

```bash
node scripts/qa/production-launch-smoke.mjs \
  --base-url https://latexy.xyz \
  --api-url https://example-backend.modal.run \
  --out qa-evidence/launch-readiness.json
```

The read-only run checks:

- Backend `/health` (must report `healthy`), `/readyz` (must return HTTP 200
  with `ready`), and `/jobs/health` (must report `healthy`).
- Anonymous effective entitlements from
  `/config/entitlements?include_quotas=false`.
- The template catalog at `/templates/`: template count, presence of
  `thumbnail_url` and `pdf_url` on at least one entry, and HTTP 200 for one
  sample thumbnail and one sample PDF. Bodies are discarded.
- `/subscription/plans`: billing mode/availability and the free/basic quota
  dimensions and limits.
- Unauthenticated `/resumes/`, `/developer/keys`, and `/tracker/applications`
  return 401.
- Frontend deployment identity from `/api/deployment-identity`, including the
  public commit SHA and source.
- Status-only checks for `/`, `/pricing`, `/templates`, `/try`, `/login`,
  `/faq`, `/privacy`, `/terms`, `/robots.txt`, `/sitemap.xml`, and `/llms.txt`.

### Opt-in checks and flags

| Flag | Effect | Requires |
| --- | --- | --- |
| `--guest-compile` | Opens `/try` in Chromium, keeps the built-in sample, submits one compile, and waits for a PDF canvas. | `LATEXY_PRODUCTION_SMOKE=1` |
| `--account` | Opens `/workspace` with the QA storage state, opens or creates a resume, compiles, downloads and verifies the PDF signature, saves, hard-reloads, and verifies the editor loads. | `LATEXY_PRODUCTION_SMOKE=1` and `LATEXY_QA_STORAGE_STATE` |
| `--deep-ats` | Submits a synthetic small LaTeX resume to `/ats/deep-analyze` and polls `/jobs/{id}/state` to a terminal state, bounded to 3 minutes. | `--account` |
| `--share` | Creates or reuses a share link, then loads it in a fresh incognito context and verifies the public PDF frame. | `--account` |
| `--help` | Prints usage and exits without running checks. | None |

`--guest-compile` calls a real anonymous compile and consumes one anonymous
trial. `--deep-ats` spends configured LLM quota. `--share` creates or reuses a
public link for the QA resume. The script never creates accounts, never sends
email, and must not be given real user credentials.

Required environment variables:

| Variable | Required for | Value |
| --- | --- | --- |
| `LATEXY_PRODUCTION_SMOKE` | `--guest-compile`, `--account`, and their dependants | Exactly `1`; any other value fails the opt-in gate. |
| `LATEXY_QA_STORAGE_STATE` | `--account`, `--deep-ats`, `--share` | Absolute or working-directory-relative path to a Playwright storage state file outside the repository. |

Example opt-in run:

```powershell
$env:LATEXY_PRODUCTION_SMOKE = '1'
$env:LATEXY_QA_STORAGE_STATE = "$env:TEMP\latexy-qa-state.json"
node scripts/qa/production-launch-smoke.mjs --account --deep-ats --share
```

POSIX equivalent:

```bash
LATEXY_PRODUCTION_SMOKE=1 \
LATEXY_QA_STORAGE_STATE="$TMPDIR/latexy-qa-state.json" \
node scripts/qa/production-launch-smoke.mjs --account --deep-ats --share
```

If an opt-in flag is supplied without its prerequisite, the script exits with
code 2 before running checks. Optional checks that were not requested are
recorded as `skipped`; they are never reported as passed.

### Evidence format

The JSON file contains one record per check:

```json
{
  "schemaVersion": 1,
  "tool": "latexy-production-launch-smoke",
  "startedAt": "2026-11-18T14:26:56.169Z",
  "finishedAt": "2026-11-18T14:27:08.731Z",
  "config": {
    "baseUrl": "https://latexy.xyz",
    "apiUrl": "https://example-backend.modal.run",
    "optionalFlags": [],
    "readOnlyByDefault": true
  },
  "summary": {
    "total": 25,
    "passed": 21,
    "failed": 0,
    "skipped": 4,
    "required": 21,
    "requiredFailed": 0,
    "optionalEnabled": 0,
    "ok": true
  },
  "checks": [
    {
      "id": "backend.health",
      "kind": "read-only",
      "required": true,
      "method": "GET",
      "url": "https://example-backend.modal.run/health",
      "timestamp": "2026-11-18T14:26:56.171Z",
      "httpStatus": 200,
      "elapsedMs": 412,
      "outcome": "passed",
      "summary": "status=healthy"
    }
  ]
}
```

Each check records its timestamp, URL, HTTP status where applicable, elapsed
milliseconds, outcome (`passed`, `failed`, or `skipped`), and a redacted
summary. Evidence never contains response bodies, cookies, bearer tokens, email
addresses, resume/job/share identifiers, resume titles, or LaTeX source. The
frontend commit SHA is public deployment identity and is recorded. Raw browser
downloads are read only for the `%PDF-` signature and byte count; their contents
and filenames are not stored.

Exit codes:

- `0`: every required check passed and no enabled optional check failed.
- `1`: a required check failed, or an enabled optional check failed.
- `2`: invalid arguments or a missing opt-in prerequisite.
