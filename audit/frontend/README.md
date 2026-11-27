# Front-end page audit - 2026-11-27

**Goal:** every user-facing page, not just the happy-path landing pages. This is a per-page UX, visual, accessibility, network and performance audit against production `https://latexy.xyz` at backend `ee1a405d`.

## Method

1. Enumerated all **44 App Router pages** from `frontend/src/app/**/page.tsx` (`page-inventory.csv`).
2. Provisioned synthetic users (free, pro, admin, team) and fixtures (resume, share link, portfolio, tracker, workspace) through the real Better Auth and backend APIs.
3. Visited every page at **1440x900** and **390x844** with Playwright, using the right role for each page.
4. Captured per page:
   - HTTP status, redirects, final URL
   - console errors, page errors, failed requests, 4xx/5xx subresources
   - DOM/UX signals: H1, heading order, body text length, link/button/form counts, missing image alt, unlabeled interactive controls, inputs without labels, small text (<12px), horizontal overflow, off-screen elements
   - document/navigation timing, DOM node count, CLS
   - full-page desktop and mobile screenshots
5. Visually inspected screenshots for layout, hierarchy, authentication walls, empty states, copy quality, overlap, and "AI slop".
6. Ran a separate interaction journey for the resume builder (create, edit, compile, preview, download, optimize, ATS, cover letter, tracker) because page-load checks do not prove the product flow.
7. Logged every page-level problem in `defects-frontend.md`; P0/P1 issues are filed in GitHub with acceptance criteria.

## Limitations

- Production data is synthetic; empty-state and populated-state checks use our own fixtures.
- Some pages depend on external OAuth/payment providers and are marked blocked rather than passed.
- Automated contrast and full axe-core checks were not available; missing labels, small text, overflow and screenshot inspection are used instead.
- Mobile screenshots are viewport captures; long pages may need a follow-up scroll pass.
- The audit does not change code; it produces findings and evidence only.

## Artifacts

- `page-inventory.csv` - 44 routes with source file, metadata and auth hints
- `pages/<slug>/report.json` - per-page metrics/console/network
- `pages/<slug>/desktop.png`, `mobile.png` - screenshots
- `pages/summary.json` - all page results
- `defects-frontend.md` - 15 consolidated findings
- `journeys/builder.md` - interaction evidence
- `AUDIT.md` - summary, coverage table, verdict

## Roles used

| Role | Account | Used for |
|---|---|---|
| anonymous | none | public pages, share, portfolio, auth pages |
| free | `audit.fe.free.20261127150805@example.test` | dashboard, workspace, settings, tracker, builder |
| pro | `audit.fe.pro.20261127150805@example.test` | billing, byok, developer, share fixture |
| admin | `audit.fe.admin.20261127150805@example.test` | `/admin`, `/admin/tenant` |
| team | `audit.fe.probe2.1795792012@example.test` | `/workspaces`, workspace detail, recruiter |

All accounts and fixtures are deleted after the audit; tokens are never committed.
