# In-app browser review - 2026-11-27

This pass used the T3 Code in-app browser (same Chromium tabs the person sees), not only the Playwright sweep.

## Environment

- Logged-in default profile at **1279x799**; anonymous checks used an incognito tab.
- The person's active tab at **741x1362** was used for the annotation check.
- Real account data ("Stem Grad"); all actions were read-only. No compile, save, invite, purchase or admin mutation was triggered from this pass.
- Console: no errors on the reviewed pages. Only the usual Next.js font-preload warnings.

## The annotation (workspace header)

**Yes - the selected element is the sticky workspace header container.** At 741px:

- Logo on the left; high-contrast, theme, language and **Menu** on the right.
- Desktop nav collapses to Menu; it does not wrap onto a second row or overlap the page.
- Header height 64px; no horizontal overflow.
- At 1279px the full nav (Dashboard, Workspace, Tracker, Templates, Studio) and the account chip return.

## Pages reviewed

| Route | Viewport | Result | New/confirmed finding |
|---|---|---|---|
| `/workspace` | 741 / 1279 | Header and library are clean; 1 resume card; no overflow | Annotation confirmed |
| `/workspace/new` | 1279 | Create Resume hub, 1 H1, 22 controls, 9 buttons | Clean; consent does not cover the hub (logged in) |
| `/templates` | 1279 | **"0 TEMPLATES"** at 3s, 61 at ~12s, no skeleton | FE-15 / #2343 confirmed live |
| `/dashboard` | 1279 | Five KPI cards are **empty boxes** at 3.5s, populated at ~6s; loaded state correct | New P3 grouped in #2345 |
| `/billing` | 1279 | Bare **"Loading plans..."** + **"Loading subscription state..."** at 3s; subscription still bare at 10s; loaded ~12s; 5 subscription requests | New P3 grouped in #2345 |
| `/settings` | 1279 | "Loading dictionary..." at 3s; preferences resolve ~7s; 1 unlabeled button; 19 small-text nodes; 4,156px page | FE-07 / #2330; loading grouped in #2345 |
| `/tracker` | 1279 | Clean empty board, 1 H1, no console errors | Pass |
| `/workspace/history` | 1279 | Clean empty state, 1 H1 | Pass |
| `/workspace/{id}/optimize` | 1279 | **Blank dark page + spinner at ~25-30s**; then "Targeted Optimization" (38 buttons), no error | FE-01 / #2324 confirmed live |
| `/workspace/{id}/cover-letter` | 1279 | Clean two-column generator, 1 H1, **2 unlabeled controls** | FE-12 / #2334 |
| `/workspace/variant/{id}` | 1279 | Still "Loading" at 4.5s | Existing route-kind issue FE-02 |
| `/workspace/merge` | 1279 | Still "Loading" at 4.5s | Loading-state issue (not yet isolated) |
| `/workspace/builder/new` | 1279 | "Loading builder templates..." at 4.5s | FE-14 / #2342 class |
| `/workspace/cover-letters` | 1279 | Clean empty library | Pass |
| `/pricing` (anonymous) | 1279 | **No prices**; "Sign in to see current prices"; consent panel **covers plan cards and CTAs** | FE-05 #2328 + FE-03 #2326 confirmed visually |
| `/admin` | 1279 | 1 H1; **21,105px**, **925 visible buttons**, 172 rows; top of page is clean | FE-04 / #2327 confirmed live |

Screenshots: `browser-review/` (workspace/new, templates-0, billing-loading, settings-loading, admin-top, pricing-anon, optimize-blank, dashboard-loading, dashboard-loaded). Logged-in captures are cropped 65px from the top to remove the account chip; pricing is anonymous.

## Verdict on this pass

The page shells are visually strong and consistent; the problems are **time-to-content and missing loading states**, not layout collapse. The live browser confirmed the existing P1/P2 findings and added one revenue-page performance/polish issue: billing refetches plans three times and shows bare loading text for ~12s, while the dashboard's KPI cards render as empty boxes first.

## Issues

- FE-01 #2324, FE-03 #2326, FE-04 #2327, FE-05 #2328, FE-07 #2330, FE-12 #2334, FE-14 #2342, FE-15 #2343
- FE-16 #2344 (share PDF CORS)
- FE-17 #2345 (bare loading shells / billing refetch)
