# Security / Tenant Isolation — Cohort Report

**Audit window:** 2026-11-27T11:34:47Z – 2026-11-27T11:54:40Z
**Environment:** production backend `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`; frontend/share origin `https://latexy.xyz`. Backend `/health` was 200 (5.45 s) immediately before the run; deployment identity was not re-read in this sub-run and is taken from `audit/ground-truth.md` (`ee1a405d…` backend / `d2cbc51…` frontend).
**Raw evidence:** `C:\Users\Sansk\AppData\Local\Temp\opencode\sec_tenant_evidence.json` (195 records; each has UTC timestamp, identity, method/path, status, latency, `X-Request-Id` where the API returned one, and a redacted body). Share tokens, presigned signatures, API keys and GDPR tokens are redacted; only lengths/hosts/TTLs are retained here.
**No global configuration, plan, flag, deployment or payment state was changed.** Per-account capability overrides were used only on the audit identities and were removed afterwards. One `latex_compilation` job was submitted; no LLM call and no live charge.

---

## 1. Verdict

| Area | Verdict | Evidence summary |
|---|---|---|
| Resume ownership | **PASS** | With no collaborator row, `free` read/overwrite/delete of a pro resume all returned 404 (clean rerun). Owner CRUD 200/201. |
| Comments | **PASS with P3 oracle** | Non-owner list/post/edit/delete 403; owner 200/201. The 403 body confirms the resume exists (SEC-D03). |
| Collaboration roles | **PASS** | Viewer read 200, viewer write 403, viewer comment 403; commenter create/edit/delete own comment 201/200/204; removal 204 → immediate 404. |
| Share creation/revocation | **PASS for metadata** | Non-owner create/revoke 404; owner revoke 204; public share 200 before, 404 after; review-comment list 404 after revoke. |
| Public share artifact revocation | **FAIL (P2)** | The already-issued 1-hour presigned PDF URL still returned `application/pdf` 200 after share revocation. SEC-D01. |
| Share capability propagation | **FAIL (P2)** | A viewer collaborator received the owner’s `share_token` and `share_url` in `GET /resumes/{id}`; collaborator removal does not rotate the public link. SEC-D02. |
| Jobs | **PASS with P3 oracle** | Cross-user state/result/stream/cancel 403 with no data; owner 200; job list excludes foreign job. 403 vs 404 reveals existence. SEC-D03. |
| PDFs / artifacts | **PASS** | Owner preview/geometry 200; free, anonymous and admin 404. Owner latest-accepted-artifact 200; free/admin 404. |
| Presigned URL signature | **PASS** | One-byte signature change → 403. The URL is a bearer capability (two anonymous GETs 200), by design for a public share. |
| Presigned URL expiry | **BLOCKED** | Direct 1-second-URL probe got no HTTP response (status 0); only the 3600 s TTL parameter and signature rejection are verified. |
| Portfolios | **PASS** | Public read 200 with published resume; free unpublish 404; username claim 409; owner unpublish 200 → empty list; owner disable 200 → public 404; g12 revoke 404/restore 200. |
| Tracker | **PASS** | Cross-user item/status/reminder/delete all 404; owner 200/201/204. |
| Team seats | **PASS** | Owner list 200; team-member and free 403; member/free invite 403. No seat fixture created. |
| Tenants | **PASS** | Team member is denied cross-tenant members/cohorts/rename/cohort-create/invite/tenant-create (403); own roster read 200; owner creates/updates tenant B 201/200. |
| Developer keys | **PASS** | Key authenticates (404 on a missing job, not 401); scope-less export 403; free delete 404; owner revoke 204 → old key 401. |
| GDPR exports/deletion | **PASS** | Cross-user request read 404; cross-user download with the owner token 404; owner download 200; pro read/cancel of free deletion 404; owner cancel of a rejected request 409. |
| Admin/support/user boundaries | **PASS** | Support user-360 200 with `pii_masked:true`; free 403; support denied flags/entitlements/audit/GDPR/view-as/PII/plan/capability mutation (403); admin allowed admin reads 200. Admin cannot read product data via the product API (job 403, resume 404). |
| Capability revocation | **PASS for f01/g12; BLOCKED for f04** | f01 revoke → share 404; grant → 200. g12 revoke → portfolio 404; grant → 200. The f04 probe was invalid because the collaborator had already been removed. |
| Rate / reliability | **PASS** | No 429 and no 5xx across 195 requests; 17/min cap held. |

**Defects:** 2×P2, 1×P3 — see `audit/defects/security-tenant.md` (SEC-D01, SEC-D02, SEC-D03).

---

## 2. Identities and safety record

| Identity | User id | Plan / role | Use |
|---|---|---|---|
| `pro-monthly` | `2c27be6f-138f-4e98-b311-38892520b1eb` | pro / user | Victim/owner of resume, job, share, portfolio, tracker, GDPR export |
| `free` | `96c507cd-e7a2-4749-9153-96b6321742db` | free / user | Cross-user attacker and viewer/commenter collaborator |
| `team-owner` | `6bb81a84-860b-46a5-8ab4-f1c483068479` | team / user | Tenant A owner; created tenant B and a cohort for isolation testing |
| `team-member` | `7a3d3b80-000c-49f0-a067-96c177b7c848` | **team_member** / user (matrix says `team`) | Cross-tenant member; all owner-only actions denied |
| `admin-support` | `942247dc-f834-43d9-b012-a552ec6632a4` | support | Support read + denied admin-only actions |
| `admin-superadmin` | `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad` | admin | Admin reads and per-user capability overrides |
| `developer-api` | `dc001b15-2133-4c18-a1a1-d0af1952835c` | pro / user | Minted/revoiced its own scoped developer key |
| `student` | `d91e5bf0-bbc9-4558-9e10-151e728cdeec` | student / user | Extra cross-user job probe |
| `trial-expired` | `620c8a6e-db14-4be2-806a-13365c667fdd` | free / expired | Target for denied support plan/capability mutations |
| anonymous | — | — | Public share, portfolio, tenant host resolution, presigned URL |

**Safety:**

- Request rate: 17/min hard ceiling in the probe; actual pace 3.05 s minimum spacing plus response time. No 429 observed.
- No global config, capability matrix, plan catalog, feature flag or deployment change.
- Per-account overrides only: `f01` and `g12` on pro; `f04` on free. All were applied with `POST /admin/users/{id}/features/{revoke|grant}` and removed from `user_metadata` during cleanup.
- One compile: `latex_compilation` job `25f2ce19-e399-449c-b2d9-6e51e2d6b8f5`, submitted 11:35:05Z, completed by 11:35:30Z. No LLM optimization, payment or checkout.
- Test data created only under the `audit+…-20261127103328@example.test` identities and tenant `audit-sec-b-103328`; see §11 for cleanup.

