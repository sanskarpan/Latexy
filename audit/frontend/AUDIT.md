# Front-end page audit - results

**Verdict:** all 44 routes load in production, but the page-by-page audit found a blocked core flow (Optimize), a broken path for imported/legacy LaTeX resumes, a 21,101px admin capability page, consent overlays on critical forms, missing accessible names, and several misleading empty states/metrics. Cover-letter generation also stays at 'Generating…' for 45s with no logs or error (FE-13).

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
| Tracking | [#2336](https://github.com/sanskarpan/Latexy/issues/2336) |
