# Non-finite telemetry — focused local acceptance

This refreshed candidate for issue #1800 is not deployed. Revalidation is based on refreshed
input-bounds PR #1792 at `722c4c06e6c8981f00ee4041fe0dd0f742505836`, which
contains then-current main `c8cdbf933461723729e72dfc0fef097b25fc00bd` plus the four
reviewed public-trial bounds/redaction files. It adds only the non-finite
metadata/error-envelope checks and compilation-query ingress repair described
below. The earlier full-suite result later in this report was measured on an
older source snapshot and does not certify this refreshed base.

## Body metadata and validation diagnostics

The shared policy rejects nested NaN/Infinity/-Infinity before persistence
using `json.dumps(..., allow_nan=False)`. Registered handlers exclude raw input/context
and defensively replace non-finite floats with JSON null in remaining diagnostics, preserving finite values and
existing malformed-Unicode handling. Tests exercise the actual analytics and
public-trial ASGI routers with strict fake persistence and registered handlers.
No real PostgreSQL write or production request was made; JSONB impact remains
supported by the binder/database contract and isolated persistence simulation.

## Separately verified query bypass

`POST /analytics/track/compilation` previously accepted non-finite
`compilation_time` query values, bypassing the request-body policy. Its existing
optional float now uses `Query(default=None, allow_inf_nan=False)`. No new
nonnegative/range restriction was introduced and the LLM optimization path was
not changed.

The exact same ten-case ASGI regression was run against the pre-query-fix
parent `4230fb39` and the repaired source. It uses the actual route and error
handlers, a no-database dependency, and an instrumented strict fake service
persistence boundary; it does not invoke a real database or provider.

- Baseline: **4 finite/omitted controls passed, 6 non-finite controls failed**
  because the values reached the fake service boundary and became HTTP 500.
- Fixed: positive, zero, negative finite and omitted values retain HTTP 201.
  NaN, lowercase nan, both infinities and both signed overflowing exponents
  return HTTP 422; the service is never called for rejected values.
- Root independent affected-suite run: **41 passed in 2.34s**, including query,
  body-policy and error-envelope tests. Scoped Ruff and diff checks passed.

Retained evidence:

- `/tmp/latexy-1800-compilation-query-red-20261007.log` — initial discovery.
- `/tmp/latexy-1800-compilation-query-baseline-20261007.log` — exact regression
  against the immutable pre-query-fix parent; failures are not erased by green.
- `/tmp/latexy-1800-compilation-query-root-focused-20261007.log` — independent
  repaired affected-suite run, with `SKIP_INFRA_CHECK=1` and no Redis reset.

Fresh remote CI and actual Modal deployment verification are still required
after this non-finite input/query fix is integrated. Local acceptance is not
live acceptance.

## Refreshed-base focused revalidation

The fixes and targeted tests were reapplied on refreshed #1792 head
`722c4c06e6c8981f00ee4041fe0dd0f742505836`. A strict synthetic-secret
regression first failed on the unsanitized validation handler: the actual
public-trial ASGI route returned HTTP 422 but echoed the rejected request under
`details[0].input`, including synthetic token, password, and resume-content
values. The handler now omits raw `input` and validator `ctx` fields from
standard request-validation details while preserving field location, error
type, and message; the 422 envelope remains intact.

After that change, the three focused modules passed **41 tests** under the
existing local Python 3.12.10 virtual environment with `SKIP_INFRA_CHECK=1`:
`test_analytics_nonfinite_query.py`, `test_public_trial_input_bounds.py`,
and `test_error_envelope.py`. Coverage includes actual ASGI body and query
admission, strict fake persistence, finite and non-finite values, JSON-safe
diagnostics, and absence of synthetic credentials/private resume content from
422 bodies. Ruff passed on all six changed Python files. No database or
provider writes occurred; remote CI and live deployment remain unverified.

## Root refreshed-base complete-backend checkpoint

Root independently ran the complete backend suite in this isolated checkout
against local test PostgreSQL and dedicated Redis databases 15/14. Result:
**4,298 passed / five skipped / one existing Starlette deprecation warning** in
488.77s. Artifact: `/tmp/latexy-nonfinite-1800-root-full-backend-20261007.log`.
The refreshed focused run separately passed **41 tests in 8.43s**:
`/tmp/latexy-nonfinite-1800-root-refresh-tests-20261007.log`.

This complete run was at the refreshed #1792 tree, equivalent to merged main
`91d1f683`, before a subsequent documentation-only handler comment update and
one direct diagnostic-normalization unit test were added. Final focused tests,
including sensitive-error redaction, passed **51 tests in 2.47s**; scoped Ruff
passed. Artifact: `/tmp/latexy-nonfinite-1800-root-final-focused-20261007.log`.
Fresh remote CI is still required; this is not a claim about a newer integrated
main or production deployment. Dedicated test-database writes
are distinct from the fake-persistence focused tests and production.

After seven one-file commits and normal rebase onto main
`bbb2b49faf8216b304161e2d097311c277125d4b` (including merged CI cancellation
repair #1824), root's final integrated run passed **143 tests in 11.75s**:
the affected modules, sensitive-error redaction, and all deployment manifest
regressions. Scoped Ruff passed; the branch differs from main in only the seven
intended code/test/evidence paths. Artifact:
`/tmp/latexy-nonfinite-1800-root-main-integrated-focused-20261007.log`.
Fresh protected CI and deployed acceptance remain required.

## Historical complete-backend checkpoint

An earlier candidate's full Python3.12.10 run passed **4,294 tests / 5 skips /
1 existing Starlette deprecation warning**, in 212.57s:

```sh
PYTHONPATH=backend /Users/sanskar/Developer/Latexy/Latexy/backend/.venv/bin/python \
  -m pytest -q -o addopts='' backend/test
```

Evidence: `/tmp/latexy-1800-query-full-backend-root-corrected-20261007.log`.
That backend snapshot predates hydration main `787b9351` and the refreshed
#1792 base; it does not certify the current preparation, remote CI, or
deployment.

The first full invocation omitted `PYTHONPATH` while running from the repository
root. It produced **4,291 passes / 3 failures / 5 skips**: three subprocess-based
publication regex tests could not import `app`, rather than timing out or
failing their parser assertions. The direct child-process probe confirmed
`ModuleNotFoundError`; the unchanged three cases then passed in 1.30s with the
correct import path. No parser code, deadline, assertions or test selection was
weakened. Preserve the original failure and controls:

- `/tmp/latexy-1800-query-full-backend-root-20261007.log`
- `/tmp/latexy-1800-query-root-subprocess-import-probe-20261007.log`
- `/tmp/latexy-1800-query-root-regex-cwd-control-20261007.log`