---

## 3. Environment and reliability observations

| Check | Result | Evidence |
|---|---|---|
| Backend `/health` | 200, 5.45 s | Pre-run, 11:34Z (no request id captured) |
| 429 count | 0 / 195 | Entire ledger |
| 5xx count | 0 / 195 | Entire ledger |
| Product GET latency range (non-admin, n≈70) | ~0.97–5.58 s; typical ~1.2 s | Single-run observations, not a statistical percentile |
| Admin 360 (`support` / `admin`) | 2,840 ms / 2,874 ms | `52b4f2c3…` / `a22d4626…` |
| Admin flags / view-as / audit | 1,445 / 1,162 / 1,193 ms | `858b2f10…`, `6d61dc44…`, `c4e33f5f…` (403 support) |
| Developer key create | 16,348 ms (cold outlier) | `f3b04f28-7a63-47b0-8abb-462f926bfd14` |
| Compile submit → terminal state | 3,234 ms submit; terminal by 24.8 s | Job `25f2ce19…`; state polls 1.7–2.6 s each |
| Compile state artifact | `artifact:null` in `/jobs/{id}/state` even at `completed`; `latest-accepted-artifact` later returned a real artifact | `b2c0c88d…` (state) vs `dd874787…` (artifact) |

**Measured stages:** submit request 3,233.6 ms (`acc5680a…`); terminal state reached 24.8 s after submit (state poll at 11:35:30.552, `b2c0c88d…`); each state poll 1.7–2.6 s. Finer stages (admission, queue, container, LaTeX pass, upload) are not exposed by this API and were not measured. The compile stage split is owned by the performance auditor; here the compile existed only to create a real PDF fixture. The security-relevant detail is that the public share PDF exists and is independently addressable by a presigned URL (SEC-D01).

---

## 4. Cross-user access results

### 4.1 Resumes

**Method note:** the first negative pass accidentally ran after `free` had been invited as a viewer, so `free` reading the pro resume returned 200 `access_role:"viewer"` (`da2c8740…`). That is correct collaborator behaviour, not an ownership bypass. The test was rerun on a fresh pro resume with **no collaborator row**; those results are authoritative.

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:52:12.730 | pro | `POST /resumes/` clean fixture | 201, owner | 4,648.8 ms | `a64ccfe5-85ae-443b-9bdb-523057a221b6` |
| 11:52:16.992 | free | `GET /resumes/60f36508…` | **404** `Resume not found` | 1,220.2 ms | `dcd2b1b2-3ace-4c41-a466-f69b8260870d` |
| 11:52:21.307 | free | `PUT /resumes/60f36508…` (`title:"hijacked"`) | **404** | 1,271.6 ms | `7a80235a-a2e7-4156-8a3d-c50393ea4e67` |
| 11:52:25.526 | free | `DELETE /resumes/60f36508…` | **404** | 1,176.0 ms | `7e9abb44-ee8d-41c7-804a-0a1c3bd687b7` |
| 11:36:30.591 | free (viewer) | `GET /resumes/fd794343…` | 200 `access_role:"viewer"` | 1,312.9 ms | `da2c8740-b49e-4d55-95b3-7a146ff9334d` |
| 11:36:34.994 | free (viewer) | `PUT /resumes/fd794343…` | 403 read-only | 1,351.1 ms | `c527b4de-376a-4d46-853e-a1cdfdbe3df6` |
| 11:36:39.242 | free (viewer) | `DELETE /resumes/fd794343…` | 404 | 1,197.1 ms | `03ca192c-d81e-45e8-9279-f71d77bb2373` |
| 11:36:43–11:36:52 | team-member, support, admin | `GET /resumes/fd794343…` | 404 for all | 1,151–1,224 ms | `f0165e87…`, `68afd598…`, `6fa672c0…` |
| 11:37:05.099 | free | `GET /resumes/?limit=100` | 200; pro resume not present | 5,583.0 ms | `b3c6c16c-ab61-434b-9a66-d54c3eca7488` |

**Verdict:** PASS. Private resume reads/writes/deletes are owner-or-collaborator scoped; a caller with no relationship receives 404 and no metadata. Admin and support do not bypass the product API. The only caveat is the share-token disclosure in a collaborator response (SEC-D02), which is a capability leak rather than a resume-content leak.

### 4.2 Comments and collaboration roles

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:52:29.959 | pro | `POST /resumes/60f36508…/comments` | 201 | 1,389.7 ms | `40b955d6-dcac-4a53-b487-b2234f9ecc75` |
| 11:52:37.056 | free (no collaborator) | `GET …/comments` | **403** `You do not have access to this resume` | 4,037.4 ms | `255122f4-7a1b-46c6-a542-fa199097e48a` |
| 11:52:41.402 | free (no collaborator) | `POST …/comments` | **403** `You cannot comment on this resume` | 1,302.9 ms | `bd42123a-e256-4fbf-9823-f3c755c7ba97` |
| 11:52:45.727 | free (no collaborator) | `PATCH …/comments/8f56d268…` | **403** | 1,281.6 ms | `34043961-922b-480a-b5fe-614fb7af3276` |
| 11:52:49.995 | free (no collaborator) | `DELETE …/comments/8f56d268…` | **403** | 1,225.2 ms | `80153298-8eb4-4c49-9d6d-f9e13197e650` |
| 11:37:27.668 | free (viewer) | `GET …/comments` | 200 (viewers may read) | 2,303.2 ms | `fef67a15-8062-47e5-a05c-6d935389f1cb` |
| 11:37:40.911 | free (viewer) | `POST …/comments` | 403 read-only | 1,340.9 ms | `82401e50-2627-44a0-ae08-32195caa2329` |
| 11:38:02.010 | free (commenter) | `POST …/comments` | 201 | 1,487.1 ms | `b6070a59-523b-4d15-9cfa-9ea384a3694f` |
| 11:38:06.532 | free (commenter) | `PATCH …/comments/e5e2f467…` | 200 | 1,467.7 ms | `480efc1c-a78f-49bf-92bb-c29c5d7e6c25` |
| 11:38:10.808 | free (commenter) | `DELETE …/comments/e5e2f467…` | 204 | 1,225.0 ms | `eef2b0d8-d017-4a28-9f98-7bb1c1ff60ed` |
| 11:38:15.288 | pro | `DELETE …/collaborators/96c507cd…` | 204 | 1,429.3 ms | `63d69d8a-d6d4-419c-adda-4ab77e1dad98` |
| 11:38:19.544 | free (removed) | `GET /resumes/fd794343…` | 404 | 1,206.1 ms | `80a60a96-e2b3-4480-adec-7ff1f30f3f65` |

