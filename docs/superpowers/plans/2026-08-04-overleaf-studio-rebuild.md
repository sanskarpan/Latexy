# Overleaf-Inspired Résumé Studio — Rebuild Plan

**Goal:** Rebuild the real `/try` page from a two-column card grid into a professional, Overleaf-inspired 3-pane LaTeX IDE (rail · editor · PDF), preserving **every** existing feature and wiring, with Latexy's AI/ATS/Import layered onto a left tool-rail.

**Approved via:** interactive mockup at `/studio-preview` → user picked direction **A**.

**Constraint:** LOCAL ONLY. No commits/pushes/merges until the user explicitly approves. 493 frontend tests must stay green; `tsc` clean.

---

## Architecture

- Keep **all** state + handlers in `app/try/page.tsx` (the container). Only the presentation changes.
- Replace the `content-shell` (max-w-7xl, scrolling) with a **full-bleed, full-height IDE frame** that fills the viewport below the global header.
- Keep `GlobalHeader` (nav/login/upgrade/trial). **Hide `MarketingFooter` on `/try`** (an IDE shouldn't have a marketing footer under it) via a pathname check in `layout.tsx`.
- Aesthetic already resolves to `compiler` for `/try` (confirmed in `THEME_BOOTSTRAP`). Editor pane stays a fixed dark IDE surface (`#0d1117`); chrome uses tokens (theme-aware light/dark).

## Layout regions → existing features (nothing dropped)

| Region | Wires to (existing) |
|---|---|
| **Top project bar** | title · **Recompile** = `runCompile('compile')` + Auto toggle (`toggleAutoCompile`) · ATS chip (`quickATSScore`) · **PDF** = `ExportDropdown`/`handleDownload` · login/trial state |
| **Icon rail** | Files · AI Optimize · ATS · Import · Templates (switches left panel) |
| **Files panel** | `resume.tex` entry + Reset / Clear / Import-file (`MultiFormatUpload` modal) — minimal for trial |
| **AI Optimize panel** | job description textarea · URL scrape (`handleScrapeUrl` + `scrapedMeta`) · **Optimize for role** = `runCompile('combined')` · trim-to-1-page (`handleTrimToOnePage`) · `stream.changesMade` list |
| **ATS panel** | `quickATSScore` + `stream.atsDetails.category_scores` + **Deep scan** → `DeepAnalysisPanel` (`handleRunDeepAnalysis`) |
| **Import panel** | `ImportProjectsModal` (GitHub / URL / LinkedIn → `onInsert(latex)`) + file upload |
| **Editor pane** | `LaTeXEditor` (ref API preserved) + `ErrorExplainerPanel` overlay + Source/RichText affordance |
| **PDF pane** | `PDFPreview` + zoom/page readout + progress strip + **collapsible logs** (`LogViewer`) + error/warning + page-overflow & timeout banners |
| **Bottom status bar** | status · stage · page count · compiler · ATS |

## Responsive

- `lg+`: full 3-pane IDE, draggable editor/PDF splitter, collapsible rail panel & PDF pane.
- `< lg`: single-pane with a segmented switch (**Editor / PDF / Tools**); rail becomes a top icon strip. No horizontal scroll.

## Non-goals (this pass)

- No new per-change accept/reject in **anonymous** `/try` (that flow lives in the authenticated workspace optimize page; the mockup's accept/reject cards illustrate the pattern — here we keep the existing whole-doc optimize + `changesMade` list). Wiring true `ChangesPanel` into `/try` is a follow-up.
- No SyncTeX click-to-jump yet (flagged as a future build item).

## Verification

1. `npx tsc --noEmit` clean.
2. `npx vitest run` → 493 passing (no behavior removed).
3. Playwright vision review: light + dark, each rail panel, mobile width — matches mockup, every control present.
4. Manual trace: every handler from the old page is reachable from a control in the new layout.

## Tasks

1. Layout: hide `MarketingFooter` on `/try`; make the Studio fill viewport height.
2. Build the IDE frame in `page.tsx` (top bar, rail, splitter, panes, status bar) — reusing existing components, keeping all state/handlers.
3. Wire each rail panel to its existing feature (table above).
4. Responsive single-pane mode for `< lg`.
5. Verify (tsc + tests + vision), iterate to match mockup.
