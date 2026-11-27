# Defect records — Security / tenant isolation

- **Audit window:** 2026-11-27T11:34:47Z – 2026-11-27T11:54:40Z
- **Environment:** production backend `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`; frontend share URL `https://latexy.xyz`; deployment identity from `audit/ground-truth.md` (`d2cbc51…` frontend / `ee1a405d…` backend) was not re-read in this sub-run.
- **Identities:** `pro-monthly` `2c27be6f-138f-4e98-b311-38892520b1eb`; `free` `96c507cd-e7a2-4749-9153-96b6321742db`; `team-owner` `6bb81a84-860b-46a5-8ab4-f1c483068479`; `team-member` `7a3d3b80-000c-49f0-a067-96c177b7c848`; `admin-support` `942247dc-f834-43d9-b012-a552ec6632a4`; `admin-superadmin` `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad`; `developer-api` `dc001b15-2133-4c18-a1a1-d0af1952835c`; `student`; `trial-expired`; anonymous.
- **Raw evidence:** `C:\Users\Sansk\AppData\Local\Temp\opencode\sec_tenant_evidence.json` (195 request/response records with `X-Request-Id`, status, latency and redacted bodies). Presigned URLs, share tokens, API keys and GDPR download tokens are redacted here and in the raw ledger; only lengths/hosts/TTLs are retained.
- **Scope:** cross-user and cross-tenant access to resumes, comments, shares, jobs, PDFs/artifacts, portfolios, tracker items, team seats/tenants, developer keys and GDPR exports/deletion; admin/support/user boundaries; capability revocation; presigned URL lifetime/binding.
- **Safety:** no global configuration, plan, flag or deployment change. Per-account capability overrides were applied by the admin identity and removed afterwards. One compile (`latex_compilation`) was submitted; no LLM calls, payments or live charges. Request rate was held at or below 17/min. No 429 and no 5xx were observed in 195 records.
- **Status:** all records below are open; no fix was attempted.

| ID | Sev | Title | Area |
|---|---|---|---|
| SEC-D01 | **P2** | Public share revocation does not invalidate an already-issued presigned PDF URL | Shares / artifacts |
| SEC-D02 | **P2** | Collaborator `GET /resumes/{id}` discloses the owner's public share token | Shares / collaboration |
| SEC-D03 | P3 | Job and comment access-denied responses reveal resource existence | Jobs / comments |

---

## SEC-D01 — P2 — Public share revocation does not invalidate an already-issued presigned PDF URL

**Surface:** `POST /resumes/{id}/share`, `DELETE /resumes/{id}/share`, `GET /share/{token}`, and the R2 presigned PDF URL returned by the public share endpoint.

**Cohort / user:** `pro-monthly` `2c27be6f-138f-4e98-b311-38892520b1eb` as owner. Any downstream holder of the PDF URL is affected, whether or not they have a Latexy account.

**Repro (observed):**

1. Create a resume and compile it. The job `25f2ce19-e399-449c-b2d9-6e51e2d6b8f5` completed (`GET /jobs/{id}/state` → 200 `status:"completed"` at 11:35:30Z; later `GET /resumes/{id}/latest-accepted-artifact` → 200 with `artifact.artifact_id=f3b7502f…`).
2. `POST /resumes/{id}/share` with `{"anonymous":false,"review_comments":true}`. The share token is issued.
3. `GET /share/{token}` returns a 509-character `pdf_url` with `X-Amz-Expires=3600` and `X-Amz-Date=20261127T114016Z` (i.e. valid until 12:40:16Z). Two unauthenticated GETs of that URL returned 200 with a PDF body.
4. `DELETE /resumes/{id}/share` → 204. `GET /share/{token}` → 404 and `GET /share/{token}/review-comments` → 404.
5. Re-use the previously issued `pdf_url` with no session → **200 `application/pdf`**.