**Verdict:** PASS for role enforcement. Viewer can read the document/comments but cannot write; commenter can create/edit/delete only its own comment; removal takes effect immediately. The 403 responses are an existence oracle (SEC-D03).

### 4.3 Shares, public access and review comments

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:35:34.942 | pro | `POST /resumes/fd794343…/share` `{anonymous:false, review_comments:true}` | 200, token issued | 1,338.6 ms | `fa8e89c1-65bf-45d0-b2eb-8092843ed5e8` |
| 11:38:24.127 | anonymous | `GET /share/{token}` | 200, title/text/PDF URL | 1,531.7 ms | `2ae76f3f-51e5-4c50-940f-d5a8611f9704` |
| 11:38:28.714 | free | `GET /share/{token}` | 200 (public by design) | 1,535.0 ms | `4d02dad1-7bc9-4830-9a08-48e5d3d6169b` |
| 11:38:33.317 | team-member | `GET /share/{token}` | 200 (public by design) | 1,552.3 ms | `3d025749-db86-4d88-9478-9cc5f775104d` |
| 11:38:37.871 | anonymous | `GET /share/{token}/review-comments` | 200, empty | 1,503.0 ms | `1c8dd3b3-65b8-4491-9cc5-bab2a04436fd` |
| 11:38:42.340 | anonymous | `POST /share/{token}/review-comments` | 201 | 1,417.8 ms | `960714b1-dbd0-4e73-969c-9ceacfeabd12` |
| 11:38:46.495 | anonymous | `GET …/review-comments` | 200, one comment | 1,103.4 ms | `c514c7ab-f98a-49f9-a23f-d02fa2edc46f` |
| 11:38:50.519 | anonymous | `GET /share/not-a-real-token` | 404 | 971.6 ms | `7ed256fb-dab9-48b9-a0df-fc33ab445063` |
| 11:38:54.800 | free | `POST /resumes/fd794343…/share` | **404** | 1,230.2 ms | `578bd9a8-df79-43dc-b4dd-3e3a967103ea` |
| 11:38:59.089 | free | `DELETE /resumes/fd794343…/share` | **404** | 1,238.1 ms | `04752ba0-54f8-4e61-a635-54d344b7838a` |
| 11:46:27.490 | pro | `DELETE /resumes/fd794343…/share` | 204 | 1,223.5 ms | `e23969fd-5522-48c2-ba67-42874ffb5063` |
| 11:46:31.559 | anonymous | `GET /share/{token}` after revoke | **404** | 1,017.5 ms | `7978c3fc-3542-4147-b413-59ff401c74d8` |
| 11:46:35.608 | anonymous | `GET …/review-comments` after revoke | **404** | 1,007.7 ms | `d0e3dd34-63fd-4961-a5df-a04d3bf83866` |
| 11:46:38.951 | anonymous | previously issued `pdf_url` after revoke | **200 `application/pdf`** | 292.2 ms | — (R2) |

**Verdict:** metadata/review revocation is correct; artifact revocation is not (SEC-D01). Non-owner share create/revoke is correctly denied. The public share response contains the owner’s full public text and title, as intended for a public link.

### 4.4 Collaboration response leak (SEC-D02)

The viewer response at 11:37:27 (`fef67a15…`) contained `share_token` and `share_url` in addition to the full document. This is detailed in SEC-D02. The important sequence is: token disclosed to viewer → viewer removed 204 → private access 404 → public share still 200 (`add2db55…` at 11:45:32, after removal). The removal control does not revoke the public capability the collaborator learned.

### 4.5 Jobs

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:35:05.761 | pro | `POST /jobs/submit` `latex_compilation` | 200, job `25f2ce19…` | 3,233.6 ms | `acc5680a-7aee-48ea-8a81-a8a51dcb772d` |
| 11:35:30.552 | pro | `GET /jobs/25f2ce19…/state` | 200 `completed` | 2,613.5 ms | `b2c0c88d-ee00-4e63-a211-9af99dd2fffb` |
| 11:39:03.583 | free | `GET …/state` | **403** `Access denied` | 1,442.9 ms | `88c8ae01-c2bb-4e00-b0cb-da9e9f1aece3` |
| 11:39:08.022 | team-member | `GET …/state` | **403** | 1,388.5 ms | `f467d41b-8553-49ab-a7b0-27eb2a6f47ac` |
| 11:39:12.446 | support | `GET …/state` | **403** | 1,370.9 ms | `c4facd9f-e7b0-4a68-b7c0-47134c538a32` |
| 11:39:16.900 | admin | `GET …/state` | **403** | 1,403.0 ms | `472ae264-f77f-4a92-9a59-bf3e3ee65d9a` |
| 11:39:21.345 | student | `GET …/state` | **403** | 1,394.8 ms | `8b639162-435f-4e04-945b-1531d57d6500` |
| 11:39:25.528 | anonymous | `GET …/state` | **403** | 1,132.4 ms | `472f778e-a100-415a-b50a-f1c9463c3fed` |
| 11:39:29.961 | free | `GET …/result` | **403** | 1,382.2 ms | `4fcecf0c-a1c2-4c9b-b34c-21d47cafdd58` |
| 11:39:34.381 | free | `GET …/stream` | **403** | 1,367.3 ms | `1a236119-a0a1-4c2b-89a8-edda35a2e52c` |
| 11:39:38.804 | free | `DELETE /jobs/25f2ce19…` | **403** | 1,372.2 ms | `c4d0ed05-8656-404a-a43c-d58acaaebf7d` |
| 11:39:43.853 | pro | `GET …/state` (control) | 200 | 1,998.8 ms | `35321446-c67c-4265-8687-cd51e0075c74` |
| 11:39:48.137 | pro | `GET …/result` (control) | 200 | 1,384.5 ms | `fd553666-3a0c-4f86-9f0b-df0dd5e9f09c` |
| 11:39:52.570 | pro | `GET …/stream` (control) | 200 | 1,616.0 ms | `d1140d2e-fc49-45eb-a607-cd36cded141f` |
| 11:39:58.169 | free | `GET /jobs/?limit=100` | 200; foreign job absent | 2,160.3 ms | `8ea5afe5-9b65-4fba-893d-4058dc381f82` |

