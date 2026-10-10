The isolated real guest preview admitted normally but failed before TeX when
Celery interrupted the first native `asyncpg.protocol.protocol` import. The child
raised `SystemError` and was killed. Earlier Windows-bound source also timed out
during render-policy import. Failed browser evidence is preserved in PR #1833.

Reproduce with a fresh prefork worker, frozen Linux source, ordinary guest field
save and unchanged task/compiler deadlines. Warm eager benchmarks do not exercise
this first-task import condition. Do not flush quota databases or extend deadlines.

Fix implemented in e77df27e: prepare required modules in parent `worker_init`
before pool/deadline setup; fail readiness on dependency errors. Modal entrypoints
prepare before eager execution. Connections, client creation and ownership remain
scoped to the existing child/job lifecycle.

Both startup regressions passed in the 138-case real PostgreSQL/Redis run.
Acceptance still requires the real first guest task/PDF, final-head CI, and
independent cloud cold-start proof. Parent migration epic: #1814. Keep this issue
open until its acceptance is recorded and the reviewed change is merged.
