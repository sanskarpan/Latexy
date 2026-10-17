# Modal spawn acceptance harness

`modal_spawn_acceptance.py` is an opt-in nonproduction test. It does not change
the deployment workflow or certify an image. It needs explicit operator input
for the API/LaTeX image, a disposable services image, and the reviewed bare
renderer image/fingerprint tuple. The renderer tuple is supplied only to the
unique test app so the existing admission gate can be exercised; a passing run
does not certify that tuple or populate GitHub Production variables.

The script fails closed unless all four confirmations are supplied:
`--confirm-isolated-modal-run`, `--confirm-nonproduction-renderer-binding`,
`--confirm-default-egress`, and `--confirm-renderer-boundary-probe`. It creates
unique `latexy-harness-*` Modal app/environment names and uses generated test
credentials in an inline `Secret.from_dict`. It never attaches named production
Secrets, a Volume, or a public tunnel. PostgreSQL 15, password-protected Redis,
and Moto S3 run in one disposable I6PN service Function. The service, caller,
and worker report only Modal provider/region labels and Redis/S3 reachability.
The caller and worker both check Redis DB 0 and DB 1 plus S3 `HeadBucket` before
the API submission; the actual spawned worker repeats that check immediately
before entering the compile task. Provider/region mismatch or missing runtime
identity halts the test before the API submission. Provider is read from the
runtime `MODAL_CLOUD_PROVIDER` value when present; if Modal omits it, the test
stops instead of assuming same-cloud placement.

The only report containing runtime identities is written to the required
`--private-report` path outside this checkout. Standard output contains only a
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
attest its source provenance. Teardown status is included in the private report.
