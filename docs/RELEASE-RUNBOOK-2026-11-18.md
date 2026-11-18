# Release Runbook — 2026-11-18

> **Procedure only — not executed and not an approval.** The ledger decision is
> still **HOLD**. A free invite-only beta is a recommendation, not an approved
> launch. This runbook mutates production. Execute it only with a named release
> owner, a second reviewer, an approved production change freeze, and recorded
> owner authorization. Do not run it to "see what happens."

This is the operator procedure for a held backend cutover from the serving
revision to the frozen `main` target, followed by an explicit release. It does
not cover legal copy, the beta gate, paid billing or capacity acceptance. Those
are separate owner decisions.

Current provenance is incomplete: the serving backend
`4b0729f331edfae92eba81aaec8d1e30897ea33c` has no recorded workflow run that
executed deploy steps, and the approvals/drain variables still name older
sources. This runbook replaces that state; reading it is not evidence that any
step has been executed.

Run one fenced block at a time. Read the warning above each destructive block.
Use PowerShell 7+ on Windows with `git`, `gh` and `modal` authenticated. Do not
paste secrets, connection strings, tokens or customer data into shell history or
the release record.

## 1. Authority and stop conditions

Do not start if any of these is true:

- The release owner has not recorded the exact target, scope, exclusions and
  observation window.
- A production change freeze is not in force, or another operator may deploy
  during the window.
- `origin/main` has moved from the frozen target. Re-approve before proceeding.
- Canonical CI is not green for the exact target.
- The frontend production identity is not the same source as the backend target.
- The fresh baseline `/health` is not `healthy`, `/readyz` is not 200, or
  `/jobs/health` is not `healthy`. **A 503 `/readyz` is a hard stop.** Do not
  start a cutover to fix a Redis or readiness incident.
- The recovery image, fresh recovery point and public artifact readers have not
  been independently verified for this exact candidate.
- The Redis handover variable has not been cleared. See section 4; this is the
  trap that fails a held cutover after migration.
