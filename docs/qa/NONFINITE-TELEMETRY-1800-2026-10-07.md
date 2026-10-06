# Non-finite telemetry — focused local acceptance

Issue #1800 remains unpublished. This candidate is based on the reviewed,
rebased input-bounds PR #1792 at `45bc198c9cccd07888fdaa046cb4f0da6034144a`.
Only its four previously reviewed non-finite metadata/error-envelope commits
were transplanted, followed by the separately verified query ingress repair.

## Body metadata and validation diagnostics

The shared policy rejects nested NaN/Infinity/-Infinity before persistence
using `json.dumps(..., allow_nan=False)`. Registered exception handlers replace
non-finite floats with JSON null in diagnostics, preserving finite values and
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
after the dependency PR is merged. Local acceptance is not live acceptance.

## Complete backend checkpoint

Root's full Python3.12.10 run on this candidate passed **4,294 tests / 5 skips /
1 existing Starlette deprecation warning**, in 212.57s:

```sh
PYTHONPATH=backend /Users/sanskar/Developer/Latexy/Latexy/backend/.venv/bin/python \
  -m pytest -q -o addopts='' backend/test
```

Evidence: `/tmp/latexy-1800-query-full-backend-root-corrected-20261007.log`.
This backend snapshot predates hydration main `787b9351`; it does not certify
subsequent edits, remote CI, or deployment.

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
