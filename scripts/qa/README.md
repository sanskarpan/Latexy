# Modal spawn acceptance harness

`modal_spawn_acceptance.py` is an opt-in nonproduction test. It does not change
the deployment workflow or certify an image. It needs explicit operator input
for the API/LaTeX image, a disposable services image, and the reviewed bare
renderer image/fingerprint tuple. The renderer tuple is supplied only to the
unique test app so the existing admission gate can be exercised; a passing run
does not certify that tuple or populate GitHub Production variables.

The script requires an existing nonproduction Environment selected with
`--environment-name` and an explicit `--confirm-nonproduction-environment`
attestation. Before any app, queue, or service resource is created, it validates
the name using the read-only `modal.Environment.objects.list()` SDK method.
It never creates an Environment and rejects `main`, `prod`, and `production`.
The script also fails closed unless all five confirmations are supplied:
`--confirm-isolated-modal-run`, `--confirm-nonproduction-environment`,
`--confirm-nonproduction-renderer-binding`, `--confirm-default-egress`, and
`--confirm-renderer-boundary-probe`. It creates uniquely named
`latexy-harness-*` Modal apps inside the selected Environment and uses generated
test credentials in an inline `Secret.from_dict`. It never attaches named
production Secrets, a Volume, or a public tunnel. PostgreSQL 15, password-protected Redis,
and Moto S3 run in one disposable I6PN service Function. The service, caller,
and worker report only Modal provider/region labels and Redis/S3 reachability.
The caller and worker both check Redis DB 0 and DB 1 plus S3 `HeadBucket` before
the API submission. The actual spawned worker repeats that check, then compares
its own provider and region to the caller's preflight placement immediately
before entering the compile task. A mismatch is recorded only in disposable
test Redis and stops before compilation. Provider is read from the runtime
`MODAL_CLOUD_PROVIDER` value when present; if Modal omits it, the test stops
instead of assuming same-cloud placement. Modal supplies its
`MODAL_ENVIRONMENT` runtime variable; the harness does not pass an override in
the function `env` mapping. The selected `environment_name` is passed explicitly
to both ephemeral queues, the service App run, the dispatch App deployment, and
the preflight Function lookup; no resource relies on an active-environment
default.

Example PowerShell invocation (replace each placeholder with reviewed values
and an existing sandbox Environment name):

```powershell
python scripts/qa/modal_spawn_acceptance.py `
  --image-id <approved-api-test-image-id> `
  --services-image-id <approved-services-image-id> `
  --renderer-image-id <reviewed-renderer-image-id> `
  --renderer-assets-fingerprint <reviewed-64-character-fingerprint> `
  --environment-name <existing-nonproduction-environment> `
  --private-report <private-path-outside-checkout> `
  --confirm-isolated-modal-run `
  --confirm-nonproduction-environment `
  --confirm-nonproduction-renderer-binding `
  --confirm-default-egress `
  --confirm-renderer-boundary-probe
```

The operator must verify that the selected existing Environment is intended
for nonproduction use. The lookup checks existence only; the name and explicit
attestation do not independently certify its purpose.

The detailed report containing runtime identities is written to the required
`--private-report` path outside this checkout. The harness rejects report paths
inside the checkout but does not set filesystem permissions or ACLs; choose a
location with appropriate access controls. Standard output contains only a
status and fixed failure code. No raw endpoint, provider exception, job/user
identifier, or credential is included. The test uses a synthetic user and LaTeX
document, checks finalization and accepted-PDF visibility, then attempts
share/bulk selection with a newer unaccepted fixture. The service, caller, and
worker Functions use Modal's default egress policy; I6PN does not mean outbound
internet is blocked. The test creates no public tunnel. The renderer VM uses
the application's existing credential-free adapter with `block_network=True`,
no Secrets, and no Volumes. Its `_VM_BOUNDARY_PREFLIGHT` still probes `/proc/1`
and outbound connectivity; its separate approval is required before a real
full-path run.

## Resource and approval boundary

Running this test creates paid nonproduction Modal resources. It uses at most
one service Function, one caller Function, one worker Function at a time, and
the renderer adapter's single VM at a time. Function calls have hard timeouts;
the renderer session remains bounded by the adapter's existing 300-second,
2-GiB ceiling. Functions connect over disposable private I6PN addresses; their
default outbound egress remains enabled and needs explicit approval. Modal's
automatic cloud placement is not pinned by this harness: if the service,
caller, and worker do not report the same provider and requested region, no
compile request is submitted.

Before running, an operator must approve the exact current-source test image
IDs, the nonproduction renderer assertion, the temporary generated test
credentials sent to Modal, the isolated app/environment and private networking,
the bounded paid compute, outer Modal control-plane access, the Functions'
default egress, and the renderer boundary probe. Existing `billing-acceptance-*`
Secret labels are not reused.
The API/LaTeX image must independently be shown to contain the intended clean
source revision; this harness accepts an immutable image ID but does not
attest its source provenance. Private services are signaled and joined while
their queues and app run scope remain active. Teardown failure changes a
would-be pass into a failed final report and exit status. Dispatch app stop is
attempted even if deployment raises after partially creating the unique app;
Moto, Redis, and PostgreSQL stop results are checked independently, and
cleanup failures are bounded and do not suppress report writing.

## Synthetic tests

Run the dependency-free harness regressions with
`python scripts/qa/run_modal_spawn_diagnostics.py`. The runner discovers the
dedicated test module and fails if fewer than 38 tests are selected. CI runs
this source-only suite without Modal credentials, SDK access, or infrastructure.
