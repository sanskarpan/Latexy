# Free / Basic monthly / Basic annual — production journey audit

**Window:** 2026-11-27T10:49:06Z → 2026-11-27T11:18:13Z (UTC)
**Environment:** production backend `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`, frontend `https://latexy.xyz`
**Runtime attestation at window end:** backend `/health` 200 `healthy`, commit `ee1a405de6058e814c3a6f5ffba5fe3630576421`; `/readyz` 200 `ready`; `/jobs/health` 200 `healthy`, all queue depths 0; frontend `/api/deployment-identity` 200 commit `d2cbc51ab8c25106d073e0e0065b985fc6dc6490` (`source: vercel`).
**Rate/spend:** 144 HTTP requests over ~29 minutes (~5/min average; 3.1 s pacing, peak ≤20/min). LLM spend: 2 optimize calls, 2 AI-assist calls, 1 synchronous ATS scoring call, 1 resume-linked compile job. No load loops.

## Identities

| Cohort | User ID | Plan | Role | Status | Session |
|---|---|---|---|---|---|
| free | `96c507cd-e7a2-4749-9153-96b6321742db` | free | user | active | `audit_sess_20261127103328_free` |
| basic-monthly | `0e0b7f8d-e7d0-48da-9e66-dcee3e52f0cb` | basic | user | active | `audit_sess_20261127103328_basic-monthly` |
| basic-annual | `2f49586c-570d-4802-82bc-187ec0a516df` | basic_annual | user | active | `audit_sess_20261127103328_basic-annual` |

Test data is tagged `AUDIT ... 2026-11-27` and the emails carry the `audit+...-20261127103328` suffix.

## Verdict

Core free/basic journeys are **functional**: templates browse/preview/use, resume create/edit/save, direct compile + PDF download, quota charge/refund, AI optimize/assist, ATS scoring, PDF import, DOCX/Markdown export, share links, portfolio publish/view, tracker CRUD, and account/quota reads all returned the expected shapes.

No P0/P1 functional failure was observed for these cohorts. Four findings are recorded in `audit/defects/free-basic.md` (two are cross-cutting duplicates already in the lead register):

- **CAP-01 / P2** — every plan family and role is granted all 149 gateable capabilities, so pricing-tier feature differentiation (e.g. cover letters, saved history) is not enforced.
- **RET-01 / P2** — history retention is displayed (Free `None`, Basic `30 days`) but is copy-only; both cohorts store and serve history identically.
- **FB-03 / P3** — resumes created with “Use template” lose `selected_template_id`, so later compile/export template attribution is null.
- **FB-04 / P3** — one 17.65 s entitlement snapshot (single sample; not reproduced).

Quota-exhaustion 402 behavior was **not exercised** deliberately: the brief forbids exhausting quotas, and all three quota dimensions are single-digit for Free. Limit values, window boundaries, successful charges, and the failure-refund path were verified instead.

## Entitlement and quota baseline

`GET /config/entitlements` returned 200 for all three identities. At the same window, a read-only `GET /admin/entitlements` (admin identity, request `d672c690-6daa-4795-b829-8cab26a179b1`) showed **149/149 gateable capabilities true for every plan family** (`free`, `basic`, `basic_annual`, `pro`, `pro_annual`, `byok`, `byok_annual`, `student`, `team`, `weekly`, `lifetime`) and **for every role** (`anonymous`, `user`, `support`, `admin`). All kill switches were on. This matches the all-enabled seed in migration `0069_capability_catalog`; it is an environment-wide state, not a free/basic-only condition. It is recorded as CAP-01 (lead register; cross-cutting) because it directly determines what an “upgrade prompt” can mean for these cohorts.

| Dimension | Free | Basic monthly | Basic annual |
|---|---|---|---|
| compilations | 10 / **day**, period `20261127`, resets `2026-11-28T00:00Z` | 400 / month, period `202611` | 400 / month, period `202611` |
| optimizations | 3 / month | 10 / month | 10 / month |
| ai_assists | 25 / month | 100 / month | 100 / month |
| historyRetention (copy/API) | `0` (UI renders “None”) | `30` | `30` |
| apiAccess / daily limit | `true` / 10 | `true` / 100 | `true` / 100 |
| prioritySupport | false | false | false |