**Expected:** revoking a share should stop every access path to that publication, including a URL already handed out. If presigned URLs cannot be revoked, the share should serve bytes through an API route that rechecks the token on every request, or the TTL must be short enough to satisfy the documented revocation expectation.

**Actual:** revocation nulls `resumes.share_token` and the public metadata endpoint stops serving, but the R2 object and the already-signed URL remain valid until the one-hour expiry. The revoke route is documented as “the public link immediately stops working”; the artifact does not.

**Evidence:**

| Time (UTC) | Identity | Request | Result | Request id |
|---|---|---|---|---|
| 11:35:05.761 | pro | `POST /jobs/submit` `latex_compilation` | 200, job `25f2ce19…` queued, 3,233.6 ms | `acc5680a-7aee-48ea-8a81-a8a51dcb772d` |
| 11:35:30.552 | pro | `GET /jobs/25f2ce19…/state` | 200, `status:"completed"`, 2,613.5 ms | `b2c0c88d-ee00-4e63-a211-9af99dd2fffb` |
| 11:35:34.942 | pro | `POST /resumes/fd794343…/share` | 200, share token issued (32 chars), 1,338.6 ms | `fa8e89c1-65bf-45d0-b2eb-8092843ed5e8` |
| 11:38:24.127 | anonymous | `GET /share/{token}` | 200, `pdf_url` 509 chars, 1,531.7 ms | `2ae76f3f-51e5-4c50-940f-d5a8611f9704` |
| 11:40:19.452 | anonymous | `GET {pdf_url}` (R2) | **200**, `application/pdf`, 588.3 ms | — (R2) |
| 11:40:22.818 | anonymous | second `GET {pdf_url}` | **200**, 314.8 ms | — (R2) |
| 11:40:25.975 | anonymous | `GET {pdf_url}` with one signature byte changed | 403, 106.0 ms | — (R2) |
| 11:46:27.490 | pro | `DELETE /resumes/fd794343…/share` | 204, 1,223.5 ms | `e23969fd-5522-48c2-ba67-42874ffb5063` |
| 11:46:31.559 | anonymous | `GET /share/{token}` after revoke | 404 `Share link not found or has been revoked`, 1,017.5 ms | `7978c3fc-3542-4147-b413-59ff401c74d8` |
| 11:46:35.608 | anonymous | `GET /share/{token}/review-comments` after revoke | 404 `Review link not found or has been revoked`, 1,007.7 ms | `d0e3dd34-63fd-4961-a5df-a04d3bf83866` |
| 11:46:38.951 | anonymous | **same `pdf_url` after revoke** | **200**, `application/pdf`, 292.2 ms | — (R2) |

The URL was issued at 11:40:16Z with `X-Amz-Expires=3600`; it was still serving 11 seconds after the 204 revoke and had roughly 53 minutes of TTL left.

**Impact:** “Revoke share” is not an immediate revocation for the PDF artifact. Anyone who received, cached or forwarded the presigned URL retains download access until expiry, even after the owner revokes the share or the collaborator who leaked it is removed. This undermines the documented revocation control and is directly relevant to the Phase 2 requirement that a public share stops serving when publication is revoked. No real customers exist as of this audit, so observed impact is limited to the synthetic fixture; the behaviour would be a P1 if live customer shares were in use.

**Confidence:** high for the revocation gap. The public metadata endpoint and review-comment endpoint both 404, while the same URL that was issued before revocation still returns bytes from R2. The exact expiry instant of a freshly minted short-TTL URL was not verified (the direct R2 probe returned no HTTP status; recorded as BLOCKED in the plan report); signature validation and the 3600 s TTL parameter are verified.

**Proposed fix:**