**Verdict:** PASS for data isolation; owner-only state/result/stream/cancel. Same 403 existence oracle as comments (SEC-D03). Admin/support do not bypass the product API.

### 4.6 PDFs and render artifacts

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:40:02.411 | free | `GET /resumes/fd794343…/latest-accepted-artifact` | **404** | 1,190.5 ms | `d0e76a73-ee4c-424f-99fb-040170eecd0b` |
| 11:40:06.695 | admin | same | **404** | 1,232.6 ms | `7f2b244e-5096-4ec3-82d6-993377d5d6c6` |
| 11:40:11.387 | pro | same | **200**, artifact `f3b7502f…` | 1,641.3 ms | `dd874787-6c17-4367-9cad-302f1d8e1b31` |
| 11:53:37.664 | pro | `GET /download/25f2ce19…/preview/f3b7502f…` | **200**, PDF | 2,438.9 ms | `cdb4e50a-5c16-4483-a27d-b076d2d84251` |
| 11:53:42.027 | free | same | **404** `Render artifact is unavailable` | 1,311.5 ms | `588b17b2-65f5-47b8-b02f-b7d90ec1c699` |
| 11:53:46.248 | anonymous | same | **404** | 1,173.6 ms | `c3e8bd52-109a-41eb-9e88-a70c83388aa3` |
| 11:53:50.662 | admin | same | **404** | 1,368.1 ms | `1538cf0d-e8c6-4fbb-a39f-ef8c3408050c` |
| 11:53:55.093 | free | `GET …/preview/f3b7502f…/geometry` | **404** | 1,371.8 ms | `156a5bd0-d2cb-439f-ad1a-a5c942fcd9e2` |
| 11:54:00.412 | pro | same | **200** | 2,274.0 ms | `a5363a33-58bd-4e1a-9b94-7bb3dbf17d9f` |

**Verdict:** PASS. The artifact API is owner-scoped even for an admin/support actor; bytes are streamed by the API rather than exposed as a presigned URL. The public share PDF is the only presigned artifact path found.

### 4.7 Presigned URL checks

| Time (UTC) | Check | Result | Latency |
|---|---|---|---|
| 11:38:24.127 | `GET /share/{token}` returns `pdf_url` | 509-char URL; `X-Amz-Expires=3600`; `X-Amz-Date=20261127T114016Z`; host `2ca2c91c…r2.cloudflarestorage.com`; path prefix `/latexy/render-artifacts/v1/5ea2c0d1…` | 1,531.7 ms |
| 11:40:19.452 | unauthenticated GET of issued URL | **200 `application/pdf`** | 588.3 ms |
| 11:40:22.818 | second unauthenticated GET | **200** | 314.8 ms |
| 11:40:25.975 | signature changed by one byte | **403** | 106.0 ms |
| 11:46:38.951 | same URL after share revocation | **200** | 292.2 ms |
| 11:54:07–11:54:29 | freshly minted 3600 s / 1 s / tampered-key URLs via deployment storage credentials | **status 0** (no HTTP response; 4.1 s each) | blocked |

**Verdict:** the presigned URL is a bearer capability: it is not bound to the caller, by design for a public share. Signature validation is enforced. Actual expiry and key tamper could not be exercised because the direct R2 probe returned no HTTP status; the 3600 s TTL is explicit in the URL. The revocation gap is the material finding (SEC-D01). The `pdf_url` remains valid until 12:40:16Z.

### 4.8 Portfolios

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:34:55.278 | pro | `POST /portfolio/setup` enabled | 200 | 4,504.4 ms | `5681e547-2a18-4bdd-b04e-e78a66520d82` |
| 11:34:59.475 | pro | `PATCH /resumes/{id}` portfolio-visible | **405** (wrong route; use PUT) | 1,147.3 ms | `e60e5bb0-f085-4d8b-a982-98e5c9cfb08f` |
| 11:52:58.695 | pro | `PUT /resumes/60f36508…` `{portfolio_visible:true}` | 200 | 1,345.4 ms | `f303e510-2d50-4768-a73f-0fb28b1a1973` |
| 11:53:02.787 | anonymous | `GET /portfolio/auditsec-103328` | 200, one resume | 1,046.9 ms | `ef267e8e-ad2c-4e8d-af00-61087da389bd` |
| 11:53:07.103 | free | `PUT /resumes/60f36508…` `{portfolio_visible:false}` | **404** | 1,268.8 ms | `bfb8e733-825c-4190-b781-33f4b6a22a8e` |
| 11:53:11.199 | anonymous | portfolio after free attempt | 200, resume still present | 1,049.1 ms | `70294194-c5f3-4376-8472-71fb11f72aeb` |
| 11:53:15.530 | pro | `PUT /resumes/60f36508…` `{portfolio_visible:false}` | 200 | 1,286.1 ms | `2ce69958-3f14-406e-92c3-11142a85b45b` |
| 11:53:19.605 | anonymous | portfolio after owner unpublish | 200, empty resume list | 1,031.8 ms | `88777a6d-4e20-4970-ac6a-98d0c704d845` |
| 11:53:23.873 | free | `POST /portfolio/setup` with pro username | **409** `Username already taken` | 1,224.8 ms | `aacd85d4-616b-4312-9ce7-4d1e59f65620` |
| 11:53:28.129 | pro | `POST /portfolio/setup` `{portfolio_enabled:false}` | 200 | 1,212.7 ms | `1a63f664-8ab6-4041-b20f-e267c00bf607` |
| 11:53:32.183 | anonymous | `GET /portfolio/auditsec-103328` after disable | **404** | 996.0 ms | `75adf4b2-8ffe-4a9d-8c7d-b26f36d278f0` |

**Verdict:** PASS. Publication is owner-controlled; a foreign user cannot unpublish or take the username; disabling the portfolio stops public serving. The initial 405 was a test-method error, not an authorization bypass. The first portfolio capability test ran with `resumes=[]` because of that 405; the clean follow-up exercised a portfolio containing one resume. The g12 capability test still exercised the endpoint gate, but not a populated resume list (see limitations).

