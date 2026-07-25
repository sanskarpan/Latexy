# Mobile / Responsive Audit — Complete Bug List (Jul 2026)

Audited the **live production** frontend (`latexy-frontend-tau.vercel.app`) with Playwright device emulation at **375px (iPhone SE)**, **430px (iPhone 14 Pro Max)**, and **768px (iPad)** — 66+ screen×viewport combos + full-page phone captures + interactive states (admin tabs). Verified as a logged-in admin/test account.

Verdict: the app is **largely responsive** (most screens stack correctly, no overflow), but there is a concrete set of real bugs — plus two **functional** (non-mobile) bugs surfaced during the audit.

## Functional bugs (found during audit — affect desktop too)
- **F1 [HIGH] `/byok` client-side crash** — `TypeError: s.map is not a function`; the entire BYOK page renders "Application error". Page unusable on all viewports.
- **F2 [MED] `/history` route missing (404)** — no `src/app/history/page.tsx`. Verify whether any nav/link points to `/history` and fix the link or add the page.

## Mobile / responsive bugs
- **M1 [HIGH] `/` landing** — hero headline clipped at the right edge (huge non-wrapping text); large empty dark whitespace band before footer.
- **M2 [MED] `/platform`** — excessive empty whitespace band before footer on mobile.
- **M3 [HIGH] `/try` (Resume Studio)** — editor toolbar "Presets" dropdown overlaps the code (line 1); editor status bar labels overlap/cramped (`⌘K PRESETS` over `856 CHARS`); job-URL input clipped next to Import. (The editor↔PDF split *does* stack vertically — OK.)
- **M4 [HIGH] `/workspace`** — resume card action-button row (Fork/Translate/Portfolio/Share/Track/Apply) overflows right (+197px @375, +142px @430); needs flex-wrap; card grid min-width.
- **M5 [HIGH] `/tracker`** — Kanban columns overflow the right edge with no horizontal-scroll affordance / no vertical stacking on mobile.
- **M6 [HIGH] `/admin` → Features × Plans matrix** — renders empty/unusable on mobile (ghost rows, no headers/cells); wide 6-col table has no mobile reflow (needs horizontal-scroll container or stacked per-feature cards).
- **M7 [HIGH] `/admin` → Users & Roles** — same failure mode: empty ghost rows, no user data/role dropdowns on mobile (needs scrollable table or stacked cards).
- **M8 [HIGH] `/workspace/[id]/edit`** — toolbar tab rows overlap/clip ("Refs" cut off); editor↔PDF split does NOT stack (editor collapses to a ~30px sliver). (Different implementation from `/try`.)
- **M9 [HIGH] `/workspace/new`** — runaway page height (~51000px) from oversized empty template-preview thumbnails; cap preview aspect-ratio / lazy-load.
- **M10 [MED] `/developer`** — API code-sample block overflows horizontally (long unwrapped curl/URL strings, no scroll/wrap).
- **M11 [MED] `/settings`** — below-fold horizontal overflow (+94px @375, +39px @430) from an unidentified wide element in a lower card.
- **M12 [MED] `/workspace/[id]/career`** — large blank/loading void under "Past Analyses" on mobile; needs compact empty/loading state.

## Screens verified GOOD on mobile (no fix needed)
`/resources`, `/faq`, `/updates`, `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email`, `/pricing` (stacks), `/billing` (cards stack), `/workspaces` (empty state), `/admin` Feature Flags tab, `/workspace/[id]/batch-tailor`, `/workspace/builder/new`.

## Needs re-capture (audit harness auth/timing artifacts — re-verify authenticated, then fix if broken)
`/dashboard` (showed login), `/workspace/[id]/optimize` (mid-load spinner), `/workspace/[id]/cover-letter` (showed login), `/workspace/builder/[id]` (showed login).

## Fix strategy
Keep the existing design language; make responsive only. Shared-component fixes first (admin table reflow is one component powering M6+M7; the two editor layouts M3/M8). Fix → re-screenshot at 375/430/768 → verify no overflow and usable, before moving on.
