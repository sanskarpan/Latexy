# Renderer audit — October 8, 2026

Reviewed the recent PR #1833 changes after rebasing onto main `bdee4892`.
Pre-fix source snapshot: `87ea1232`. This is local correctness evidence, not
default Modal deployment or production performance certification.

## Verified defects and repairs

- Root follow-up reproduced a second-boundary retention failure for both
  user and guest artifacts: sampling creation/expiry clocks separately yielded
  a TTL one second too long and `invalid render retention interval`. Both new
  tests failed before repair. Creation and expiry now use the same clock sample
  so the strict retention validator can remain unchanged.

- A reused Modal session checked its deadline only before input upload. An
  upload could consume the remaining time, close the session, or throw, yet
  execution still started or the VM remained open. Three pre-fix regression
  cases failed. The adapter now checks before each upload, before execution
  and after execution; failures close the session. Inputs are still restored
  on every pass because untrusted TeX can alter a writable workspace.
- Binary batch export retained a memoryview into the entire aggregate frame
  through later worker bookkeeping. A one-MiB synthetic PDF regression failed
  before repair. Only bounded stdout bytes are retained after file export;
  aggregate PDF/SyncTeX memory can be released. File/type/size/framing checks
  and all existing confinement protections remain.
- Device artifacts expire after 24 hours, but their Redis cache index can
  outlive that manifest. Replaying the pre-fix source proved API lookup still
  selected cache-only dispatch and worker restore attempted to read a deleted
  expired object. Both paths now reject expired manifests before restoration.
  An expired entry causes normal render admission instead of selecting this
  cache-only shortcut. Object retention and publication remain owner fenced.
- Geometry used two serial `pdfinfo` processes to discover count then rotations.
  Actual Poppler clamps `-f 1 -l 1000` at the last existing page and reports
  both count and rotations. Geometry now uses that one bounded probe followed
  by bbox extraction. Real fixtures cover one, two, 1,000 and 1,001 pages and
  rotation on page two. Oversized/rotated PDFs remain read-only; the shared
  six-second deadline, no-follow verified private PDF copy and output bounds
  remain. The fixed `geometry_inspection` metric separates this work from TeX
  and storage; overlapping phase intervals must not be summed as wall latency.
- The Modal certification harness had only a historical cached image probe.
  Optional paired `--image-id` and `--expected-assets` arguments now validate
  an intended immutable pin before setup and enforce its pre-upload assets
  comparison. Omitting them remains explicitly diagnostic. Success does not
  certify default application flow or set `MODAL_ENGINE_VM_CERTIFIED`.

## Reproduce and validation scope

The final focused run passed **88 cases**. Five database-backed artifact
finalization cases were explicitly deselected for this pure run; they must be
covered by the root complete/real-storage verification. The three regression
files are `test_modal_engine_adapter.py`, `test_modal_vm_certification.py` and
`test_render_artifacts.py`. Inspect their named expiry/session/memory/Poppler
cases when reproducing against the old and repaired snapshots.

From `backend`, in the Linux QA image with Poppler installed:

```text
python -m pytest -p no:cacheprovider -o addopts= -q \
  test/test_modal_engine_adapter.py test/test_modal_vm_certification.py \
  test/test_render_artifacts.py test/test_engine_observability.py \
  -k 'not durable_finalization'
```

This exact run reported `88 passed, 5 deselected in 59.06s`. Its deselection
excludes the five parameterizations of
`test_durable_finalization_binds_private_manifest`. Output was retained in the
agent tool transcript; this passing run did not write JUnit. Do not substitute
the disappeared JUnit from an earlier failed fixture-setup run.

For infrastructure-free cases only, set `SKIP_INFRA_CHECK=true` and select the
pure fixtures explicitly. The full backend and actual storage run require
isolated PostgreSQL/Redis/object storage with infrastructure checks enabled.

Ruff and scoped diff checks passed for all nine changed files. A broader
renderer run encountered one existing 30-second child-import deadline under
host contention; that fixture passed unchanged on a serial rerun. No deadline
or assertion was relaxed, and the timed-out run is not represented as green.

No cloud calls, paid providers or deployment occurred. The actual default
managed Lua workload needs separate performance measurement; the older plain
article pdfLaTeX benchmark cannot certify it. Broad Modal Lua remains closed
until intended-image multilingual/isolation/default-flow acceptance succeeds.