### 4.9 Tracker

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:35:47.347 | pro | `POST /tracker/applications` | 201 | 2,587.7 ms | `78f0ce47-72b7-4c6e-ab93-41e5a3b4fd81` |
| 11:40:50.938 | free | `GET /tracker/applications/301014d9…` | **404** | 1,194.1 ms | `276223ce-9b3f-4c97-95ff-fef7af7b13ef` |
| 11:40:55.213 | free | `PUT …` | **404** | 1,224.1 ms | `e52241d4-2089-41a2-aaa1-1eb664619c4d` |
| 11:40:59.475 | free | `PATCH …/status` | **404** | 1,208.8 ms | `cd23b1c5-094c-4646-a4a3-4b241201e2f9` |
| 11:41:04.885 | free | `DELETE …` | **404** | 2,359.5 ms | `661a0d0d-cd7a-4669-bf10-1f762678f191` |
| 11:41:12.370 | free | `GET …/reminders` | **404** | 4,433.5 ms | `83ee0a5d-e46a-408d-aac6-e22758c6c9d3` |
| 11:41:17.213 | pro | `GET …` (control) | 200 | 1,204.9 ms | `546eaf80-cfda-4a72-8c0d-d454249c878c` |
| 11:41:21.659 | free | `GET /tracker/applications?flat=true` | 200; foreign item absent | 1,207.6 ms | `0c774537-b3ea-42be-bd23-8569d803f1c3` |
| 11:41:26.132 | pro | `POST …/reminders` | 201 | 1,271.9 ms | `4689a33f-5e89-4159-949f-de9334a7e84a` |
| 11:41:31.573 | free | `DELETE …/reminders/{id}` | **404** | 1,201.9 ms | `ed43ccc9-a038-4ef4-8100-01e2e488c459` |
| 11:41:35.849 | pro | `DELETE …/reminders/{id}` (control) | 204 | 1,175.0 ms | `63ef06fe-cd8c-4805-b167-b9fb6761c1bd` |

**Verdict:** PASS. All tracker sub-resources are user-scoped and use 404.

---

## 5. Team seats and tenant isolation

### 5.1 Team seats

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:41:37.920 | team-owner | `GET /team/seats` | 200 | 1,182.5 ms | `976dda31-ed70-443d-90a3-9a2c4b545b1f` |
| 11:41:42.164 | team-member | `GET /team/seats` | **403** `Team plan required` | 1,193.2 ms | `54dedfb3-c866-4f30-b1bd-0ae97b53f1db` |
| 11:41:46.538 | team-member | `POST /team/invite` | **403** | 1,320.7 ms | `f8752b4f-fd80-4eb7-98c7-66ed2e1d94cc` |
| 11:41:50.849 | free | `POST /team/invite` | **403** | 1,259.5 ms | `dbe1ac4e-5e10-4f66-bede-2f4497b9c3f5` |
| 11:41:55.068 | free | `GET /team/seats` | **403** | 1,168.1 ms | `645573d2-a4a3-4e86-ac59-785caa2923ca` |

**Verdict:** PASS. The live `team-member` has `subscription_plan=team_member`, so the route's plan check correctly denies owner-only seat actions. No seat was created. See the hardening note in §9.

### 5.2 Tenants

Tenant A: `577149dd-ff83-4409-9d66-a14d61cb8a60` (`audit-team-20261127103328`), owner `team-owner`, one member `team-member`. Tenant B was created only for the isolation test: `3f98ed40-fcb0-4766-8dd0-e0f6807aa2b5` (`audit-sec-b-103328`), owner `team-owner`, one cohort `5898602a-6a2d-4366-a8fc-fb3f2d1c9279`.

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:36:21.824 | team-owner | `POST /tenants` tenant B | 201 | 1,542.0 ms | `9ca938eb-904b-46a3-837f-9018abf304d6` |
| 11:36:26.227 | team-owner | `POST /tenants/{B}/cohorts` | 201 | 1,352.0 ms | `e66a03a5-53d4-4280-ab0b-6b5ea73c9f6f` |
| 11:41:59.326 | team-member | `GET /tenants/{B}/members` | **403** `Access denied` | 1,207.3 ms | `2b55658e-5484-430c-b6cb-cd2814943f17` |
| 11:42:03.578 | free | `GET /tenants/{B}/members` | **403** | 1,200.7 ms | `34ef9d74-33be-4aa6-8499-42fbad6791c5` |
| 11:42:07.817 | admin | `GET /tenants/{B}/members` | **403** | 1,198.9 ms | `01bf3e23-4f77-4790-a025-f29578105402` |
| 11:42:12.078 | team-member | `GET /tenants/{B}/cohorts` | **403** `Access denied: owner or admin required` | 1,210.1 ms | `d304bb7e-ec3b-4257-ac50-86d11d58342e` |
| 11:42:16.350 | team-member | `POST /tenants/{B}/cohorts` (no body) | 422 validation | 1,221.8 ms | `98b73e96-4326-4526-8754-3d08df321e5a` |
| 11:42:20.634 | team-member | `PATCH /tenants/{B}` | **403** `Access denied: owner or admin required` | 1,233.9 ms | `a9db3dc1-35e8-4384-86af-38c399e1a1eb` |
| 11:42:25.106 | team-owner | `PATCH /tenants/{B}` | 200 | 1,420.8 ms | `99cc0f8e-a290-4038-abee-875e36da5525` |
| 11:42:29.374 | team-member | `GET /tenants/{A}/members` (own roster) | 200 | 1,213.6 ms | `276c603e-04e7-452f-9d7a-17a059a6a727` |
| 11:42:33.668 | team-member | `PATCH /tenants/{A}` | **403** | 1,243.3 ms | `8eefae92-6f76-4583-a99c-9e2150752035` |
| 11:42:37.981 | team-member | `POST /tenants/{A}/cohorts` | **403** | 1,262.0 ms | `a91cf753-9c2f-445d-b0f8-e6124b445c4b` |
| 11:42:42.262 | team-member | `POST /tenants/{A}/members/invite` | **403** | 1,229.9 ms | `a8fd472c-a1ac-42b3-a117-a22c2d602e9a` |
| 11:42:46.513 | team-member | `GET /tenants/my` | 200; tenant A only, B absent | 1,199.5 ms | `94f6f269-ee6d-4ab3-8c05-07744cfd4224` |
| 11:42:50.743 | team-owner | `GET /tenants/my` | 200; A + B | 1,177.4 ms | `ee202193-8a9d-470f-980c-532b392ee10f` |
| 11:42:55.037 | team-member | `POST /tenants` (tenant C) | **403** `Team plan or platform administrator access required` | 1,242.8 ms | `b2cc863a-bd70-4f23-a531-4c448c6866da` |
| 11:43:00.117 | anonymous | `GET /tenants/resolve-host?host=nonexistent-audit.invalid` | 200 `{tenant:null}` | 1,372.9 ms | `8756a6a1-f83c-4570-8043-328da23b38b6` |

