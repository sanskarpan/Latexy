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
