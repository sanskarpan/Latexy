# Front-end defects - 2026-11-27

Severity follows the audit scale. Every finding is from live production `https://latexy.xyz` and the screenshots/reports in `pages/` and `journeys/`.

## FE-01 - P1 - Optimize page can sit on a blank "Checking feature availability" spinner for 25s+ with no error

**Surface:** `/workspace/{resumeId}/optimize`.
**Cohorts:** free, legacy LaTeX resume and builder resume.

**Observed:** the page renders only a spinner and "Checking feature availability"; after 25s it either loads (builder resume) or remains blank (legacy resume). No console error, no HTTP error, no skeleton, no timeout. The earlier builder journey loaded after ~8s; a later run took 25s.

**Evidence:** `pages/workspace-optimize/report.json`, `journeys/optimize-action.json`, `journeys/optimize-loaded.png`, `journeys/optimize-action.png`.

**Impact:** a core paid AI flow is effectively unavailable or appears broken for users on slow loads and for imported LaTeX resumes.

**Proposed fix:** cache the entitlement/tenant resolution; render the editor shell immediately; add a skeleton and an 8s timeout with Retry/Back; do not gate the whole page on a feature check.

**Acceptance:** page shell renders <2s warm / <5s cold; a timeout error appears by 8s; legacy resume shows an actionable message or source editor; test both resume types.

## FE-02 - P1 - Imported/legacy LaTeX resumes have no coherent edit path

**Surface:** `/workspace/{id}/edit`, `/workspace/builder/{id}`, `/workspace/variant/{id}`.
**Observed:**
- Edit page is read-only: "This document uses a layout that cannot be edited safely through fields yet"; no clear CTA to the source editor.
- Builder route returns 404 `/resumes/{id}/builder/v1` and the UI says "Builder resume could not be loaded".
- Variant route returns 409 "This is not a source-linked builder variant".
- Optimize page spinner (FE-01).

**Evidence:** `pages/workspace-edit/desktop-clean.png`, `pages/workspace-builder/report.json`, `pages/workspace-variant/desktop-clean.png`.

**Impact:** a user who imports LaTeX/PDF or creates through the public API is routed into dead ends; only builder-created resumes get the full product.

**Proposed fix:** detect the resume kind at the route boundary; route legacy resumes to the source editor with a clear banner; hide/disable Builder and Variant entry points; make the error state actionable.

**Acceptance:** every resume kind has one working edit path; no 404/409 from a navigation link; legacy edit shows source or a clear "convert to builder" flow; regression test for both kinds.

## FE-03 - P2 - Consent banner overlays critical UI on first visit

**Surface:** all pages, especially `/login`, `/signup`, `/pricing`, `/admin`, `/templates`.
**Observed:** the fixed consent card covers the lower sign-in options (GitHub/passkey), pricing cards, admin capability rows and template previews. It is present on every first visit until a choice is made.

**Evidence:** `pages/home/desktop-top.png`, `pages/login/desktop-top.png`, `pages/pricing/desktop-top.png`, `pages/admin/desktop.png`.

**Impact:** hides conversion actions and admin controls; poor first impression; can block a user who does not notice the banner.

**Proposed fix:** use a bottom sheet that does not cover interactive content, or reserve space; allow dismissal before paint; never cover auth buttons.

**Acceptance:** no interactive control is obscured at 1440x900 or 390x844; banner is dismissible; auth form fully visible.

## FE-04 - P2 - Admin capability matrix is a 21,101px page with 930 toggles

**Surface:** `/admin` → Features × Plans & Roles.
**Observed:** 165 capabilities × 6 columns render in one page: 21,101px tall, 6,135 DOM nodes, 930 buttons, 469 small-text elements. Search filters rows but there is no pagination/virtualization/sticky header.

**Evidence:** `pages/admin/desktop-clean.png`, `pages/admin/report.json`.

**Impact:** slow first paint, hard to scan, easy to toggle the wrong row; operators cannot work efficiently.

**Proposed fix:** virtualize/paginate the matrix; sticky column header; search/filter summary; bulk select; confirm before global toggles.

**Acceptance:** initial admin payload <500 DOM rows; matrix interactive <2s; no more than ~100 rows in DOM at once; sticky header and filters work.