`GET /subscription/plans` returned the same limits and the expected prices (`free` 0, `basic` ₹299.00 monthly, `basic_annual` ₹2,871.00 yearly). Billing provider Dodo is enabled.

## Journey results

Legend: **PASS** = expected response and shape observed; **PASS\*** = passed with a methodology caveat; **N/E** = intentionally not exercised.

| # | Journey | Result | Evidence (UTC, request ID, latency) |
|---|---|---|---|
| 1 | Health/readiness | PASS | `/health` 200 `healthy` 11:12:07Z `671f2d1c-6099-45ea-b9d8-18319ba194d6` 4,629 ms; `/readyz` 200 `ready` 11:12Z `997d9cad-...` 1,149 ms; `/jobs/health` 200 all queues 0 11:12:14Z `9b125d65-...` 3,580 ms |
| 2 | Session/account read | PASS | `GET /me` 200 for all three; plan/role/status match matrix. Free 10:49:07Z `3a6a4b92-...` 1,173 ms; basic-monthly 10:49:16Z `105d4705-...` 1,171 ms; basic-annual 10:49:40Z `edfa3560-...` 1,133 ms |
| 3 | Entitlement/quota snapshot | PASS\* | 200 for all three; values above. Basic-monthly snapshot at 10:49:36Z `315d56d2-91d1-4620-92bd-b07fe2975e9b` took **17,655 ms** (FB-04); the other 25 snapshots were 1,827-1,987 ms |
| 4 | Templates list/categories | PASS | `GET /templates/` 200, 61 templates 10:49:56Z `8768a1c5-...` 1,587 ms; `GET /templates/categories` 200, 14 categories 10:49:53Z `f0d4c4e9-...` 1,316 ms |
| 5 | Template search/filter | PASS | `?search=ats` 200, 4 ATS-Safe templates 11:09:24Z `719ec0c8-...` 1,502 ms; `?category=minimal` 200, 4 templates, all minimal 11:09:27Z `224f02bb-...` 1,333 ms |
| 6 | Template detail/preview | PASS\* | `GET /templates/{id}` 200 for all three (1.23–1.33 s). Thumbnail/PDF return 307 to R2; direct unauthenticated fetch of the redirect target returned **200 `image/png` 358,640 B** (11:06:47Z) and **200 `application/pdf` 96,149 B** (11:06:49Z). Caveat: when a test client forwards the backend `Authorization` header across the cross-host redirect, R2 correctly rejects the request with `400 Missing x-amz-content-sha256`; browsers do not forward that header. This was a harness artifact, not a product failure |
| 7 | Template view event | PASS | `POST /templates/{id}/events` 201 `{recorded: template_view, plan: free}` 10:53:08Z `54a57ce0-...`; basic 201 `fe3e84d7-...`; annual 201 `0a229081-...` |
| 8 | Use template | PASS | `POST /templates/{id}/use` 200 → free resume `29bf3ac1-f5a5-4cc5-a06a-ba971f727944` (10:53:11Z `2c3b55e7-...`), basic `a06ca085-...` (`7ecad5b6-...`), annual `c896ffca-...` (`48e8637a-...`). Readback 200 with template LaTeX (3,360–3,694 chars); see FB-03 for null `selected_template_id` |
| 9 | Resume create/list/read | PASS | `POST /resumes/` 201 (free 10:55:25Z `444b9d17-...`; basic 10:56:00Z `49d170d4-...`; annual 10:56:12Z `934d1907-...`). `GET /resumes/` 200 with pagination, fixture present; `GET /resumes/{id}` 200 |
| 10 | Resume edit/save | PASS | `PUT /resumes/{id}` without `expected_latex_content` → **428** `precondition_required` (designed optimistic concurrency) 10:55:30Z `5492ce37-...`. Retry with the last-read content → 200, title and marker updated 10:57:16Z `ecaafb78-...` 1,544 ms. Frontend edit page sends the same field (`frontend/src/app/workspace/[resumeId]/edit/page.tsx`) |
| 11 | Direct compile | PASS | `POST /compile` multipart 200 `success: true`; 4/4 successes; 3,162–3,288 ms; PDF 84,144–84,159 B; 10:55:39Z `233fbc81-...` (free), 10:56:08Z `fc979711-...` (basic monthly), 10:56:20Z `9bb2931b-...` (basic annual) |
| 12 | Compile failure/refund | PASS | Invalid command compile 200 `success:false`, 3,070-char log 10:55:55Z `39bf4cb7-...`; free `compilations.used` stayed **1** before and after (refund worked) |
| 13 | PDF download | PASS | `GET /download/{job}` 200 `application/pdf`; free direct job `76f3589a-...` 84,144 B 7,097 ms 10:55:49Z `5fc83495-...`; resume-linked job 84,158 B 3,291 ms 11:04:39Z `7059ffc8-...` |
| 14 | Resume-linked compile job | PASS | `POST /jobs/submit` (`latex_compilation`, `metadata.resume_id`) 200 11:04:09Z `d1648554-...` 3,210 ms; state `queued → processing → completed`; result 200 with artifact manifest (`pdf_sha256`, `pdf_size: 84,158`) 11:04:34Z `1a0ed5ff-...`. Basic-annual `compilations.used` 1 → 2 |
| 15 | AI optimize | PASS | `POST /optimize` 200 `success:true`, optimized LaTeX/changes/ATS present; free 16,014 ms 10:57:37Z `7532d0f1-...`; basic 12,365 ms 10:58:07Z `46014736-...`; each charged 1 optimization |
| 16 | AI assist rewrite | PASS | `POST /ai/rewrite` 200 `{rewritten, action, cached:false}`; free 5,970 ms `d3131aac-...`; basic 4,011 ms `c2e74b0c-...`; each charged 1 `ai_assists` |
| 17 | ATS quick score | PASS | `POST /ats/quick-score` 200 score **71 / C**, keyword match 55%, no missing sections; free `2d499f06-...`, basic `5507e8a3-...`; ~1.5 s |
| 18 | ATS full score | PASS | `POST /ats/score` (`async_processing:false`) 200 `ats_score: 74.2`, 5 category scores, 7 recommendations, 3 warnings, 1,486 ms 10:58:28Z `57219ebd-...` |
| 19 | Export formats | PASS | `GET /export/formats` 200 13 formats 11:00:26Z `81f74438-...`; `GET /export/{id}/docx` 200 `PK\x03\x04` 37,167 B 1,898 ms `b90d6362-...`; `/md` 200 659 B `b4e61f8c-...` |
| 20 | PDF import | PASS | `POST /resumes/imports/pdf` 201 `{import_id, original.sha256, extraction.status: partial, 9 fields, 23 supported templates}` 11:03:33Z `3f086430-...` 1,581 ms; receipt 200 `2afedb5c-...`; `POST .../adapt` 200 created resume `94d72ad3-...` (`source_mode: managed`, 481 chars) `51da9ac9-...`; resume deleted 204. Staged import row then 404 (cascaded with resume deletion) — cleanup completed |
| 21 | Share link | PASS | On a resume with a linked compilation: `POST /resumes/{id}/share` 200 11:04:43Z `ba3c6db8-...`; public `GET /share/{token}` 200 11:04:50Z `cae53a27-...` 4,373 ms, 674-char accessible text, PDF 200 84,158 B; `DELETE` 204 and public token then 404. Without a resume-linked compilation the public view returns 404 “compile your resume first” (expected; direct `/compile` is not resume-bound) |
| 22 | Portfolio publish/view | PASS | `check-username` 200; `POST /portfolio/setup` 200; `PUT /resumes/{id}` `portfolio_visible:true` 200; public `GET /portfolio/audit-free-20261127` 200 with 1 resume 11:01:00Z `a58510b1-...`; unpublish → 0 resumes; disable portfolio → public 404 11:14:30Z `141928cb-...` |
| 23 | Tracker | PASS | `POST /tracker/applications` 201 `3817b8f8-...` / `45aee057-...`; `GET ?flat=true` 200 contains row; `PATCH status` 200 `applied → phone_screen` (11:03:54Z `dad0b181-...`); `stats` 200 `total_applications:1`; invalid status `interview` correctly 422 with allowed enum; `DELETE` 204 |
| 24 | Account/quota final | PASS | `GET /me` 200 all three 11:09–11:10Z; `GET /config/entitlements` 200; `GET /subscription/current` 200; no drift outside expected charges |
| 25 | History surfaces | PASS\* | `POST /resumes/{id}/record-optimization` 201 for free `809974e7-...` and basic `aed5d3e8-...`; `GET /optimization-history` 200 returned 1 row each (`77617cc1-...`, `85b23441-...`); `/score-history` 200 returned 1 row each. Behavior is plan-identical despite different `historyRetention` copy — RET-01 |
| 26 | Quota exhaustion 402 | N/E | Deliberately not triggered to avoid exhausting Free’s 3 optimizations / 10 compiles and Basic’s allocations. Code path: `entitlement_service.enforce_quota` raises 402 `quota_exceeded` with `dimension/limit/used/reset`; refund path verified via failed compile |

