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
boundary-probe run. The runtime backend accepts this binding only when
`ENVIRONMENT=test`, `DEPLOY_TARGET=modal`, and Modal supplies an explicit
nonproduction `MODAL_ENVIRONMENT`; the renderer image ID and fingerprint must
still be well formed. It uses a distinct noncacheable backend identity and
reports `renderer_boundary_probe: not_run` and
`production_certification_claimed: false`.

Functional-only mode skips only `_VM_BOUNDARY_PREFLIGHT`. It retains the
renderer image/asset preflight, `block_network=True`, no Modal Secrets, no
Volumes, and the actual renderer compile. The test-only setting cannot be
combined with `MODAL_ENGINE_VM_CERTIFIED=true`, and the adapter refuses to
skip the boundary probe outside its explicit nonproduction test configuration.

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

## Functional-only invocation

Use fresh API/services test images built from the exact source revision under
acceptance, plus the already accepted bare renderer tuple below. Replace the
environment and report path with reviewed nonproduction values:

```powershell
python scripts/qa/modal_spawn_acceptance.py `
  --image-id <current-source-api-test-image-id> `
  --services-image-id <nonproduction-services-image-id> `
  --renderer-image-id im-mF0rpCXgH2MBjw3TKMYXEf `
  --renderer-assets-fingerprint db98401df2e8c2d2b5a158ef96dcca6be5cfc36f2fc8451c693cb4018bf6c4a9 `
  --renderer-mode functional-only `
  --region us-east `
  --environment-name <existing-nonproduction-environment> `
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
their source provenance, the existing nonproduction Environment and its
purpose, the test-only binding of the accepted renderer tuple, generated test
credentials sent to Modal, isolated app/environment and private networking,
bounded paid compute, outer Modal control-plane access, Functions' default
egress, and a private report destination. Functional-only mode does not require
approval to run the renderer boundary probes. It does not repeat or invalidate
the existing 61-template acceptance evidence. The API/services images must
include the exact source revision carrying this harness and backend path.

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