The valid-body retry of `POST /tenants/{B}/cohorts` (after the 422 harness error) returned **403 `Access denied: owner or admin required`**, request id `be2ff4b9-5f2d-484e-9a42-e12afa4979b3`, during cleanup. It confirms the first 422 was a missing-body artifact, not an authorization gap.

**Verdict:** PASS for tenant isolation. Membership is checked before tenant data; a member of tenant A cannot read tenant B's roster or cohorts, cannot mutate tenant B, and cannot create a tenant. The tenant owner can read/update own tenants and sees both owned tenants. Platform admin is also denied on the tenant membership API because it is not a tenant member; admin has the separate `/admin/users/{id}/360` surface. That is a policy choice worth confirming (see §9), not a cross-tenant leak.

---

## 6. Developer API keys

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:36:17.227 | developer-api | `POST /developer/keys` (`scopes:["ats"]`) | 201, prefix `lx_sk_hIyM…` | 16,347.7 ms | `f3b04f28-7a63-47b0-8abb-462f926bfd14` |
| 11:43:03.890 | developer-api | `GET /api/v1/jobs/00000000…` | 404 `Job not found` (key authenticated) | 1,378.1 ms | `48fb4335-62f9-4ee8-8154-1bc1b7ca901e` |
| 11:43:08.091 | developer-api | `GET /api/v1/jobs/00000000…/pdf` | **403** `API key lacks 'export' scope` | 1,151.0 ms | `d4529c25-aed0-481f-ab23-89f0db483bc9` |
| 11:43:12.333 | developer-api | `GET /developer/keys` | 200, own key only | 1,202.5 ms | `91b28e9c-5b6e-4eb6-8bcc-975253d861dc` |
| 11:43:16.568 | free | `DELETE /developer/keys/f597d64e…` | **404** `Developer API key not found` | 1,184.2 ms | `774553ca-a462-4b74-a8f5-4560ba83d921` |
| 11:43:20.794 | free | `GET /developer/keys` | 200, own keys only | 1,175.7 ms | `090e0f79-fe2a-4008-870a-9400f4c98625` |
| 11:43:25.045 | developer-api | `DELETE /developer/keys/f597d64e…` | 204 | 1,199.9 ms | `bed01057-4a45-4b14-9457-98aa72296818` |
| 11:43:29.257 | anonymous | same key on `GET /api/v1/jobs/…` | **401** `Valid developer API key required` | 1,162.0 ms | `5467f328-5ce7-4ffc-a785-540dd607a73c` |

**Verdict:** PASS. Keys are user-scoped for management and revocation; scopes are enforced before the handler; revocation invalidates the key immediately. The 16.3 s key-create latency is noted for the performance auditor, not a security defect. The pre-provisioned matrix key from `identity-matrix.json` was not used (PB-H01 applies); a real `lx_sk_` key was minted through the API.

---

## 7. GDPR exports and deletion

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:35:52.639 | pro | `POST /account/gdpr/exports` | 202; request `e6a5b566…`; token 254 chars; expires 12:05:53Z | 2,240.9 ms | `1ff7e948-ac13-4e0e-876d-75940c9c07e7` |
| 11:43:34.352 | free | `GET /account/gdpr/requests/e6a5b566…` | **404** `Request failed.` | 2,040.6 ms | `c68645f4-9195-4813-9468-74b0fc2c4813` |
| 11:43:38.573 | free | `GET /account/gdpr/exports/e6a5b566…/download` with pro token | **404** | 1,170.0 ms | `72b68e4c-5fc1-443f-a231-a13646f1f9cd` |
| 11:43:42.942 | pro | same download with own token | **200**, JSON envelope | 1,318.4 ms | `1c033af5-167f-4ed6-8aa3-60e097166bb0` |
| 11:43:47.170 | free | `GET /account/gdpr/requests?limit=100` | 200; 3 own requests, pro export absent | 1,176.3 ms | `2bafcc2b-9308-4ffe-84c7-b6c998992aba` |
| 11:43:51.415 | free | `GET /account/gdpr/requests/98a1e187…` (own rejected deletion) | 200 | 1,193.8 ms | `71846f5e-06d4-4b70-a5a1-31b145230e4d` |
| 11:43:55.632 | pro | `GET /account/gdpr/requests/98a1e187…` (free’s) | **404** | 1,163.2 ms | `ea52b979-3f35-46a0-ac38-99cd3eec75a9` |
| 11:43:59.840 | pro | `POST /account/gdpr/deletion/98a1e187…/cancel` | **404** | 1,156.7 ms | `5d8090ec-6bf1-443a-a06f-987964109723` |
| 11:44:04.111 | free | same cancel (own, rejected) | 409 `not_cancellable` | 1,219.8 ms | `a0aa0a8d-b90f-48c1-a57c-9b3997990210` |

**Verdict:** PASS. Export creation, read, download and cancellation are owner-scoped; the download token is additionally bound to the owner (cross-user token use 404). The pro export downloaded successfully with a 200 and a signed manifest. No deletion was executed; the free identity’s pre-existing rejected request was only read and a non-destructive cancel was attempted.

---

## 8. Admin vs support vs user boundaries