1. On `DELETE /resumes/{id}/share`, delete or replace the shared PDF object (versioned delete) and invalidate the share-specific artifact pointer; do not leave the object addressable by an old signed URL.
2. If the object must remain for owner access, serve share PDFs through an API route that rechecks `share_token`/capability on every request and streams the bytes; do not hand out a long-lived bucket URL.
3. If presigned URLs remain, cap share PDF TTL at the revocation SLO (for example ≤60 s) and document that revocation is eventually consistent within that window. A 1-hour TTL is incompatible with “immediately stops working”.
4. Add a regression test: issue share URL → revoke share → assert the URL no longer returns `application/pdf` (or returns 403/404) and that no new URL can be minted from the revoked token.
5. Consider binding the share artifact to the share token generation (object key includes a token-generation hash) so revocation can invalidate all prior generations without affecting owner downloads.

**Owner:** Share/artifact backend (resume sharing + storage). **Status:** open.

---

## SEC-D02 — P2 — Collaborator `GET /resumes/{id}` discloses the owner's public share token

**Surface:** `GET /resumes/{id}` (`ResumeResponse` fields `share_token`, `share_url`, `share_anonymous`, `share_review_comments`); collaborator invitation/removal.

**Cohort / user:** `pro-monthly` owner `2c27be6f-138f-4e98-b311-38892520b1eb`; `free` viewer collaborator `96c507cd-e7a2-4749-9153-96b6321742db`.

**Repro (observed):**

1. Owner creates a public share on the resume (share `fa8e89c1…`, token `oaLm…`, `review_comments:true`).
2. Owner invites `free` as a `viewer` collaborator (`POST /resumes/{id}/collaborators`, 201).
3. `free` calls `GET /resumes/{id}`. The 200 response has `access_role:"viewer"`, the full `latex_content`, **`share_token` (32 chars)**, **`share_url` (`https://latexy.xyz/r/<token>`)** and `share_review_comments:true`.
4. Owner removes the collaborator (`DELETE …/collaborators/{free_id}` → 204). `free` then gets 404 on the private resume, but the public share token that was disclosed is not rotated or revoked and the public link remains live until the owner explicitly revokes it.

**Expected:** the owner’s share-management capability should not be disclosed to a collaborator. A viewer/editor needs document content to collaborate, but not the owner’s public share token. `share_token`, `share_url`, `share_anonymous` and `share_review_comments` should be owner-only fields (or gated by a dedicated share-management capability).

**Actual:** every collaborator response includes the live public token. A removed collaborator can retain the public link and redistribute it; the private collaborator removal control does not remove that capability.

**Evidence:**

| Time (UTC) | Identity | Request | Result | Request id |
|---|---|---|---|---|
| 11:35:34.942 | pro | `POST /resumes/fd794343…/share` | 200, token issued, `review_comments:true`, 1,338.6 ms | `fa8e89c1-65bf-45d0-b2eb-8092843ed5e8` |
| 11:35:57.829 | pro | `POST /resumes/fd794343…/collaborators` (`free`, viewer) | 201, 2,137.9 ms | `d58b0a7d-10ce-4b28-a89b-7da3472c21fe` |
| 11:37:27.668 | free | `GET /resumes/fd794343…` as viewer | 200, `access_role:"viewer"`, `share_token` present, `share_url` present, full LaTeX, 2,303.2 ms | `fef67a15-8062-47e5-a05c-6d935389f1cb` |
| 11:38:15.288 | pro | `DELETE /resumes/fd794343…/collaborators/96c507cd…` | 204, 1,429.3 ms | `63d69d8a-d6d4-419c-adda-4ab77e1dad98` |
| 11:38:19.544 | free | `GET /resumes/fd794343…` after removal | 404 `Resume not found`, 1,206.1 ms | `80a60a96-e2b3-4480-adec-7ff1f30f3f65` |
| 11:45:32.956 | anonymous | `GET /share/{token}` after collaborator removal | 200, public PDF/access still live, 1,569.0 ms | `add2db55-6f48-46ca-a1f0-9d0599234bed` |