## FE-05 - P2 - Pricing page hides every price

**Surface:** `/pricing`.
**Observed:** the page says "Sign in to see current prices, plan limits, and checkout on your billing page" and shows no amounts. `/billing` shows ₹299 Basic / ₹599 Pro.

**Evidence:** `pages/pricing/desktop-top.png`, `pages/billing/desktop-clean.png`.

**Impact:** a pricing page without prices is a conversion and trust problem; users cannot compare plans without signing in.

**Proposed fix:** show the monthly/annual prices (or a clear "from ₹X" with regional note) on the marketing page; keep checkout on billing.

**Acceptance:** every plan card shows its price/interval or a clear regional reason; prices match billing; no sign-in required to see them.

## FE-06 - P2 - Dashboard metrics mislabel compile latency and success

**Surface:** `/dashboard`.
**Observed:** "Avg Compile Latency 3.5s" while measured submit-to-terminal is 20.7s p50; "Success Rate 100%" while optimization jobs failed. The card computes a different denominator/window than the user expects.

**Evidence:** `pages/dashboard/desktop-clean.png`, `audit/latency/load-test.md`.

**Impact:** users are told compiles are ~6x faster than they are; reliability looks perfect despite failures.

**Proposed fix:** use server submit-to-terminal latency (or label "pdflatex time"), exclude preview/cache hits, and count failed/cancelled jobs in the success rate.

**Acceptance:** dashboard value matches backend p50 within 10%; failed jobs reduce success rate; tooltip defines the metric.

## FE-07 - P2 - Editor/auth controls lack accessible names

**Surface:** builder Profile & Summary; `/login`, `/signup`, `/forgot-password`, `/dashboard`, `/settings`, `/admin`, cover-letter, batch-tailor, merge, workspaces-detail, two-factor.
**Observed:** builder has 10 visible text inputs with no `aria-label`, `placeholder`, `id`/`<label for>`; login 2 unlabeled interactive controls; signup 4; other pages 1–2 each.

**Evidence:** `journeys/builder-profile-controls.json`, `pages/summary.csv`.

**Impact:** screen-reader users cannot identify fields/buttons; WCAG 2.1 AA failure.

**Proposed fix:** associate labels/`aria-label` with every input and icon button; add an axe-core regression.

**Acceptance:** zero unlabeled interactive controls on audited pages; axe-core critical/serious violations zero; test with keyboard/screen reader.

## FE-08 - P2 - Share page shows a generic "Link unavailable" after a successful compile

**Surface:** `/r/{token}`.
**Observed:** after a successful compile, the share endpoint returns 404 "No compiled PDF available yet" and the page shows "Link unavailable" with no next step. The share token exists; the resume's latest artifact is null until accepted.

**Evidence:** `pages/share/report.json`, live backend response `97d1cc8…`, `pages/share/desktop-top.png`.

**Impact:** a user cannot share a compiled resume; the error is indistinguishable from a revoked/expired link.

**Proposed fix:** use the latest compilation PDF or explain "This resume has no accepted PDF yet"; add a CTA to compile/accept; distinguish invalid vs no-artifact.

**Acceptance:** compile → share returns a PDF; no-artifact state explains what to do; revoked link remains a distinct 404.

## FE-09 - P3 - Missing H1 and small-text/heading hierarchy issues

**Surface:** `/workspace/{id}/edit`, `/workspace/{id}/optimize`, `/workspaces/{id}`; home/templates/dashboard/admin/settings.
**Observed:** three pages have no H1; 469 small-text elements on admin, 63 on templates, 45 on dashboard, 43 on home. Visual headings are divs.

**Evidence:** `pages/summary.csv`, screenshots.

**Impact:** weaker accessibility/SEO and harder scanning; tiny labels may be unreadable.

**Proposed fix:** one H1 per page; semantic headings; raise body/label minimum to 12px (or 14px for secondary text).

**Acceptance:** exactly one H1 on every page; no visible text <12px except legal microcopy; heading order valid.

## FE-10 - P3 - Onboarding modal blocks the resume library for an existing user

**Surface:** `/workspace`.
**Observed:** a 4-step "Welcome to Latexy" modal covers the library even though the account already has a resume. Skip exists, but the first screen is blocked.