| Time (UTC) | Identity | Request | Result | Latency | Request id |
|---|---|---|---|---|---|
| 11:44:10.002 | support | `GET /admin/users/{free}/360` | **200**, `pii_masked:true` | 2,840.3 ms | `52b4f2c3-7f09-475a-aae7-b453d492267a` |
| 11:44:15.927 | admin | same | **200** | 2,874.1 ms | `a22d4626-2050-4821-9466-451d1078d64b` |
| 11:44:21.806 | free | same | **403** `Support or admin privileges required` | 2,824.5 ms | `cd8a86d3-2aeb-48d1-b3d7-1f643a44daa6` |
| 11:44:26.057 | support | `GET /admin/feature-flags` | **403** `Admin privileges required` | 1,199.5 ms | `04cca269-c117-4701-832e-1f7ea06b6d3d` |
| 11:44:30.553 | admin | `GET /admin/feature-flags` | **200** | 1,444.9 ms | `858b2f10-c94b-459b-b971-54f966408e7e` |
| 11:44:34.811 | support | `GET /admin/entitlements` | **403** | 1,207.6 ms | `482f16c0-8865-4147-bf28-f95f0fdf7ffc` |
| 11:44:39.055 | support | `GET /admin/audit?limit=5` | **403** | 1,193.1 ms | `c4e33f5f-9d86-478c-9366-ab7878e196e3` |
| 11:44:43.324 | support | `GET /admin/gdpr/requests?limit=5` | **403** | 1,211.4 ms | `f8032593-c90c-4a2a-aef5-74a365db79f7` |
| 11:44:47.562 | support | `GET /admin/view-as/sessions` | **403** | 1,187.0 ms | `f179ec33-ff38-4d62-be1d-75359a0d5c17` |
| 11:44:51.775 | admin | `GET /admin/view-as/sessions` | **200**, own sessions | 1,162.1 ms | `6d61dc44-b120-490c-9645-896a7cda8218` |
| 11:44:55.983 | support | `POST /admin/users/{free}/reveal-pii` | **403** | 1,157.1 ms | `500f7a8a-200d-4439-b26d-9495e24a6bec` |
| 11:45:00.179 | support | `POST /admin/users/{trial-expired}/plan` | **403** | 1,145.0 ms | `2c4f86d8-462c-4ae2-a200-ff9c5a735ab3` |
| 11:45:04.386 | support | `POST /admin/users/{trial-expired}/features/revoke` | **403** | 1,152.3 ms | `24aed419-df8c-440f-bbff-db2ee0f5e217` |
| 11:45:08.646 | free | `POST /admin/users/{free}/features/grant` | **403** | 1,209.2 ms | `37bfd31b-67e3-41ee-8735-bbb0337dea92` |
| 11:45:13.055 | admin | `GET /jobs/25f2ce19…/state` (product API) | **403** `Access denied` | 1,357.8 ms | `6a73969e-87fc-4851-aa08-9621afd2d5e8` |
| 11:36:43 | admin | `GET /resumes/fd794343…` (product API) | **404** | 1,224.1 ms | `6fa672c0-fe1e-4ec2-86ea-9892e494716c` |

**Verdict:** PASS. Support has the intended masked user-360 read and is denied every admin-only control surface. Admin can read flags/entitlements/audit/view-as but does not bypass product data ownership. Free users have no admin path. The `support` 360 response showed `pii_masked:true`, so the support role did not receive the raw email/name in that payload. No mutation was performed by a denied role (all 403s occurred before writes; the trial-expired plan/status remained `free/expired`).

---

## 9. Capability revocation

Per-account overrides were used instead of global capability changes. The admin API wrote `users.user_metadata.entitlement_overrides`; cleanup removed the override key.

| Capability | Revoke | Observed while revoked | Restore | Observed after restore |
|---|---|---|---|---|
| `f01` (public share) on pro | 11:45:18.678 200 `e558cdec…` | `GET /share/{token}` **404** 11:45:22.758 `5a56a41f…` | 11:45:28.336 200 `a6babb09…` | `GET /share/{token}` **200** 11:45:32.956 `add2db55…` |
| `g12` (portfolio) on pro | 11:45:45.870 200 `adcfdd84…` | `GET /portfolio/auditsec-103328` **404** 11:45:49.928 `721c36bd…` | 11:45:55.411 200 `fed3c83c…` | `GET /portfolio/…` **200** 11:45:59.525 `5c40eb30…` |
| `f04` (collaboration) on free | 11:46:09.258 200 `f9977015…` | control was already **404** because the collaborator had been removed at 11:38:15 | 11:46:18.993 200 `1aa8ab4a…` | still **404** 11:46:23.217 `fe23dd3f…` |

**Verdict:** f01 and g12 revocation are enforced immediately at the public endpoint and restored by a grant. The f04 test is **invalid**: the collaborator was removed before the test, so the control, revoked and restored cases were all 404. Do not cite it as evidence of f04 enforcement. The separate collaborator-row removal test did show immediate revocation: `DELETE collaborator` 204 → `GET resume` 404 (11:38:15 → 11:38:19).

The g12 test ran while the portfolio had no published resumes because the initial 405 prevented the publish. The endpoint gate itself is proven, but a populated-portfolio revocation was not re-run before the time cap.

**Hardening note:** `_require_team_owner` (`backend/app/api/team_routes.py:153-168`) and tenant provisioning (`backend/app/api/tenant_routes.py:459-483`) gate owner-only actions on `subscription_plan == "team"`, not on a `team_seats`/tenant owner row. Today the team-member identity is `team_member`, so all such actions are 403. If a tenant member ever has `subscription_plan="team"` — the identity matrix originally recorded that — the same member would pass the owner gate and could invite seats or create tenants. Recommend deriving the check from the seat/tenant ownership row and adding a test for a `team`-plan member.

---

## 10. Cross-cutting observations

1. **First-pass test contamination:** the initial resume/comment negative tests ran after `free` had been made a viewer. The 200s (`da2c8740…`, `f7b51c7f…`) are correct collaborator behaviour. The clean no-collaborator rerun at 11:52Z is authoritative.
2. **No 429 / no 5xx:** 195 requests, 17/min cap, zero 429 and zero 5xx. Two transient 401s on the clean-resume setup at 11:50:30 and 11:50:49 (`b6534ea6…`, `87945fff…`) were followed by a 201 at 11:52:12 after the probe’s identity alias was corrected; they are test-harness issues, not product failures. (The raw ledger shows these as 401; they are not counted as security results.)
3. **404 discipline is inconsistent:** resumes, artifacts, tracker and GDPR use 404 for unauthorized objects; jobs and comments use 403 with area-specific messages (SEC-D03).
4. **Admin is not a product superuser:** admin/support get 403/404 on product job/resume data; tenant API access also requires tenant membership. This is a defensible least-privilege design; support uses the masked 360 view instead.
5. **Share tokens are long-lived while share PDF URLs are 1 h:** the share token itself has no expiry; revocation nulls it. The presigned URL outlives revocation for up to 1 h (SEC-D01).
6. **Matrix discrepancy:** `identity-matrix.json` says team-member plan `team`; the live DB says `team_member`. The live DB prevented owner-only actions. Recorded as a data discrepancy, not a defect.

---

## 11. Test data, writes and cleanup