**Impact:** a viewer or editor can copy the owner’s public share link before or after removal. The public link is a bearer capability; it grants public access to the resume (and, when enabled, anonymous review comments) until the owner explicitly revokes it. A removed collaborator can continue to distribute that link, and the owner has no signal that it leaked. The collaborator already had private read access while a member, so this is a capability-propagation/least-privilege defect rather than an outright data breach; P2 reflects the persistence across collaborator removal.

**Confidence:** high. The response body was observed directly; the share token length and `share_url` are present in the viewer response, and collaborator deletion does not rotate `resumes.share_token` (source at the deployed SHA only deletes the collaborator row and revokes live sockets).

**Proposed fix:**

1. In the resume serializer, return `share_token=None`, `share_url=None`, `share_anonymous=False`, `share_review_comments=False` unless the caller is the owner (or has an explicit share-management permission). Keep the fields for the owner response only.
2. Add an authorization test that a viewer/editor response never contains a live share token, even when a share exists.
3. On collaborator removal, consider whether the owner wants the public share rotated. At minimum, surface the active share link to the owner with a “rotate/revoke” action so removal of a collaborator does not silently leave a link the collaborator knows.
4. Audit the response model for other owner-only capabilities (future fields) with the same rule: serializer output should depend on `access_role`.

**Owner:** Resume sharing / serializer. **Status:** open.

---

## SEC-D03 — P3 — Job and comment access-denied responses reveal resource existence

**Surface:** `GET /jobs/{job_id}/state`, `/result`, `/stream`, `DELETE /jobs/{job_id}`; `GET|POST /resumes/{resume_id}/comments`, `PATCH|DELETE /resumes/{resume_id}/comments/{comment_id}`.

**Cohort / user:** any authenticated non-owner (`free`, `team-member`, `student`, `admin`, `support`); anonymous for jobs.

**Repro (observed):**

1. With a valid pro-owned job id, `free`/`team-member`/`student`/`admin`/`support`/anonymous call the job state, result, stream and cancel endpoints. They return **403 `Access denied`**, not 404.
2. With a valid pro-owned resume id and no collaborator row, `free` calls the comments endpoints. The comment list/post/edit/delete return **403** with messages such as “You do not have access to this resume” / “You cannot comment on this resume”.
3. The same `free` identity calling `GET /resumes/{id}` and `/tracker/applications/{id}` on the same foreign objects gets **404** (`Resume not found`, `Application not found`).

**Expected:** unauthorized lookups should be indistinguishable from non-existent resources (404) so an authenticated attacker cannot confirm that a UUID exists and belongs to another tenant/user. The resume and tracker endpoints already follow this pattern. The developer API job route returns 404 for a non-owned job, which is the correct precedent.

**Actual:** job and comment routes return 403 with area-specific denial messages; this is an existence oracle for guessed UUIDs. The practical risk is low because job/resume ids are 128-bit UUIDs and the word “Access denied” does not disclose content, but it is inconsistent and gives a probing signal.

**Evidence:**

| Time (UTC) | Identity | Request | Result | Request id |
|---|---|---|---|---|
| 11:39:03.583 | free | `GET /jobs/25f2ce19…/state` | 403 `Access denied`, 1,442.9 ms | `88c8ae01-c2bb-4e00-b0cb-da9e9f1aece3` |
| 11:39:29.961 | free | `GET /jobs/25f2ce19…/result` | 403 `Access denied`, 1,382.2 ms | `4fcecf0c-a1c2-4c9b-b34c-21d47cafdd58` |
| 11:39:34.381 | free | `GET /jobs/25f2ce19…/stream` | 403 `Access denied`, 1,367.3 ms | `1a236119-a0a1-4c2b-89a8-edda35a2e52c` |
| 11:39:38.804 | free | `DELETE /jobs/25f2ce19…` | 403 `Access denied`, 1,372.2 ms | `c4d0ed05-8656-404a-a43c-d58acaaebf7d` |
| 11:52:37.056 | free | `GET /resumes/60f36508…/comments` (no collaborator) | 403 `You do not have access to this resume`, 4,037.4 ms | `255122f4-7a1b-46c6-a542-fa199097e48a` |
| 11:52:41.402 | free | `POST /resumes/60f36508…/comments` | 403 `You cannot comment on this resume`, 1,302.9 ms | `bd42123a-e256-4fbf-9823-f3c755c7ba97` |
| 11:52:45.727 | free | `PATCH /resumes/60f36508…/comments/8f56d268…` | 403 `You cannot comment on this resume`, 1,281.6 ms | `34043961-922b-480a-b5fe-614fb7af3276` |
| 11:52:16.992 | free | `GET /resumes/60f36508…` (control) | 404 `Resume not found`, 1,220.2 ms | `dcd2b1b2-3ace-4c41-a466-f69b8260870d` |
| 11:40:50.938 | free | `GET /tracker/applications/301014d9…` (control) | 404 `Application not found`, 1,194.1 ms | `276223ce-9b3f-4c97-95ff-fef7af7b13ef` |