## Quota ledger

| Cohort | Dimension | Baseline | Final | Limit | Charge events | Refund events |
|---|---|---|---|---|---|---|
| free | compilations | 0 | **1** | 10/day | direct compile `233fbc81-...` | failed compile `39bf4cb7-...` (no net change) |
| free | optimizations | 0 | **1** | 3/month | `/optimize` `7532d0f1-...` | none |
| free | ai_assists | 0 at 10:49; **1 pre-existing at 10:53** (not attributable to this test) | **2** | 25/month | `/ai/rewrite` `d3131aac-...` | none |
| basic-monthly | compilations | 0 | **1** | 400/month | direct compile `fc979711-...` | none |
| basic-monthly | optimizations | 0 | **1** | 10/month | `/optimize` `46014736-...` | none |
| basic-monthly | ai_assists | 1 pre-existing | **2** | 100/month | `/ai/rewrite` `c2e74b0c-...` | none |
| basic-annual | compilations | 0 | **2** | 400/month | direct compile `9bb2931b-...`; job `4d083a75-...` | none |
| basic-annual | optimizations | 0 | **0** | 10/month | none | none |
| basic-annual | ai_assists | 0 | **0** | 100/month | none | none |

The pre-existing `ai_assists` unit on free/basic-monthly appeared between the 10:49 baseline and 10:53 start of journey tests; it is not explained by any request in this report. Baselines at 10:33 were 0 for all cohorts. This is noted for other agents sharing the identity matrix.

