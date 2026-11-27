# Front-end page audit - results

**Verdict:** all 44 routes load in production, but the page-by-page audit found a blocked core flow (Optimize), a broken path for imported/legacy LaTeX resumes, a 21,101px admin capability page, consent overlays on critical forms, missing accessible names, and several misleading empty states/metrics. Cover-letter generation also stays at 'Generating…' for 45s with no logs or error (FE-13). The share/review journey found a P1: compiled share links cannot render their PDF because the R2 artifact URL is blocked by CORS (FE-16).

## Coverage

| Metric | Result |
|---|---|
| Routes inventoried | 44 |
| Routes loaded | 44 / 44 returned HTTP 200 |
| Roles exercised | anonymous, free, pro, admin, team |
| Desktop viewport | 1440x900 |
| Mobile viewport | 390x844 |
| Console errors | 4 pages (share, tenant-invite, workspace-builder, workspace-variant) |
| Horizontal overflow | 0 desktop, 0 mobile |
| Missing H1 | 3 pages (workspace-edit, workspace-optimize, workspaces-detail) |
| Pages with unlabeled interactive controls | 10 |

## In-app browser verification

A separate read-only pass used the T3 Code in-app browser at 1279x799 (logged-in default profile) plus an incognito tab for anonymous pricing, and the person's 741x1362 tab for the header annotation. It confirmed, live:

- Optimize stays a **blank page + spinner for ~25-30s** (FE-01).
- Templates shows **"0 TEMPLATES" at 3s**, then **61 at ~12s** (FE-15).
- Anonymous pricing shows **no prices** and the consent panel covers plan cards/CTAs (FE-05/FE-03).
- Admin is **21,105px** with **925 visible buttons** (FE-04).
- Billing shows bare "Loading plans..." / "Loading subscription state..." for ~12s and fires **five** subscription requests (new FE-17).
- Dashboard KPI cards are empty boxes before data arrives (FE-17).
- Cover letter has **2 unlabeled controls** (FE-12); settings has **1** (FE-07).

Full notes and screenshots: [`browser-review-2026-11-27.md`](browser-review-2026-11-27.md), `browser-review/`.

## Per-page results