**Impact:** information disclosure only: an authenticated attacker with a valid UUID can distinguish “exists but not yours” from “does not exist”. Content is not returned. P3.

**Proposed fix:** use a single not-found response for unauthorized job/comment/resume access; keep a separate, audited owner-only path for legitimate 403s (for example a collaborator who is authenticated but lacks a write role, where the resource is already known to them). Log the actual denial reason server-side with the actor/request id.

**Owner:** Jobs and comments backend. **Status:** open.

---

## Observations not filed as defects

| Observation | Evidence | Disposition |
|---|---|---|
| First-pass `free` read of the pro resume returned 200 because `free` had already been invited as a viewer before the negative test. | `da2c8740…` 200 `access_role:"viewer"` at 11:36:30Z; clean rerun at 11:52:16Z returned 404 `dcd2b1b2…`. | Test-order contamination, not a product defect. The clean rerun is authoritative. |
| First-pass `free` comment list returned 200 for the same reason (viewers may read comments by design). | `f7b51c7f…` 200 at 11:37:05Z; clean rerun 403 `255122f4…`. | By design for a viewer; not a defect. The clean no-collaborator test is 403. |
| `PATCH /resumes/{id}` returned 405 when trying to test portfolio visibility. | `c8f1192a…` and `e60e5bb0…` 405. | Test harness used the wrong method; `PUT /resumes/{id}` is the update route. Not a defect. |
| Tenant-B cohort deny first returned 422 because the probe sent no body. | `98b73e96…` 422. Re-run with `{"name":"Audit Security denied cohort"}` → 403 `Access denied: owner or admin required`, request `be2ff4b9-5f2d-484e-9a42-e12afa4979b3`. | Test harness error; the valid-body result is a PASS for tenant isolation. |
| `f04` per-user capability revocation could not be measured: the collaborator had already been removed before the test, so control/revoked/restored all returned 404. | `7880d48b…` 404, `f54b3f8f…` 404, `fe23dd3f…` 404 at 11:46:03–11:46:23Z. | **INVALID / not tested.** Do not claim f04 enforcement from this run. Collaborator row removal itself was verified: `63d69d8a…` 204 → `80a60a96…` 404. |
| Presigned URL actual expiry (1-second TTL) could not be fetched from the harness. | Four follow-up R2 GETs returned no HTTP status (`0`) with 4.1 s elapsed. The original share-issued URL did fetch (200), and a tampered signature returned 403. | **BLOCKED.** Signature validation is proven; actual expiry is not. The one-hour TTL is visible in `X-Amz-Expires=3600`. |
| Team-member live plan is `team_member`, while the identity matrix records plan `team`. | DB read at 11:34Z and after cleanup: `subscription_plan=team_member`; all owner-only team actions returned 403. | Matrix/data discrepancy, not a live defect. It prevents the latent plan-string issue below. |
| Latent code risk: `_require_team_owner` and tenant creation check `subscription_plan == "team"` rather than seat/tenant ownership. | Source at the deployed SHA: `backend/app/api/team_routes.py:153-168`, `backend/app/api/tenant_routes.py:459-483`. Live team-member is `team_member`, so the checks deny. | Hardening observation only; would become a privilege boundary if a team member's plan were ever `team`. |
| Platform admin (`admin-superadmin`) received 403 on `/tenants/{tenantB}/members` and `/tenants/{tenantB}/cohorts`. | `01bf3e23…` 403 at 11:42:07Z. | Tenant API is membership-scoped; admin has the separate `/admin/users/{id}/360` path. No defect. |