**Evidence:** `pages/workspace/desktop-clean.png`.

**Impact:** returning users must dismiss onboarding again; hides the primary workspace action.

**Proposed fix:** show only for new accounts with no resumes; persist dismissal; make it a side panel.

**Acceptance:** existing users see the library immediately; onboarding only for first-run; dismissal persists.

## FE-11 - P3 - Builder PDF contact URLs break mid-token

**Surface:** builder PDF preview/download.
**Observed:** `github.com/audit` wraps as `github.com/au-` / `dit` in the generated PDF; long contact lines break without a clean separator.

**Evidence:** `journeys/builder-preview-after.png`.

**Impact:** unprofessional contact block; copy/paste may break.

**Proposed fix:** use a ragged-right contact block or `\url` with hyphenation disabled; test long URLs.

**Acceptance:** a 40-character URL renders on one line or breaks only at a safe separator.

## FE-12 - P3 - Tracker/cover-letter forms lack labels and slow save feedback

**Surface:** `/tracker` Add Application; `/workspace/{id}/cover-letter`.
**Observed:** tracker form inputs have placeholders but no associated labels; after clicking Add Application the button shows "Adding…" for >2.5s. Cover letter has 2 unlabeled controls.
**Evidence:** `journeys/explore-optimize-tracker.json`, `pages/workspace-cover-letter/report.json`.

**Impact:** accessibility and perceived reliability.

**Proposed fix:** associate labels; show progress/disabled state; return errors inline.

**Acceptance:** all inputs labeled; save <1s or a progress state; errors visible.


## FE-13 - P2 - Cover-letter generation sits at "Generating…" with no logs or error

**Surface:** `/workspace/{resumeId}/cover-letter`.
**Observed:** with a 159-character job description, clicking "Generate Cover Letter" leaves the button at "Generating…" for 45s, the live log says "No log output yet", and the document stays empty. No console or HTTP error appears.

**Evidence:** `journeys/cover-template-result.json`, `journeys/cover-letter-after-generate.png`.

**Impact:** a core AI writing flow appears hung; the user has no progress, error, or retry guidance.

**Proposed fix:** surface the job id/state and provider error; show streamed log lines; add a timeout and Retry; do not leave the button in an indeterminate state.

**Acceptance:** success returns a document within the target; failure shows a typed error and Retry within 30s; the live log shows progress.


## FE-14 - P2 - Guided builder creation can sit at "Creating your résumé…" for ~30s

**Surface:** `/workspace/builder/new`.
**Observed:** after entering a title and clicking **Start my résumé**, the button stayed at "Creating your résumé…" for ~30s; one run was still on `/workspace/builder/new` after the wait, another navigated at ~30s. `POST /resumes/builder/v1` returned 201 and the editor loaded. No error or progress beyond the button label.

**Evidence:** `journeys/builder-create-net.json`, `journeys/builder-create-stuck.png`.

**Impact:** users cannot tell whether creation is working; a 30s wait is abandonment territory.

**Proposed fix:** prefetch capabilities/templates, show a step/progress state, add a timeout with Retry, and prevent duplicate submits.

**Acceptance:** creation navigates within 3s warm / 8s cold, or shows a progress step; timeout error by 10s; no duplicate resume created.


## FE-15 - P2 - Templates page shows "0 templates" while loading; template use stays at "CREATING…"

**Surface:** `/templates`, `/workspace/new` → Use Template / Import File.
**Observed:** a fresh authenticated user sees **0 TEMPLATES** and no skeleton for ~10s; after the API calls complete it shows 61. Clicking **Use Template** leaves the card at **"CREATING…"** for >7s, and PDF import stays at "Preserving your PDF and extracting its text…" for >8s. No error is shown.

**Evidence:** `journeys/template-use-free.json`, `journeys/template-use-worked.png`, `journeys/pdf-import-parsed.png`.

**Impact:** a new user's first impression is an empty library or a frozen action; the product looks broken while it is working.

**Proposed fix:** show a skeleton/“Loading templates…” instead of 0; prefetch templates/categories during auth; show a progress step for template use and import; add a timeout.

**Acceptance:** templates skeleton or count appears immediately; no "0 templates" flash; template use/import shows step progress and reaches the destination or an error within 15s.
