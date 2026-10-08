# Cold worker preparation — October 8, 2026

The real guest browser probe reached ordinary quota admission, then failed before
TeX began. The Windows-bound worker timed out during a render-policy module
import. After moving isolated QA source to a frozen Linux volume, a fresh prefork
child instead received Celery's task time-limit signal while importing the native
`asyncpg.protocol.protocol` extension. It raised a `SystemError` and the child
was killed. These failed attempts remain in the dated browser reports.

The worker now loads the native driver, SQLAlchemy dialect and render
cache/artifact/retention/geometry modules in Celery's parent `worker_init` phase,
before the pool and task deadlines exist. Semantic service imports are prepared
when that capability is enabled. The memoized helper creates no connection,
database engine, provider client or renderer VM. Per-child Redis initialization
and per-job owner/epoch/client isolation remain in their existing lifecycle.
Modal's worker entrypoint calls the helper before eager task execution too.

Celery signal dispatch catches ordinary exceptions. Preparation failure therefore
raises `WorkerTerminate`, preventing readiness instead of consuming jobs after
an incomplete import. Failed preparation is not memoized and can recover after
the dependency problem is corrected. The installed Celery `WorkController`
dispatches `worker_init` before applying the worker blueprint/pool.

Both regressions passed in the **138-case** real PostgreSQL/Redis run: startup
loads the actual native module without calling connection/engine factories, and
a synthetic missing dependency aborts readiness then permits successful recovery.
An earlier standalone test command misspelled `SKIP_INFRA_CHECK` and omitted
isolated Redis URLs; both cases failed setup, not their assertions. The corrected
combined run kept infrastructure checks enabled.

The isolated fresh worker using frozen backend tree
`afca6ba3fe9e1c607874928a56b09d32a8599864` reached normal prefork readiness at
`2026-10-08T14:24:32Z`. Actual user-action/PDF verification is recorded separately
in the release audit. Startup readiness alone is not proof of first-job latency,
cloud cold-start behavior or a percentile target. Task/compiler limits were not
increased.