---

## Cleanup / verification status

| Item | Status |
|---|---|
| Per-user capability overrides `f01`, `g12` on pro and `f04` on free | Applied through admin API, then removed directly from `users.user_metadata` (`entitlement_overrides` key deleted). Verified `{}` for pro, free and trial-expired. Six admin audit rows remain as the immutable record. |
| Automatic `db_restore` on first run | **Failed** (`ConnectionDoesNotExistError` after the long run). Manual cleanup with a fresh connection succeeded; the stale error remains in the raw evidence file’s `cleanup` key and should not be read as the final state. |
| Pro fixture resume `fd794343-6f9b-4658-bfb2-e5e0f17c73f4` | Deleted by API, verified 404. Clean follow-up resume `60f36508-4865-414d-b100-3f022840da3f` deleted, DB count 0. Accidental curl probe resume `1a213551-7cb1-446b-aec2-db3d37b5bf8a` deleted 204. |
| Comments / collaborator | Owner comment `e50920a6…` deleted; free collaborator comment `e5e2f467…` deleted by author; collaborator removed (`63d69d8a…`), private read 404. Clean comment `8f56d268…` deleted. |
| Public share | Revoked (`e23969fd…`), public metadata and review-comment reads 404. |
| Anonymous review comment `c13de9d1-0677-4b79-a2ed-e1fdc6114079` | Deleted from `resume_review_comments` during manual cleanup; DB count 0. |
| Portfolio `auditsec-103328` | Pro username cleared and portfolio disabled in DB; public 404. `portfolio_theme` reset to `minimal`. |
| Tenant B `3f98ed40-fcb0-4766-8dd0-e0f6807aa2b5` and cohort `5898602a-6a2d-4366-a8fc-fb3f2d1c9279` | Deleted via DB (tenant API has no delete route): `tenant_domain_events`, `tenant_members`, `workspaces`, `tenants`. Verified no `audit-sec-%` tenants remain; no tenant C was created (team-member got 403). |
| Tracker application `301014d9-fbf3-439a-a72f-cb91d0a2c8e9` and reminder | Deleted, DB count 0. |
| Developer key `f597d64e-fa4b-400d-bceb-1e5ea764fd68` | Revoked by owner, `is_active=false`; revoked key returns 401. Cross-user delete returned 404. |
| GDPR export request `e6a5b566-ad19-4577-b2e5-42a9c0941eb8` | **Retained** (`status=ready`, expires 2026-11-27T12:05:53Z, 254-char token). Contains synthetic pro fixture only. Cleanup owner: cleanup auditor; natural expiry or explicit deletion. |
| Compilation `477643e9-b70b-4ac0-9c2b-603eaaab8060` / job finalization `25f2ce19-…` | **Retained** after resume deletion with `resume_id=NULL`; `pdf_path=render-artifacts/v1/5ea2c0d1…/pdf/c429…pdf`. R2 object remains. Cleanup owner: artifact lifecycle / cleanup auditor. This is the object used for the presigned URL evidence. |
| `team_seats` | No new seat was created; team-member/free invites were denied. Pre-existing owner/member seats untouched. |
| Admin/support sessions, subscriptions, plans | Unchanged. `trial-expired` plan/status verified `free/expired`; the concurrent `basic-annual` plan-change audit rows visible at 11:43Z belong to another sub-agent and were not touched. |