## Latency observations (not a substitute for the performance audit)

Small samples; min/median/max. All times are wall-clock from the connected client (includes edge/network).

| Endpoint class | n | min | median | max |
|---|---|---|---|---|
| `GET /me` | 6 | 1,133 ms | 1,178 ms | 1,195 ms |
| `GET /config/entitlements` | 26 | 1,827 ms | 1,875 ms | **17,655 ms** (one outlier) |
| `GET /templates/` (list/search/filter) | 3 | 1,333 ms | 1,502 ms | 1,587 ms |
| `GET /templates/{id}` | 3 | 1,228 ms | 1,241 ms | 1,326 ms |
| `POST /resumes/` | 3 | 1,578 ms | 1,588 ms | 1,599 ms |
| `PUT /resumes/{id}` | 2 successes | 1,544 ms | 1,544 ms | 1,544 ms |
| `POST /compile` | 4 | 3,162 ms | 3,228 ms | 3,288 ms |
| `GET /download/{job}` | 2 | 3,291 ms | 5,194 ms | 7,097 ms |
| `POST /optimize` | 2 | 12,365 ms | 14,190 ms | 16,014 ms |
| `POST /ai/rewrite` | 2 | 4,011 ms | 4,991 ms | 5,970 ms |
| `POST /ats/quick-score` | 2 | 1,485 ms | 1,501 ms | 1,517 ms |
| `POST /ats/score` | 1 | 1,486 ms | 1,486 ms | 1,486 ms |
| `GET /export/{id}/{fmt}` | 2 | 1,214 ms | 1,556 ms | 1,898 ms |
| `POST /resumes/imports/pdf` | 2 | 1,581 ms | 1,680 ms | 1,779 ms |
| `GET /share/{token}` | 1 success | 4,373 ms | 4,373 ms | 4,373 ms |
| `GET /portfolio/{username}` | 2 | 1,026 ms | 1,036 ms | 1,046 ms |
| `POST /tracker/applications` | 2 | 1,300 ms | 1,831 ms | 2,363 ms |
| `GET /jobs/{id}/state` | 5 | 1,777 ms | 1,799 ms | 2,729 ms |