### 11.1 Per-account writes (all intentional)

| Time (UTC) | Identity | Write | Status |
|---|---|---|---|
| 11:34:48 | pro | Resume `fd794343-6f9b-4658-bfb2-e5e0f17c73f4` + one compile job `25f2ce19…` | Resume deleted 11:47:13; job/finalization retained with `resume_id=NULL` |
| 11:34:55 | pro | Portfolio `auditsec-103328` enabled | Disabled + username cleared during cleanup |
| 11:35:34 | pro | Share token on resume | Revoked 11:46:27 |
| 11:35:41 | pro | Comment `e50920a6…` | Deleted 11:47:09 |
| 11:35:47 | pro | Tracker application `301014d9…` | Deleted 11:47:01 |
| 11:35:52 | pro | GDPR export `e6a5b566…` | Retained (ready until 12:05:53Z) |
| 11:35:57 | pro | Collaborator `free` (viewer) | Removed 11:38:15 |
| 11:36:17 | developer-api | Developer key `f597d64e…` | Revoked 11:43:25 |
| 11:36:21 | team-owner | Tenant B `3f98ed40…` | Deleted via DB during cleanup |
| 11:36:26 | team-owner | Cohort `5898602a…` | Deleted via DB during cleanup |
| 11:38:42 | anonymous | Review comment `c13de9d1…` | Deleted via DB during cleanup |
| 11:52:12 | pro | Clean resume `60f36508…` + comment `8f56d268…` | Comment deleted 11:54:33; resume deleted 11:54:40 |
| 11:45:18–11:46:18 | admin | Six `user.feature.revoke/grant` audit rows (f01, g12, f04) | Retained by audit exception; overrides removed |
| 11:51:47 | pro | Accidental curl probe resume `1a213551…` | Deleted 204 |

### 11.2 Cleanup verification

- **Capability overrides:** removed from `users.user_metadata` for pro, free and trial-expired; verified `{}` for all three. The admin audit rows remain (six rows, actor `8b2ee54b…`).
- **Automatic cleanup:** the first probe’s `db_restore` failed with `ConnectionDoesNotExistError` after the long run. A fresh-connection manual cleanup succeeded. The raw evidence file’s `cleanup.db_restore_error` is stale; the final DB state is clean. The follow-up script also reports the same stale field from the first run.
- **Resume/comments/tracker:** pro fixture resume, clean follow-up resume, both comments, tracker application and reminder all deleted (DB counts 0; API 404 for the deleted resume).
- **Share/review comment:** share revoked; public share and review comments 404; review comment deleted (DB count 0).
- **Portfolio:** `auditsec-103328` username cleared, portfolio disabled, theme reset to `minimal`; public 404. Free’s pre-existing `audit-free-20261127` username was left untouched.
- **Tenant B/cohort:** deleted from `tenants`, `tenant_members`, `tenant_domain_events` and `workspaces`; no `audit-sec-%` tenants remain. No tenant C was created.
- **Developer key:** revoked (`is_active=false`); 401 with the old key.
- **Retained evidence:** GDPR export `e6a5b566…` (ready until 12:05:53Z); compilation `477643e9-b70b-4ac0-9c2b-603eaaab8060` and job finalization `25f2ce19…` (`resume_id=NULL`); R2 object `render-artifacts/v1/5ea2c0d1…/pdf/c429…pdf`; admin audit rows for the overrides. Cleanup owner: cleanup auditor / artifact lifecycle.
- **No touch:** team seats, subscriptions, team billing, admin/support sessions, free’s pre-existing portfolio username, and the concurrent `basic-annual` plan-change rows from another sub-agent.

### 11.3 Analytics exclusion

Use identity emails `audit+pro-monthly-20261127103328@example.test`, `audit+free-20261127103328@example.test`, `audit+team-owner-…`, `audit+team-member-…`, `audit+admin-support-…`, `audit+admin-superadmin-…`, `audit+developer-api-…`, `audit+student-…`, `audit+trial-expired-…` and the window **2026-11-27T11:34:47Z – 11:54:40Z**. Tenant slugs `audit-team-20261127103328` and the deleted `audit-sec-b-103328` identify tenant traffic. If a dashboard cannot exclude these identities, that is an analytics finding for the analytics auditor.

---

## 12. Limitations / blocked

1. **f04 capability revocation** — invalid due to test ordering; the collaborator was removed before the override test. Only collaborator-row revocation was proven. Do not claim f04 enforcement.
2. **Presigned URL actual expiry** — the 1-second and tampered-key URLs generated from the harness got no HTTP response (status 0, ~4.1 s each). The original share `pdf_url` did fetch (200); signature tampering 403; TTL is 3600 s in the query. Expiry enforcement is therefore **unverified**; the revocation gap (SEC-D01) is verified.
3. **g12 with a populated portfolio** — the g12 revocation test ran while the portfolio had `resumes:[]` because the initial publish used `PATCH` (405). The clean follow-up proved a populated portfolio serves and is owner-controlled, but the g12 revoke/restore was not repeated on the populated version.
4. **No WebSocket collaboration / presence** — `/ws/collab/{resume_id}` was not exercised; the HTTP collaborator authorization and removal path were. The events auditor owns the WS surface.
5. **No UI** — all checks are API-level; no React state, routing or client-side authorization was tested. A UI that renders hidden controls is not evidence of server enforcement either way.
6. **No real cross-tenant customer data** — tenant B was synthetic and contained only one empty cohort. There was no second real tenant with resumes/analytics, so tenant isolation is proven for the tested endpoints, not for every tenant-scoped feature.
7. **No live payment or deletion execution** — GDPR deletion was not executed; the free identity’s pre-existing rejected request was read and a non-destructive cancel was rejected with 409. No live checkout/payment.
8. **Rate probe** — 17/min cap, not the full 20/min; no 429 was deliberately induced. The shared auth rate-limit defect (AAG-D01) is outside this pass.

---

## 13. Defect references

| ID | Severity | Summary |
|---|---|---|
| SEC-D01 | **P2** | Public share revocation does not invalidate an already-issued 1-hour presigned PDF URL; old URL returned 200 after the share 404ed. |
| SEC-D02 | **P2** | Collaborator `GET /resumes/{id}` discloses the owner’s live `share_token`/`share_url`; removing the collaborator does not rotate the public link. |
| SEC-D03 | **P3** | Job and comment unauthorized reads return 403 with distinct messages, revealing that a guessed UUID exists; resumes/tracker return 404. |