- The Redis capacity/observability blocker (#1628) is not dispositioned for the
  intended release. An unconfigured capacity probe is not a pass; if this release
  opens user traffic, OPS/PRODUCT must explicitly accept or resolve it.
- Billing is not confirmed disabled. This procedure never enables live sales.
- If this release is intended to open a user-facing beta or launch, the
  legal/public-copy and beta-gate blockers are not dispositioned for the
  intended audience.

Do not use a local `modal deploy` or `modal serve` against production as a
shortcut. The workflow is the only supported production path; `modal app stop`
is used here only for the drain step. If the GitHub `Production` environment has
required reviewers, the named reviewer must approve the run; do not bypass
environment protection.

Known state at authoring time: the audit snapshot recorded all three health
endpoints 200. A transient read-only re-probe at **2026-11-18 14:21 UTC** found
`/health` degraded with Redis unavailable, `/readyz` 503 and `/jobs/health`
unhealthy; a follow-up at **14:38 UTC** returned healthy/ready with database,
Redis and storage `ok`. The transient cause is unexplained and
`redis_capacity.status` remains `unconfigured`. Re-check at the start and stop
if readiness fails again; recovery from one probe is not a capacity pass.

## 2. Frozen release variables

```powershell
$Repo        = "sanskarpan/Latexy"
$TargetSha   = "19d11cea92696d3ac21d1a6743b8f9068cec8add"
$RollbackSha = "e9ddb1d76971c0d6934d83875a5879146e3d51a3"
$Backend     = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"
$Frontend    = "https://latexy.xyz"
$ModalEnv    = "main"
$ModalApp    = "latexy-backend"
$OldAppId    = "ap-zCH8YOYYRADWBr1Lyva5PL"   # observed 2026-11-18; re-check below
```

- `$TargetSha` is the frozen `main` source. Do not substitute a newer SHA inside
  an approved window.
- `$RollbackSha` was validated locally as an ancestor of the target, with the
  required source guards and green CI. That is not proof that a deployable
  recovery image exists; the operator attestation below remains required.
- `$OldAppId` must be re-checked against the serving App. The workflow binds by
  App ID, not by the human-readable description.

## 3. Read-only preflight

### 3.1 Confirm the frozen source and canonical CI

```powershell
git fetch origin main --prune
$mainSha = (git rev-parse origin/main).Trim()
if ($mainSha -ne $TargetSha) { throw "origin/main is $mainSha, not the frozen target; stop and re-approve" }

$ciJson = gh run list --repo $Repo --workflow ci.yml --branch main --limit 30 --json headSha,conclusion,createdAt
$ci = @($ciJson | ConvertFrom-Json)
$green = @($ci | Where-Object { $_.headSha -eq $TargetSha -and $_.conclusion -eq "success" })
if ($green.Count -eq 0) { throw "No successful canonical CI run for $TargetSha; stop" }
$green | Format-Table headSha,conclusion,createdAt -AutoSize
```

Confirm from the release record that the last frontend-touching run was green on
Cross-Browser Quality and the last backend-touching run was green on Backend
Tests. A green aggregate run with skipped jobs is not a pass for those jobs.

### 3.2 Confirm frontend and backend identities

```powershell
$identity = Invoke-RestMethod "$Frontend/api/deployment-identity" -TimeoutSec 30
$identity | Format-List
if ($identity.commitSha -ne $TargetSha) {
    throw "Frontend identity is $($identity.commitSha), not $TargetSha; stop"
}

function Get-DeploymentProbe {
    param([Parameter(Mandatory)][string]$Path)
    $response = Invoke-WebRequest -Uri "$Backend$Path" -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 30
    [pscustomobject]@{
        Path           = $Path
        StatusCode     = [int]$response.StatusCode
        DeploymentHold = [string]$response.Headers['X-Latexy-Deployment-Hold']
        Body           = $response.Content
    }
}

$health = Invoke-RestMethod "$Backend/health" -TimeoutSec 30
$health | Format-List

$healthProbe = Get-DeploymentProbe "/health"
$ready       = Get-DeploymentProbe "/readyz"
$jobs        = Get-DeploymentProbe "/jobs/health"
@($healthProbe, $ready, $jobs) | Format-Table Path,StatusCode,DeploymentHold -AutoSize
```

Hard stops:

```powershell
if ($health.status -ne "healthy") { throw "Baseline /health is '$($health.status)'; stop" }
if ($health.redis -ne "ok" -or $health.redis_cache -ne "ok") { throw "Redis is not healthy; stop" }
if ([int]$ready.StatusCode -ne 200) { throw "Baseline /readyz is $($ready.StatusCode); stop" }
if (($jobs.Body | ConvertFrom-Json).status -ne "healthy") { throw "Baseline /jobs/health is not healthy; stop" }
if ($healthProbe.DeploymentHold -ne "false") { throw "Baseline hold is '$($healthProbe.DeploymentHold)', not false; stop and re-assess" }
if ($health.redis_capacity.status -eq "unconfigured") {
    Write-Warning "Redis capacity is unconfigured (#1628); this is a known launch blocker, not a capacity acceptance."
}
```

Record the current backend `commit_sha`, Redis binding fingerprint and flight
recorder output in the release record. The expected current serving revision is
`4b0729f331edfae92eba81aaec8d1e30897ea33c`, which is 16 commits behind the
target. The existing released process is expected to report
`X-Latexy-Deployment-Hold: false`; record that baseline, but do not confuse it
with the held candidate you will verify in section 7.

### 3.3 Re-check the serving Modal App

```powershell
$apps = @(modal app list --env $ModalEnv --json | ConvertFrom-Json)
$apps | Format-Table app_id,description,state,tasks,created_at -AutoSize

$old = @($apps | Where-Object { $_.app_id -eq $OldAppId })
if ($old.Count -ne 1) { throw "Expected exactly one row for $OldAppId; stop and re-identify the App" }
$old | Format-List app_id,description,state,tasks,created_at
if ($old[0].description -ne $ModalApp) { throw "App description is '$($old[0].description)'; stop" }
if ($old[0].state -eq "stopped") { throw "The App is already stopped; stop and re-assess the incident before continuing" }
```

The description is for human confirmation only. The workflow resolves the App
name through Modal's API and binds the drain record by App ID. Keep this
PowerShell session open; later sections reuse `$Backend` and the
`Get-DeploymentProbe` function defined above.

### 3.4 Check repository and Production environment variable scopes

```powershell
gh variable list --repo $Repo
gh variable list --repo $Repo --env Production
gh variable list --repo $Repo | Select-String '^MODAL_ENGINE_VM_'
```

Environment-scoped variables override repository variables. If any of the
approval, drain, handover or Redis-secret variables exist in both scopes, update
the scope that actually wins. Do not set a value in one scope and assume the
other is irrelevant.

Confirm `MODAL_ENGINE_VM_CERTIFIED`, `MODAL_ENGINE_VM_IMAGE_ID` and
`MODAL_ENGINE_VM_ASSETS_FINGERPRINT` match the approved renderer certification.
Do not invent, rotate or "refresh" them as part of this runbook.

Also confirm `MODAL_REDIS_SECRET_NAME` is absent or still `latexy-redis`. If it
names a different binding, stop: an alternate binding can enter the freeze path
even after the handover variable is cleared.

## 4. Clear the stale release approval and the handover trap

> **Operator-only and critical.** Redis authority is already on the spare
> (phase `spare`). With `MODAL_REDIS_HANDOVER_ID` set, the held cutover runs the
> freeze step, which requires phase `legacy`, and fails **after** the migration
> step. Clear the variable before dispatch. The observed stale value is
> `a95f9bcb-df73-4662-96cb-bf8ba12358d9`; any non-empty value must be cleared,
> not just this one.

```powershell
# Remove the stale release approval. It names 4b0729f3, not the frozen target.
gh variable delete MODAL_TRAFFIC_RELEASE_APPROVED_SHA --repo $Repo

# Clear the handover trap. Do not re-set it while the spare is authoritative.
gh variable delete MODAL_REDIS_HANDOVER_ID --repo $Repo

$vars = @(gh variable list --repo $Repo) + @(gh variable list --repo $Repo --env Production)
if ($vars | Select-String -Pattern '^MODAL_REDIS_HANDOVER_ID\s') {
    throw "MODAL_REDIS_HANDOVER_ID is still present in repository or Production scope; stop"
}
if ($vars | Select-String -Pattern '^MODAL_TRAFFIC_RELEASE_APPROVED_SHA\s') {
    throw "Stale MODAL_TRAFFIC_RELEASE_APPROVED_SHA is still present in repository or Production scope; stop"
}
```

These commands target repository scope. If section 3.4 showed the same variable
in the Production environment scope, repeat the delete with `--env Production`
and verify there; the environment value wins.

A `gh variable delete` exit code of 1 can mean the variable was already absent.
The list check above is the authoritative confirmation. Do not "fix" a missing
variable by setting it.

`MODAL_REDIS_RECOVERY_FREEZE_ID` may remain set. With the default binding and no
handover ID, the freeze step is skipped. Do not set a new freeze ID unless a
separately authorized freeze procedure is intended.

## 5. Set candidate-scoped cutover and recovery approvals

> **Operator attestation — not automated evidence.** Setting
> `MODAL_RECOVERY_VERIFIED_FOR_SHA` asserts that you independently verified a
> deployable recovery image, a fresh recovery point, and every public artifact
> reader for this exact candidate. The workflow does not verify those facts. If
> you cannot attest them, stop.

```powershell
if ($RollbackSha -eq $TargetSha) { throw "Rollback SHA equals target; stop" }
git merge-base --is-ancestor $RollbackSha $TargetSha
if ($LASTEXITCODE -ne 0) { throw "Rollback SHA is not an ancestor of target; stop" }

gh variable set MODAL_SCHEMA_CUTOVER_APPROVED_SHA --repo $Repo --body $TargetSha
gh variable set MODAL_RECOVERY_VERIFIED_FOR_SHA --repo $Repo --body $TargetSha
gh variable set MODAL_FORWARD_ROLLBACK_SHA --repo $Repo --body $RollbackSha

gh variable list --repo $Repo | Select-String -Pattern 'MODAL_(SCHEMA_CUTOVER_APPROVED_SHA|RECOVERY_VERIFIED_FOR_SHA|FORWARD_ROLLBACK_SHA|TRAFFIC_RELEASE_APPROVED_SHA|REDIS_HANDOVER_ID)'
gh variable list --repo $Repo --env Production | Select-String -Pattern 'MODAL_(SCHEMA_CUTOVER_APPROVED_SHA|RECOVERY_VERIFIED_FOR_SHA|FORWARD_ROLLBACK_SHA|TRAFFIC_RELEASE_APPROVED_SHA|REDIS_HANDOVER_ID)'
```

These commands target repository scope. If section 3.4 showed environment-scoped
overrides for these variables, set the same values with `--env Production` as
well; otherwise an old environment value can win.

The workflow re-checks rollback ancestry, source guards and rollback CI. Those
checks do not prove image availability. Keep the recovery evidence private and
access-controlled.

## 6. Drain window — stop the App and dispatch held

> **Destructive and time-bound.** This block stops the serving App, records the
> drain within the 300-second gate, and dispatches the held cutover. Production
> product traffic is unavailable from the stop until the held candidate starts.
> Do not run this block until the change freeze, recovery point, drain evidence,
> approvals and rollback plan are all recorded. If the dispatch fails after the
> stop, production is down: fix the dispatch immediately or escalate to the
> incident owner. If the Production environment requires approval, the reviewer
> must approve immediately; approval delay counts against the 300-second drain
> gate.

The timestamp must be the actual completion time of the external drain
procedure. Do not backdate it, refresh it without repeating the procedure, or
fabricate the evidence reference. The gate is a trusted operator pointer, not
authentication of the external work.

Before running, replace `<change-ticket>` and `<private-reference>` in the
evidence string. Do not put a token, password, connection string or customer
document in the reference. The block refuses to run while a placeholder remains.
If any deploy or App change happened since section 3.3, repeat section 3.3
first; do not stop a stale App ID.

```powershell
$DrainEvidence = "release-2026-11-18/<change-ticket>: $ModalApp $OldAppId stopped; production change freeze held; queued/in-flight work reconciled per the approved drain procedure; evidence record <private-reference>"
if ($DrainEvidence -match '<') { throw "Replace <change-ticket> and <private-reference> before dispatch" }

$confirm = Read-Host "Type DRAIN to stop $OldAppId and dispatch traffic_mode=held"
if ($confirm -ne "DRAIN") { throw "Aborted" }

modal app stop $OldAppId --env $ModalEnv --yes

Start-Sleep -Seconds 5
$after = @(modal app list --env $ModalEnv --json | ConvertFrom-Json |
    Where-Object { $_.app_id -eq $OldAppId })
if ($after.Count -eq 1 -and $after[0].state -ne "stopped") {
    throw "App state is '$($after[0].state)', not stopped; stop"
}

$DrainCompletedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

gh variable set MODAL_DRAIN_PROCEDURE_APPROVED_FOR_SHA --repo $Repo --body $TargetSha
gh variable set MODAL_DRAIN_PROCEDURE_APP_ID --repo $Repo --body $OldAppId
gh variable set MODAL_DRAIN_PROCEDURE_COMPLETED_AT --repo $Repo --body $DrainCompletedAt
gh variable set MODAL_DRAIN_PROCEDURE_EVIDENCE_REFERENCE --repo $Repo --body $DrainEvidence
gh variable list --repo $Repo | Select-String '^MODAL_DRAIN_PROCEDURE_'

gh workflow run deploy-modal.yml --repo $Repo --ref main -f ref=$TargetSha -f traffic_mode=held
```

If section 3.4 showed Production-scoped drain variables, repeat the four
`gh variable set` commands with `--env Production` before dispatching. The
environment value wins.

Immediately capture the run:

```powershell
Start-Sleep -Seconds 5
$runJson = gh run list --repo $Repo --workflow deploy-modal.yml --branch main --limit 1 --json databaseId,headSha,event,status,conclusion,createdAt
$run = @($runJson | ConvertFrom-Json)
$run | Format-Table databaseId,headSha,event,status,conclusion,createdAt -AutoSize
$runId = $run[0].databaseId
gh run watch $runId --repo $Repo --exit-status
if ($LASTEXITCODE -ne 0) { throw "Held cutover failed; do not release. Inspect the failed step." }
```

If the run fails before migration at the drain gate, the App is still stopped.
Verify that the external procedure is still valid before re-dispatching. Do not
edit the timestamp to make a stale record pass. If the run fails at or after the
migration step, stop and use section 11; do not simply retry the held cutover.

## 7. Verify the held candidate

The workflow's final health check already requires the hold header and statuses.
Verify independently before approving release.

```powershell
$health = Invoke-RestMethod "$Backend/health" -TimeoutSec 30
$health | Format-List

if ($health.status -ne "healthy") { throw "Held /health is '$($health.status)'" }
if ($health.commit_sha -ne $TargetSha) { throw "Held backend is $($health.commit_sha), not target" }
if ($health.redis -ne "ok" -or $health.redis_cache -ne "ok") { throw "Held Redis is not healthy" }

$healthProbe = Get-DeploymentProbe "/health"
$readyProbe  = Get-DeploymentProbe "/readyz"
$jobsProbe   = Get-DeploymentProbe "/jobs/health"
@($healthProbe, $readyProbe, $jobsProbe) | Format-Table Path,StatusCode,DeploymentHold -AutoSize

if ($healthProbe.DeploymentHold -ne "true" -or
    $readyProbe.DeploymentHold -ne "true" -or
    $jobsProbe.DeploymentHold -ne "true") {
    throw "One or more held probes did not return X-Latexy-Deployment-Hold: true"
}
if ([int]$readyProbe.StatusCode -ne 200) { throw "Held /readyz is $($readyProbe.StatusCode)" }
if (($readyProbe.Body | ConvertFrom-Json).status -ne "ready") { throw "Held /readyz is not ready" }
if (($jobsProbe.Body | ConvertFrom-Json).status -ne "healthy") { throw "Held /jobs/health is not healthy" }

$product = Get-DeploymentProbe "/resumes"
$productBody = $null
try { $productBody = $product.Body | ConvertFrom-Json } catch { }
@($product, $productBody) | Format-List
if ([int]$product.StatusCode -ne 503 -or $productBody.code -ne "deployment_traffic_held") {
    throw "Product path is not held with the expected 503 body; stop"
}

$catalog = @(Invoke-RestMethod "$Backend/templates/" -TimeoutSec 30)
Write-Host "Held public template count: $($catalog.Count) (audit snapshot: 61)"
```

Record the held run ID, App ID, backend `commit_sha`, all hold headers, the
product-path 503 body, health bodies and template count. Do not set the release
approval until the release owner has reviewed this evidence and accepted the
remaining risks.

## 8. Set the release approval and dispatch release

> **Operator-only release decision.** This does not authorize live billing. Dodo
> must remain disabled throughout.

```powershell
$confirm = Read-Host "Type RELEASE to approve $TargetSha and dispatch traffic_mode=release"
if ($confirm -ne "RELEASE") { throw "Aborted" }

gh variable set MODAL_TRAFFIC_RELEASE_APPROVED_SHA --repo $Repo --body $TargetSha
gh variable list --repo $Repo | Select-String -Pattern '^MODAL_TRAFFIC_RELEASE_APPROVED_SHA\s'

gh workflow run deploy-modal.yml --repo $Repo --ref main -f ref=$TargetSha -f traffic_mode=release
```

Capture and watch the run:

```powershell
Start-Sleep -Seconds 5
$runJson = gh run list --repo $Repo --workflow deploy-modal.yml --branch main --limit 1 --json databaseId,headSha,event,status,conclusion,createdAt
$run = @($runJson | ConvertFrom-Json)
$run | Format-Table databaseId,headSha,event,status,conclusion,createdAt -AutoSize
$runId = $run[0].databaseId
gh run watch $runId --repo $Repo --exit-status
if ($LASTEXITCODE -ne 0) { throw "Release failed; the candidate should remain held. Inspect before any retry." }
```

The release phase re-verifies the held candidate identity, hold header and fresh
health before redeploying the same source with the hold disabled. It does not
repeat the old-App drain gate or the database migration. On success, retain
`MODAL_TRAFFIC_RELEASE_APPROVED_SHA` at the target; it prevents an automatic CI
rerun for the same SHA from silently re-holding the released application.

## 9. Verify the released service

```powershell
$health = Invoke-RestMethod "$Backend/health" -TimeoutSec 30
$health | Format-List

if ($health.status -ne "healthy") { throw "Released /health is '$($health.status)'" }
if ($health.commit_sha -ne $TargetSha) { throw "Released backend is $($health.commit_sha), not target" }
if ($health.redis -ne "ok" -or $health.redis_cache -ne "ok") { throw "Released Redis is not healthy" }
if ($health.redis_capacity.status -eq "unconfigured") {
    Write-Warning "Redis capacity remains unconfigured (#1628); this release does not accept capacity risk."
}

$healthProbe = Get-DeploymentProbe "/health"
$readyProbe  = Get-DeploymentProbe "/readyz"
$jobsProbe   = Get-DeploymentProbe "/jobs/health"
$product     = Get-DeploymentProbe "/resumes"
@($healthProbe, $readyProbe, $jobsProbe, $product) | Format-Table Path,StatusCode,DeploymentHold -AutoSize

if ($healthProbe.DeploymentHold -ne "false" -or
    $readyProbe.DeploymentHold -ne "false" -or
    $jobsProbe.DeploymentHold -ne "false") {
    throw "A released probe still reports the deployment hold"
}
if ([int]$readyProbe.StatusCode -ne 200) { throw "Released /readyz is $($readyProbe.StatusCode)" }
if (($readyProbe.Body | ConvertFrom-Json).status -ne "ready") { throw "Released /readyz is not ready" }
if (($jobsProbe.Body | ConvertFrom-Json).status -ne "healthy") { throw "Released /jobs/health is not healthy" }
if ([int]$product.StatusCode -eq 503 -or $product.Body -match 'deployment_traffic_held') {
    throw "Product traffic is still held"
}
if ([int]$product.StatusCode -notin @(401, 403)) {
    Write-Warning "Expected an authentication response on /resumes; got $($product.StatusCode). Verify the route manually."
}

$identity = Invoke-RestMethod "$Frontend/api/deployment-identity" -TimeoutSec 30
if ($identity.commitSha -ne $TargetSha) { throw "Frontend identity changed during release" }

$plans = Invoke-RestMethod "$Backend/subscription/plans" -TimeoutSec 30
if ($plans.billing.feature_enabled -ne $false -or $plans.billing.available -ne $false) {
    throw "Billing is not safe-disabled; stop and escalate"
}
if ($plans.billing.mode -ne "disabled") {
    throw "Billing mode is '$($plans.billing.mode)', not 'disabled'; stop and escalate"
}
$plans.billing | Format-List
```

A released product path should return an ordinary authentication response (401
or 403), not a 503 with `deployment_traffic_held`. A 401 is not proof that every
product path works; it only shows the hold is no longer rejecting the request.

## 10. Post-release smoke list

Run against `https://latexy.xyz` and the backend after the release run is green.
Use synthetic data. Record the exact timestamp, source identities and results.

- [ ] Public pages `/`, `/pricing`, `/templates`, `/try`, `/login`, `/faq`,
  `/privacy` and `/terms` return 200.
- [ ] `/api/deployment-identity` still returns the target frontend SHA.
- [ ] `/health` is `healthy`, `/readyz` is `ready` and `/jobs/health` is
  `healthy`; the hold header is `false` on all three.
- [ ] Database, Redis, Redis cache and storage report `ok`. Record
  `redis_capacity.status`; `unconfigured` is still a launch blocker, not a pass.
- [ ] The public catalogue reports the expected count (audit snapshot: 61) and
  at least three templates return both thumbnail and PDF bytes.
- [ ] Guest `/try` compile produces a PDF; happy path, validation error and
  exhausted-quota state behave as intended.
- [ ] Signup/login works only through the approved invite/beta gate. If the beta
  gate is not approved, do not treat open signup as accepted.
- [ ] Workspace create, save, hard reload, compile and PDF download work.
- [ ] ATS quick, optimize, cover letters, share link and settings pass their
  agreed smoke cases. Deep ATS, file import, purchases, teams/tenants,
  outreach/email parser/apply, extension, integrations, developer API, interview
  simulation, package manager, Canva/Figma and email PDF remain gated if the
  free-beta scope is in force.
- [ ] Billing shows the disabled state with no purchasable SKU; free quotas show
  10 compiles/day, 3 optimizations/month and 25 AI assists/month; Basic shows
  400/10/100.
- [ ] No new 5xx spike, duplicate job, duplicate charge, cross-owner access or
  stuck admitted job in the observation window (minimum 30 minutes; extend for
  any anomaly).
- [ ] Template sync/backfill and the release run both completed; no skipped
  required step is reported as a pass.

## 11. Rollback and containment

Do not run a destructive schema downgrade as a reflex. Preserve the advanced
schema and financial history.

- **Failure before migration:** restore service only through a separately
  approved procedure. Do not reactivate a legacy writer or an unfiltered
  artifact reader. The last serving revision before the cutover was
  `4b0729f3`; verify its state and compatibility before any restore, and record
  the approval.
- **Failure at or after migration:** keep the advanced schema. Use the verified
  forward-compatible recovery build (`MODAL_FORWARD_ROLLBACK_SHA`, currently
  `e9ddb1d76971c0d6934d83875a5879146e3d51a3`) only after independently verifying
  its image, artifact readers and startup. Do not relabel suspect financial rows
  or rerun the old backfill.
- **Held cutover failed at the handover/freeze step:** migration may already have
  applied. Do not retry the held cutover blindly. Confirm the handover variable is
  cleared, inspect the failed step, and follow the forward-recovery path with the
  recovery owner.
- **Release failed:** verify the actual hold state. If the candidate is still
  held, keep product traffic unavailable, fix forward or use the recovery build,
  and do not set the release approval again without repeating the held
  verification. If it is already unheld, contain and verify before any retry.
- **Redis/readiness incident:** keep sales disabled and do not start a cutover to
  "fix" readiness. Restore/confirm Redis, preserve unknown quotas and receipts,
  and follow the Redis recovery contract and capacity runbook.
- **Suspected credential exposure:** use the private security procedure. Do not
  put credentials or private diagnostics in the release record.

## 12. Evidence to retain

Record, in the private release record:

- Release owner, reviewer, change-ticket ID, change-freeze window and approval.
- Frozen target SHA, frontend identity, old and new backend `commit_sha`, old and
  new Modal App IDs.
- Canonical CI run ID, held run ID, release run ID, timestamps and conclusions.
- The four drain variables as set, the actual drain completion time and the
  private evidence reference.
- Held verification: all three hold headers, health/readiness/jobs bodies,
  product-path 503 body, template count.
- Released verification: hold `false`, health/readiness/jobs bodies, billing
  disabled state, public-page results and smoke results.
- Rollback decision, recovery attestation, residual risks and observation window.
- Any incident, failed step, retry or deviation from this runbook.

Do not attach tokens, passwords, connection strings, customer documents, raw
environment dumps or logs containing user data.

## 13. Explicit operator-only attestations

The workflow cannot verify these. Do not represent them as automated:

- **Recovery:** `MODAL_RECOVERY_VERIFIED_FOR_SHA` is your assertion that the
  recovery image, fresh recovery point and public artifact readers are usable for
  this exact candidate.
- **Drain:** the four `MODAL_DRAIN_PROCEDURE_*` values are a trusted pointer. The
  workflow checks SHA equality, App ID/state, a timestamp no more than 300
  seconds old and a nonempty reference. It does not authenticate the external
  procedure or prove that queued/in-flight work settled.
- **Release:** `MODAL_TRAFFIC_RELEASE_APPROVED_SHA` is the release owner's
  decision for this exact candidate. It is not a test result.
- **Capacity:** configuring the Redis capacity probe and accepting monthly
  capacity/exhaustion risk is an operator/product decision; this runbook does not
  configure it.
- **Legal and beta scope:** correcting Terms/contact channels and approving an
  invite gate are separate owner decisions; this runbook does not perform them.

If any attestation is unavailable, stop. A green workflow is not a substitute
for an owner decision.