The 17.65 s snapshot has its own defect record (FB-04). Direct compile is ~3.2 s client-observed; the resume-linked job reached `completed` ~16 s after submit (state polling cadence), with artifact `pdf_sha256` and `pdf_size` consistent with the direct compile. Stage-level attribution is out of scope here (performance/events auditors).

Template preview assets add a gallery-specific cost: every thumbnail/PDF request is a **307** to R2 with `Cache-Control: private, no-store` and a freshly signed URL (TTL 86,400 s for templates). The card grid lazy-loads images, but a full scroll through 61 cards performs up to 61 backend redirects; single-redirect TTFB was 1.26–1.43 s, and the objects themselves were 358,640 B (PNG) / 96,149 B (PDF). Full-gallery load time was not measured in this pass.

## Artifacts and cleanup

Left in place for cross-check/reproduction (all prefixed `AUDIT`):

| Cohort | Artifact | ID | Status |
|---|---|---|---|
| free | template-created resume | `29bf3ac1-f5a5-4cc5-a06a-ba971f727944` | active |
| free | compile fixture (edited) | `d0e35c34-d619-4384-a5c6-b4eb39135d3f` | active |
| free | optimization history record | `04e859c5-3747-4b34-b519-eed1aa9f5440` | active |
| free | direct compile job/PDF | `76f3589a-32a8-4aa1-95d4-a39c33dd95af` | 84,144 B |
| free | failed compile job | `c4526b7d-a730-4b32-b7b5-99e388db9c57` | failed, refunded |
| basic-monthly | template-created resume | `a06ca085-9834-493b-895a-1960fbcb7ae2` | active |
| basic-monthly | compile fixture | `19c6cb91-b3ad-444e-8bad-a8512bd77667` | active |
| basic-monthly | optimization history record | `87736178-e4eb-4eb8-9657-84377584848f` | active |
| basic-monthly | compile job/PDF | `db89b925-8e9f-47ca-a913-202f44ae7c31` | 84,159 B |
| basic-annual | template-created resume | `c896ffca-1aca-457c-a99f-7da4c8c1ed5b` | active |
| basic-annual | compile fixture | `afe7e11f-e427-4109-910c-1b87431645ff` | active |
| basic-annual | direct compile job/PDF | `ec688b54-8834-4589-a5cb-152137641629` | 84,158 B |
| basic-annual | resume-linked compile job/PDF | `4d083a75-33f5-4e3b-b536-a98804ccd8f7` | 84,158 B, accepted artifact |

Deleted/revoked during cleanup: imported resume `94d72ad3-eba8-4a56-8d94-95631344b2a8` (204); staged import `fa065857-...` (cascaded, 404); tracker apps `3817b8f8-...` and `45aee057-...` (204); free share token (204, public 404); basic-annual share token (204); portfolio `audit-free-20261127` disabled (public 404) and resume `portfolio_visible:false`.

No global configuration, plan catalog, feature flag, capability grant, or deployment change was made. Per-account quota counters were consumed only by the calls above. Staged PDF import originals are deleted with their rows; generated PDFs remain in the job/artifact store.

## Limitations

- UI was not exercised: the in-app browser was not attached (`browser.not_attached`). Frontend source was inspected for the template card/preview and resume-edit call signatures; all functional evidence here is API-level.
- 402 quota exhaustion, dunning, checkout, billing webhooks, trial conversion, and GDPR deletion are out of scope for this sub-agent.
- `historyRetention` cannot be observed at a 30-day boundary with fresh test data; RET-01 is based on the plan catalog values plus code/read-path inspection and a fresh record/read on both plans.
- Basic-annual fixture subscription has a 30-day `currentPeriodEnd` (`2026-12-27`) because the provisioning script created every paid subscription with `+30 days`; this is a test-fixture limitation, not a product finding.
- The all-enabled capability matrix is environment-wide; CAP-01 may be owned/deduped by the capability audit.