| Page | Role | Status | H1 | DOM | Small text | Unlabeled | Console/HTTP | Notes |
|---|---|---|---:|---:|---:|---:|---|---|
| `/accessibility` | anon | 200 | 1 | 239 | 2 | 0 |  |  |
| `/admin` | admin | 200 | 1 | 6135 | 469 | 1 |  | 165-capability matrix renders 21,101 px / 930 buttons; needs virtualization. |
| `/admin/tenant` | admin | 200 | 1 | 191 | 4 | 0 |  | Works, but no navigation link to this route (TEN-01). |
| `/billing` | pro | 200 | 1 | 1328 | 6 | 0 |  | Shows ₹299 Basic / ₹599 Pro; pricing page hides these prices. |
| `/byok` | pro | 200 | 1 | 256 | 13 | 0 |  | Copy promises direct provider access; PB-D03 routes OpenAI keys to the platform proxy. |
| `/dashboard` | free | 200 | 1 | 490 | 45 | 1 |  | 'Avg Compile Latency 3.5s' understates the measured 20.7s; 0%/100% empty-state semantics. |
| `/developer` | pro | 200 | 1 | 301 | 6 | 0 |  |  |
| `/faq` | anon | 200 | 1 | 253 | 2 | 0 |  |  |
| `/forgot-password` | anon | 200 | 1 | 227 | 2 | 1 |  |  |
| `/` | anon | 200 | 1 | 612 | 43 | 0 |  |  |
| `/login` | anon | 200 | 1 | 263 | 3 | 2 |  | Consent banner covers the lower sign-in options (GitHub/passkey). |
| `/platform` | anon | 200 | 1 | 342 | 2 | 0 |  |  |
| `/u/auditfe20261127` | anon | 200 | 1 | 238 | 2 | 0 |  |  |
| `/pricing` | anon | 200 | 1 | 311 | 3 | 0 |  | No prices shown; asks user to sign in while billing shows prices. |
| `/privacy` | anon | 200 | 1 | 280 | 2 | 0 |  |  |
| `/reset-password` | anon | 200 | 1 | 231 | 2 | 0 |  |  |
| `/resources` | anon | 200 | 1 | 301 | 2 | 0 |  |  |
| `/settings` | free | 200 | 1 | 490 | 23 | 1 |  |  |
| `/r/xC_40DHizO7gxGhA2fdsAuG62aMPoX1P` | anon | 200 | 1 | 233 | 4 | 0 | 1/1 | 'Link unavailable' when the resume has no accepted artifact; generic error. |
| `/signup` | anon | 200 | 1 | 262 | 2 | 4 |  | 4 unlabeled interactive controls; consent banner overlaps form. |
| `/templates` | anon | 200 | 1 | 1170 | 63 | 0 |  | 61 templates; consent banner covers first row; 63 small-text elements. |
| `/tenant-invite` | anon | 200 | 1 | 260 | 3 | 2 | 1/1 | Redirects to login; host-resolution request returned 429 during sweep. |
| `/terms` | anon | 200 | 1 | 405 | 2 | 0 |  |  |
| `/tracker` | free | 200 | 1 | 230 | 3 | 0 |  | Clean empty state; Add Application form inputs lack labels. |
| `/try` | anon | 200 | 1 | 399 | 14 | 0 |  |  |
| `/two-factor` | anon | 200 | 1 | 238 | 2 | 1 |  |  |
| `/updates` | anon | 200 | 1 | 370 | 2 | 0 |  |  |
| `/verify-email` | free | 200 | 1 | 231 | 3 | 0 |  |  |
| `/workspace` | free | 200 | 1 | 403 | 5 | 0 |  | Onboarding modal blocks the resume library on first visit. |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/batch-tailor` | free | 200 | 1 | 230 | 3 | 1 |  |  |
| `/workspace/builder/70e3fa53-0f92-4b64-8a0d-8ce256639f32` | free | 200 | 1 | 207 | 3 | 0 | 1/1 | 404 /resumes/{id}/builder/v1 for a LaTeX-created resume. |
| `/workspace/builder/new` | free | 200 | 1 | 404 | 3 | 0 |  |  |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/career` | free | 200 | 1 | 228 | 7 | 0 |  |  |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/cover-letter` | free | 200 | 1 | 335 | 15 | 2 |  |  |
| `/workspace/cover-letters` | free | 200 | 1 | 203 | 3 | 0 |  |  |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/edit` | free | 200 | 0 | 315 | 23 | 0 |  | Read-only for legacy LaTeX resume; no H1; no clear source-edit CTA. |
| `/workspace/history` | free | 200 | 1 | 250 | 9 | 0 |  |  |
| `/workspace/merge` | free | 200 | 1 | 215 | 3 | 1 |  |  |
| `/workspace/new` | free | 200 | 1 | 1197 | 64 | 0 |  |  |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/optimize` | free | 200 | 0 | 138 | 2 | 0 |  | 25s+ 'Checking feature availability' spinner on legacy resume; no skeleton/timeout. |
| `/workspace/variant/70e3fa53-0f92-4b64-8a0d-8ce256639f32` | free | 200 | 1 | 190 | 3 | 0 | 1/1 | 409 'This is not a source-linked builder variant' for a normal resume. |
| `/workspaces` | team | 200 | 1 | 236 | 3 | 0 |  |  |
| `/workspaces/bf531756-d928-4b3d-a79d-b666e7415cf0` | team | 200 | 0 | 263 | 3 | 1 |  | No H1; otherwise clean empty workspace. |
| `/workspaces/bf531756-d928-4b3d-a79d-b666e7415cf0/recruiter` | team | 200 | 1 | 215 | 3 | 0 |  |  |

## Interaction journey: guided builder

- Created a builder resume through `/workspace/builder/new` (POST `/resumes/builder/v1` 201).
- Filled Profile & Summary (name, headline, email, phone, location, links, summary); completeness moved 0% → 35%.
- Clicked Preview PDF; the button showed 'Preparing PDF…' for ~20-60 s, then rendered the PDF with a Download button.
- Builder resume opens the Optimize and Cover Letter pages; a legacy LaTeX resume does not.
- No console/page errors during the builder journey; one 429 analytics page-view was observed under sweep load.

## Evidence

- `pages/summary.csv` — all 44 rows
- `pages/<slug>/report.json` — console/network/DOM/performance
- `pages/<slug>/desktop.png`, `mobile.png` — screenshots
- `journeys/builder-journey.json`, `builder-preview-result.json`, `optimize-action.json`
- `page-inventory.csv` — source routes and metadata

## GitHub issues

| ID | Issue |
|---|---|
| FE-01 | [#2324](https://github.com/sanskarpan/Latexy/issues/2324) |
| FE-02 | [#2325](https://github.com/sanskarpan/Latexy/issues/2325) |
| FE-03 | [#2326](https://github.com/sanskarpan/Latexy/issues/2326) |
| FE-04 | [#2327](https://github.com/sanskarpan/Latexy/issues/2327) |
| FE-05 | [#2328](https://github.com/sanskarpan/Latexy/issues/2328) |
| FE-06 | [#2329](https://github.com/sanskarpan/Latexy/issues/2329) |
| FE-07 | [#2330](https://github.com/sanskarpan/Latexy/issues/2330) |
| FE-08 | [#2331](https://github.com/sanskarpan/Latexy/issues/2331) |
| FE-09 | [#2332](https://github.com/sanskarpan/Latexy/issues/2332) |
| FE-10 | [#2333](https://github.com/sanskarpan/Latexy/issues/2333) |
| FE-11 | [#2334](https://github.com/sanskarpan/Latexy/issues/2334) |
| FE-12 | [#2335](https://github.com/sanskarpan/Latexy/issues/2335) |
| FE-13 | [#2339](https://github.com/sanskarpan/Latexy/issues/2339) |
| FE-14 | [#2342](https://github.com/sanskarpan/Latexy/issues/2342) |
| FE-15 | [#2343](https://github.com/sanskarpan/Latexy/issues/2343) |
| FE-16 | [#2344](https://github.com/sanskarpan/Latexy/issues/2344) |
| FE-17 | [#2345](https://github.com/sanskarpan/Latexy/issues/2345) |
| FE-18 | [#2347](https://github.com/sanskarpan/Latexy/issues/2347) |
| Tracking | [#2336](https://github.com/sanskarpan/Latexy/issues/2336) |

## Visual disposition by page

| Route | Visual analysis |
|---|---|
| `/accessibility` | Long-form accessibility statement; readable hierarchy; no visual defects. |
| `/admin` | Control plane is clean at the top; capability matrix becomes a 21k px wall of toggles. |
| `/admin/tenant` | Clean empty state; no navigation link into the route. |
| `/billing` | Clear plan cards with real prices; coupon/student panels align; no visual defects. |
| `/byok` | Strong hierarchy; provider cards clear; direct-provider copy contradicts the P0. |
| `/dashboard` | Clear KPI cards/charts; 0% empty state reads as failure; metric labels are misleading. |
| `/developer` | Strong typographic API hero; key form clear; consent overlay covers the list. |
| `/faq` | Readable accordion; consistent typography. |
| `/forgot-password` | Centered card; clear instruction; consent overlay covers the lower card. |
| `/` | Clean editorial hero; sample resume card is legible; consent banner overlaps lower proof section. |
| `/login` | Polished centered auth card; consent overlay covers GitHub/passkey options. |
| `/platform` | Editorial feature narrative; clean spacing. |
| `/u/auditfe20261127` | Clean public portfolio with resume/contact blocks; good hierarchy. |
| `/pricing` | Strong hero; plan cards hide all prices; consent overlay covers the cards. |
| `/privacy` | Long legal document; readable measure. |
| `/reset-password` | Centered card; clear input; no visual defects. |
| `/resources` | Editorial resource grid; clean. |
| `/settings` | Clean section cards; dictionary/security/passkeys align; small labels. |
| `/r/xC_40DHizO7gxGhA2fdsAuG62aMPoX1P` | Centered empty/error card; 'Link unavailable' is generic. |
| `/signup` | Centered auth card; consent overlay hides lower options; several unlabeled controls. |
| `/templates` | Library grid is well organized; 61 cards; preview modal loads slowly; consent overlay covers first row. |
| `/tenant-invite` | Redirects to login; cannot assess invite layout without a token. |
| `/terms` | Long legal document; readable measure. |
| `/tracker` | Excellent empty state; board columns clear; add form is dense but readable. |
| `/try` | Editor/preview split is clear; CTAs strong. |
| `/two-factor` | Centered card; verification code input; consent overlay. |
| `/updates` | Editorial changelog; clean. |
| `/verify-email` | Centered card; clear resend CTA. |
| `/workspace` | Onboarding modal covers the library on first visit. |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/batch-tailor` | Form is clear; 1 unlabeled control; no overflow. |
| `/workspace/builder/70e3fa53-0f92-4b64-8a0d-8ce256639f32` | Error card 'Builder resume could not be loaded'; no recovery path. |
| `/workspace/builder/new` | Clean guided-builder start; template cards clear. |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/career` | Career path visualization is clear; 9 buttons. |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/cover-letter` | Two-column generator is clear; 2 unlabeled controls. |
| `/workspace/cover-letters` | Clear library empty state. |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/edit` | PDF preview is good; left editor is blank/read-only for a legacy LaTeX resume; no H1. |
| `/workspace/history` | Run table is readable; filters clear. |
| `/workspace/merge` | Step 1/3 picker is clear. |
| `/workspace/new` | Strong create hub: guided builder, imports, templates. |
| `/workspace/70e3fa53-0f92-4b64-8a0d-8ce256639f32/optimize` | Blank spinner; no skeleton or error. |
| `/workspace/variant/70e3fa53-0f92-4b64-8a0d-8ce256639f32` | Error card 409 with Retry; no explanation how to create a variant. |
| `/workspaces` | Clear team workspace list; consent overlay. |
| `/workspaces/bf531756-d928-4b3d-a79d-b666e7415cf0` | Clean member/share panels; heading is not an H1. |
| `/workspaces/bf531756-d928-4b3d-a79d-b666e7415cf0/recruiter` | Clean empty recruiter dashboard. |


## Additional interaction results (template use, PDF import, share/review, ATS)

- **Templates:** a fresh authenticated free user initially saw **0 TEMPLATES** for ~10s; after the API calls completed it showed 61. Clicking **Use Template** left the card at **"CREATING…"** for >7s. This is FE-15.
- **PDF import:** `/workspace/new` → Import File accepted the PDF and started "Preserving your PDF and extracting its text…"; after 8s the UI was still in the extraction state, but the import does complete: with a non-empty reviewed field and a layout selected, "Create editable resume" succeeded in 12.8s and reached `/workspace/{id}/edit`; the upload POST took ~6s and adapt ~16s. This is a PASS (FE-15 covers the perceived-wait issue).
- **Share/review:** a compiled/accepted resume produced a valid share link, but the public page could not render the PDF because the R2 presigned URL has no `Access-Control-Allow-Origin`; console shows a CORS block and the review surface says "The review document could not be loaded." This is FE-16 / #2344.
- **ATS simulator:** PASS with an accepted artifact: select a check profile (Greenhouse), Run checks enabled, `POST /ats/simulate` 200 in 3.4s, **76/100**, 2 issues, 4 recommendations. The optimize page still took 40.1s to appear (FE-01). See `journeys/ats-simulator.md`.
- **Team invite:** PASS with a P2 state defect: owner invites a member by email; the member can sign in and sees the workspace with **2/5 members**, but the owner's page still shows **1/5** until reload. The submit button is icon-only with no accessible name. This is FE-18 / #2347. See `journeys/team-invite.md`.
- **LinkedIn import:** PASS with a synthetic LinkedIn-style text fixture: conversion produced **2,342 characters**, created a resume, and opened the editor, but the editor is **source-only** ("layout cannot be edited safely through fields yet", FE-02 / #2325) and creation took ~30s (FE-14). See `journeys/linkedin-import.md`.
- **Builder:** create/fill/preview/PDF works; creation can take ~30s and preview ~20–60s (FE-14/FE-01).
- **Cover letter:** generation stayed at "Generating…" for 45s with no logs (FE-13).
- **Tracker:** a fresh account saved an application (`POST /tracker/applications` 201) and the board updated.

Evidence: `journeys/template-use-free.json`, `template-use-worked.png`, `pdf-import-open.png`, `pdf-import-parsed.png`, `pdf-import-completion.json`, `pdf-import-created-final.png`, `share-review-journey.json`, `share-review-45s.png`, `ats-simulator-journey.json`, `ats-simulator-result.png`, `team-invite-journey.json`, `team-workspace-owner.png`, `team-workspace-member-loaded.png`, `linkedin-import-converted.png`, `linkedin-import-editor.png`, `tracker-pro-result.json`.
