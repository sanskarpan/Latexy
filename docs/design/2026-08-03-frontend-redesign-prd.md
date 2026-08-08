# PRD: Latexy Frontend Redesign — "Typeset × Compiler" Hybrid Design System

- **Status:** Final v2 (post-scrutiny — an adversarial architecture review was applied; corrections are marked ⟐)
- **Date:** 2026-08-03
- **Owner:** TBD
- **Scope:** Full frontend redesign — every marketing, auth, app, and admin surface — plus a from-scratch design-token system, real webfont loading, a shared primitive library, and a responsive/performance baseline.
- **Non-negotiable constraint:** **Zero functional regressions.** This is a visual/structural refactor. Every existing feature (compile, optimize, per-change review, imports, BYOK, billing, collaboration, ATS, editor, etc.) must keep working exactly as it does today. Redesign the surface, never the behavior.

---

## 1. Summary

Latexy works but *looks* generic — "okayish, with AI-slop hints." We will replace the ad-hoc styling with a single **three-layer design-token system** driving two aesthetics that share one spine:

- **"Typeset"** — an editorial, print-specimen identity (serif display + mono, sharp corners, document rhythm) for **marketing/public** surfaces. It is deliberately *not* the saturated dark-dev-tool look, which is now a default rather than a differentiator.
- **"Compiler"** — a refined dark-capable dev-tool identity (mono/grotesque, soft corners, terminal motifs) for the **authenticated app** where developers actually work.

Both aesthetics support **light and dark** modes (four total variants), tuned by hand rather than naively inverted. The redesign also fixes the root causes uncovered in the audit (§3): webfonts that never load, a contradictory color system, and a ghost component library.

## 2. Goals / Non-goals

**Goals**
1. A distinctive, cohesive identity that reads as intentional design, not template output.
2. One token source of truth (color, type, spacing, radius, motion) — no hardcoded hex, no per-feature rainbow.
3. Real, properly-loaded typography (fixes the "Inter configured but never delivered" bug).
4. A genuinely-used primitive library (Button/Card/Badge/Panel/Input/…) that replaces the 104 hand-rolled buttons.
5. Excellent **responsive + cross-device** behavior and loading performance (a first-class requirement — see §9).
6. A memorable hero grounded in the product's own world (live `.tex → .pdf`), plus problem-oriented page structure.
7. Full-surface coverage: marketing, auth, app shell, and the heavy editor/panel/modal ecosystem.

**Non-goals**
- No changes to backend APIs, data models, routing paths, or feature behavior.
- Not adopting a heavyweight component framework (MUI/Chakra). We stay on Tailwind + a thin token-bound primitive layer.
- Not a copy rewrite beyond replacing salesy/placeholder text and emoji-as-icons.
- Not removing dark mode from marketing or light mode from the app — all four variants ship.

## 3. Current-state diagnosis (from the codebase audit)

Concrete problems the redesign must resolve (file evidence in the audit; summarized here):

1. **Fonts never load.** `tailwind.config.ts` references `Inter`/`JetBrains Mono`, but there is **no `next/font`, no `@font-face`, and zero font files** — the site renders in the OS default. *This is the single biggest "generic" tell.*
2. **No real color source of truth.** `globals.css` defines CSS-var tokens (`--primary` orange), but app code ignores them and hardcodes literals. Grep: `zinc-*` dominates; accent is `orange-300`; but the app is a rainbow — `bg-violet-500 ×124`, `bg-emerald-500 ×86`, plus amber/sky/blue and hardcoded hex (`#0d0d0d ×25`, purple `#a855f7/#8b5cf6/#7c3aed`). A **blue** `primary` ramp and **purple** gradient presets baked into the Tailwind config contradict the orange brand.
3. **Ghost design system.** shadcn-style `ui/{button,card,badge,input}` exist but `ui/button` is imported by **2 files while 104 files hand-roll `<button className=…>`**. Cards/badges/panels each have 2–3 incompatible definitions. Radius is chaotic (`rounded-2xl ×42`, one-off `rounded-[44px]/[34px]`, `--radius:0.95rem`).
4. **Glass-everywhere + template layout.** `.surface-panel`/`.surface-card` (`backdrop-blur-xl`) across 30 files; a `@react-three/fiber` icosahedron 3D hero; the textbook *centered hero → 3 feature cards → 4 steps → glowing CTA* funnel.
5. **Emoji-as-icons** in 10 files despite a full `lucide-react` set (e.g. `try/page.tsx:469` `📍`).
6. **Boastful placeholder stats** on the landing page (`"8.4s median compile"`, `"+23% score gain"`, `"50k+ generated monthly"`).
7. **Duplicate chrome:** both `GlobalHeader.tsx` (active) and a legacy `Header.tsx`.

## 4. Design direction — the hybrid

### 4.1 Routing of aesthetics
- **Typeset** (editorial): `/`, `/platform`, `/templates`, `/resources`, `/faq`, `/updates`, `/pricing` (`billing` re-export), `/developer`, `/u/[username]`, `/r/[token]`, and all auth pages (`/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email`).
- **Compiler** (dev-tool): everything authenticated — `/dashboard`, `/billing`, `/settings`, `/byok`, `/tracker`, `/workspace/**` (lists, editor, optimize, cover-letter, career, batch-tailor, builder), `/workspaces/**`, `/admin/**`.
- **Edge case — `/try` (public Studio):** it is a public entry that *is* the app editor. Decision: render `/try` in **Compiler** (it is the product surface), but keep the surrounding public header in a Typeset-neutral bridge state. (Flag for scrutiny.)

### 4.2 The three-layer token architecture
1. **Spine (shared, aesthetic- and theme-agnostic):** spacing scale (8pt), modular type scale, motion tokens (durations/easings), semantic roles (`ok`/`warn`/`err`/`info`), z-index scale, breakpoints, container widths.
2. **Aesthetic layer** (`data-aesthetic="typeset|compiler"`): swaps **fonts, radius, label letter-spacing, shadow character, and grid motif** only.
3. **Theme layer** (`data-mode="light|dark"`): swaps **colors** only — four hand-tuned sets.

Components read *only* from semantic tokens (`--bg`, `--surface`, `--fg`, `--accent`, `--ok`/`--warn`/`--err`), never from raw values, so all four combinations resolve from one component definition. ⟐ **Semantic roles are `ok`/`warn`/`err` only** — there is no `--info` role (an "info" hue would collide with the Typeset accent, which is itself blue); "informational" emphasis reuses `--accent` or `--fg-2` contextually.

## 5. Token specification

### 5.1 Spine
- **Spacing (8pt base, rem):** `4, 8, 12, 16, 24, 32, 48, 64, 96` → `--space-{1..9}`.
- **Radius (scale, values set per aesthetic):** `sm, md, lg, pill`. Typeset = `2 / 3 / 4 / 999px`; Compiler = `6 / 8 / 12 / 999px`.
- **Type scale (modular, minor-third ≈ 1.2), fluid via `clamp()`:** caption `.75rem`, body `1rem/1.0625rem`, lead `1.125rem`, h3 `1.25–1.5rem`, h2 `1.5–2.25rem`, h1/display `clamp(2.4rem, 6vw, 5rem)` (capped). Reading measure `≤ 66ch`.
- **Motion:** `--dur-1 .15s`, `--dur-2 .3s`, `--dur-3 .5s`; `--ease-out cubic-bezier(.2,.7,.2,1)`, `--ease-in-out`. All motion gated by `prefers-reduced-motion`.
- **Z-index scale:** `base 0, raised 10, sticky 20, dropdown 30, modal 40, toast 50, dock 60`.

### 5.2 Fonts (fixes the load bug)
Loaded via **`next/font`** (self-hosted, subset, `display: swap`, preloaded for the above-the-fold face):
- **Shared mono:** **JetBrains Mono** (UI labels, code, metadata) — used by *both* aesthetics.
- **Typeset display + body:** **Fraunces** (variable; use optical sizing — large `opsz` for display, text `opsz` for body).
- **Compiler body:** a clean grotesque — default **Geist Sans** (OSS, dev-native); Compiler display uses JetBrains Mono. *(Font choice is an open decision — §13.)*
- **Fallback stacks** are declared for each role to avoid layout shift; `size-adjust`/`ascent-override` tuned to minimize CLS between fallback and webfont.

### 5.3 Color — the four variants
Semantic role → hex, per `[data-aesthetic][data-mode]`:

| Role | Typeset·Light | Typeset·Dark | Compiler·Dark | Compiler·Light |
|---|---|---|---|---|
| `--bg` | `#FBFAF6` | `#141310` | `#0B0B0D` | `#F7F6F3` |
| `--surface` | `#FFFFFF` | `#1B1A14` | `#111114` | `#FFFFFF` |
| `--surface-2` | `#F3F0E8` | `#211F18` | `#17171B` | `#EFEDE7` |
| `--line` | `#D8D2C4` | `#302C24` | `#26262C` | `#E1DED7` |
| `--line-2` | `#C6BFAE` | `#3E392E` | `#33333B` | `#D2CFC7` |
| `--fg` | `#1B1815` | `#E9E4D7` | `#ECEAE4` | `#17171A` |
| `--fg-2` | `#4A443C` | `#ABA595` | `#A7A49C` | `#55534D` |
| `--fg-3` | `#8C857A` | `#746E60` | `#6E6B64` | `#8A877F` |
| `--accent` | `#1C3F6E` | `#8AB0DE` | `#F0A250` | `#C2691F` |
| `--accent-fg` | `#FBFAF6` | `#101319` | `#1C1200` | `#FFFFFF` |
| `--ok` | `#2E7D57` | `#6FCB9A` | `#5BD6A4` | `#1F9D63` |
| `--warn` | `#9A7B3F` | `#D8B36A` | `#E7C46A` | `#B07A1E` |
| `--err` | `#B23A2E` | `#E0796B` | `#E5715C` | `#C4472F` |

**Rules:** exactly **one accent** per variant; `ok/warn/err` are *semantic only* and never used decoratively or as the accent. Neutrals carry a slight warm hue bias (chosen, not defaulted). Every foreground/background pairing must meet **WCAG AA** (4.5:1 body text, 3:1 large text / UI) — verified per variant (§9.6). The two "risky" variants (Typeset-dark warmth, Compiler-light amber-on-white) are the ones to contrast-check hardest.

## 6. Theming architecture (implementation) ⟐ (rewritten after scrutiny)

- Tokens live in `globals.css` (or `tokens.css`) as CSS custom properties, scoped by `:root[data-aesthetic="…"][data-mode="…"]`.
- **`tailwind.config` consumes the tokens** via `theme.extend.colors: { bg: 'var(--bg)', surface: 'var(--surface)', fg: 'var(--fg)', accent: 'var(--accent)', ok/warn/err, line/line-2 }` so `bg-surface text-fg border-line` work everywhere. ⟐ **This is additive: the stock Tailwind palette (`zinc-*`, `white`, `black`, etc.) is retained the whole time** — hundreds of `text-zinc-*`/`bg-zinc-*` uses keep working and are removed only per-surface as each file is converted (Phases 4–5). Nothing is globally deleted out from under un-migrated files.
- ⟐ **`darkMode` must change.** It is currently `darkMode: ["class"]` (`tailwind.config.ts:4`), which expects an ancestor `.dark` class we do not use. Set it to `darkMode: ['selector', '[data-mode="dark"]']` so any `dark:` utility resolves under our attribute. (Audit: there are **zero real `dark:` utilities today** — the 2 grep hits are object literals — so this is latent, but leaving `["class"]` would make future `dark:` silently no-op.)
- ⟐ **Deleting the legacy color presets is sequenced, not upfront.** The blue `primary` numeric ramp **is used in 29 places** (`LoadingSpinner.tsx:15`, `ui/button.tsx:21` `gradient` variant, `onboarding/OnboardingFlow.tsx`, `help/HelpCenter.tsx`, legacy `Header.tsx:16`), as are `secondary-*` and `blue-50`. Tailwind **silently drops unknown classes** (no build error), so deletion must happen **only after** those consumers are migrated, and a **CI grep guard for orphaned `primary-\d`/`secondary-\d`** is mandatory. The `gradient-primary`/`gradient-secondary`/`gradient-dark` presets (0 usages) and `shadow-glow` (1 usage, `ui/button.tsx:22`) can be removed with their few/no consumers.
- **Aesthetic is set by route group.** Restructure `app/` into `(marketing)` and `(app)` route **groups** (no URL changes); each group's `layout.tsx` stamps `data-aesthetic`. ⟐ **Migration hazards (must honor):**
  1. **Providers stay in the ROOT layout.** `app/layout.tsx:31–68` nests `FeatureFlagsProvider > EntitlementsProvider > NotificationProvider > WebSocketProvider` + `AuthSync`, `TenantThemeSync`, `WebVitalsReporter`, `Toaster`. Only **chrome** (header/footer) moves into group layouts; providers are **never duplicated** (a second `WebSocketProvider` would break the WS singleton).
  2. **The header is auth-aware, not route-aware today.** `GlobalHeader.tsx:70` picks `guestNav` vs `appNav` by **session**, and hides itself on fullscreen editor routes (`fullscreenPatterns`, `:59`). Splitting into a marketing header (Typeset) and an app header (Compiler) changes today's behavior where a logged-in user on `/` sees app nav — this is an intended change but must be called out against "zero functional regressions": the **marketing header stays auth-aware for its CTAs** (Sign in vs Dashboard) while adopting the Typeset skin; only the *aesthetic* is route-scoped, not the auth logic.
  3. **`/pricing` is a literal re-export of `/billing`** (`app/pricing/page.tsx` = `import BillingPage from '@/app/billing/page'; export default BillingPage`). Resolution: **give `/pricing` its own Typeset marketing component** (public pricing cards) rather than re-exporting the authenticated billing screen; `/billing` (Compiler) stays the in-app subscription manager. This also avoids the broken import path if `billing/page` moves into the `(app)` group.
- ⟐ **Existing tenant theming must coexist.** `TenantThemeSync` (root layout `:44`) → `applyTenantTheme()` (`lib/tenant-theme.ts:23`) sets `--tenant-primary`/`--tenant-primary-rgb` on `documentElement` (the same node we stamp `data-aesthetic`/`data-mode` on) and overrides `document.title` (`:38`). Today `--tenant-primary` has **0 consumers** (white-label accent is a no-op). Plan: (a) when a tenant accent exists, map it onto `--accent` at a specificity that overrides `:root[data-aesthetic][data-mode]` (e.g. an inline style on `:root` set by `TenantThemeSync`, which wins over stylesheet rules); (b) fix the `document.title` override to not fight per-page Next `metadata` (scope it to tenant-branded routes only). No `next-themes` dependency exists — the new `ThemeProvider` is net-new, no library collision.
- **Mode (light/dark)** = user preference resolved with no flash:
  - Default to `prefers-color-scheme`, overridable by a persisted toggle. ⟐ Persistence uses a **new, dedicated theme cookie** (e.g. `latexy-theme`) — **distinct from the Better Auth `better-auth.session_token` cookie**; `src/middleware.ts` (which exists) may set/normalize it.
  - ⟐ App Router renders no literal `<head>`, so the **blocking inline script** is injected as a `<script dangerouslySetInnerHTML>` child at the top of the root `<body>`, setting `data-mode`/`data-aesthetic` before paint. For a true SSR match, the **RSC root layout reads the theme cookie via `cookies()`** and stamps `data-mode` server-side. ⟐ `<html lang="en" suppressHydrationWarning>` **already exists** (`layout.tsx:37`) — reuse it; it is not new work.
- A `ThemeProvider` exposes `mode`, `setMode`, and resolves aesthetic from the route group; the marketing header gets a sun/moon toggle, the app gets one in the app header + settings.
- ⟐ **`themeColor` becomes mode-aware.** `layout.tsx:28` hardcodes `viewport.themeColor = '#ff845d'`; with four variants it should switch by mode (light/dark) via the `media`-keyed `themeColor` array so browser chrome matches.

## 7. Component / primitive system

Build a real, token-bound library in `components/ui/` and make it the enforced source of truth. Minimum set:

- **Primitives:** `Button` (variants: primary/ghost/subtle/danger; sizes sm/md/lg; loading state), `IconButton`, `Card`, `Panel` (app surface w/ header slot), `Badge` (accent/ok/warn/err/neutral), `Input`, `Textarea`, `Select`, `Checkbox`, `Toggle`, `Tabs`, `Tooltip`, `Dialog/Modal` shell, `Sheet` (mobile drawer), `Toast` (already `sonner` — re-skin), `Skeleton`, `Kbd`, `SegmentedControl`, `ProgressBar`, `Spinner`, `Avatar`, `Separator`.
- **Composed app pieces:** `DiffHunk`/review row, `CompileStatus` pill, `ATSScoreRing`, `SourceTabs`, editor chrome — all rebuilt on primitives.
- **Rules:** every primitive styles through tokens only; a lint rule (or CI grep) flags new raw hex, `violet-*`/`emerald-*`/etc. accent literals, orphaned `primary-\d`/`secondary-\d`, `bg-gradient-to-*` in app code, and emoji in JSX icon positions. Remove the legacy `Header.tsx` and the `.surface-*`/`.btn-*` globals once migration completes.
- ⟐ **Button conversion is semi-manual, not a mechanical codemod.** `ui/button` is imported by only **2 files**, but there are **~610 hand-rolled `<button>` occurrences across 104 files**. Each must be mapped to a `variant` (primary/ghost/subtle/danger) by human judgment. Sequence: **land the lint guard first** (so no new hand-rolled buttons appear), then convert file-by-file within each surface phase. Do not attempt a blind global codemod.

## 8. Hero & marketing page structure

### 8.1 Hero — "The Living Specimen" (the memorable moment)
The product's own world is typesetting, so the hero *shows a résumé being set and tailored live* — the equivalent of Figma's canvas / Vercel's globe, but honest to Latexy (a "live product embed," which the research calls "a power move if you can pull it off").

- **Layout:** an intentional asymmetric editorial split (breaks the default centered-dev-tool hero) — oversized Fraunces headline + dek + **dual CTAs** on the left; a live **`resume.tex → resume.pdf`** panel on the right that:
  - types a JD chip → proposes 2–3 diff hunks → "accepts" them → recompiles into a clean PDF, on a short orchestrated loop (one staggered page-load reveal, not scattered effects).
  - is **interactive on capable devices** (hover/tap a JD chip to re-tailor); degrades to a **canned animation**, then a **static specimen image**, on mobile / low-power / `prefers-reduced-motion`.
- **Eyebrow** momentum signal (e.g. "New — import projects from GitHub, a URL, or LinkedIn"). **Specific CTAs**: "Start compiling →" + "See a specimen" (never "Get started").
- **Kill** the `@react-three/fiber` icosahedron (heavy, generic, off-concept). Replace with the specimen. (If a 3D moment is wanted later, it should be *typographic* — e.g. extruded letterforms — not an abstract energy core.)

### 8.2 Page sequence (problem-oriented, per dev-tool research)
1. Hero (living specimen) → 2. **Trust strip** immediately after (real, honest stats or "compiles/sec", import sources; no fabricated numbers) → 3. **Feature blocks framed as problems** ("The AI rewrote my whole résumé" → per-change review; "My projects live in GitHub, not a form" → import) using a chess/bento layout, not a function list → 4. The **`.tex`-left / `.pdf`-right** product moment → 5. **1–3 curated testimonials** (real, or omit until we have them) → 6. FAQ accordion → 7. high-contrast full-width final CTA. No "salesy BS."

## 9. Responsive, cross-device & performance (first-class requirement)

This section is a hard requirement, not an afterthought.

### 9.1 Breakpoints & fluid layout
- Tailwind breakpoints: `sm 640 / md 768 / lg 1024 / xl 1280 / 2xl 1536`, plus explicit handling for **small phones (320–375px)** and **ultrawide (≥1920px, cap content width, don't stretch line lengths)**.
- **Fluid type** via `clamp()` on every display/heading token, with min and max caps so text never overflows on 320px or balloons on ultrawide.
- Layout uses **flex/grid + `gap`** (never per-element margins that collapse); wide content (tables, code, PDF, diagrams) sits in `overflow-x:auto` containers so the page body never scrolls sideways.

### 9.2 Navigation & touch
- Desktop nav → **mobile `Sheet`/drawer** below `md`. Hamburger with an accessible labeled trigger.
- **Touch targets ≥ 44×44px**; interactive spacing increased on coarse pointers (`@media (pointer: coarse)`).
- Sticky headers collapse height on scroll for small screens.

### 9.3 The editor & PDF on mobile (highest-risk surface) ⟐ (corrected after scrutiny)
- ⟐ **Reality check:** `MobileEditor.tsx` is **CodeMirror-based** (not Monaco) and **source-only, full-screen, no split/preview tab** (docstring `:17`). The **Source ⇄ Preview tabbing already exists at the page level** in `workspace/[resumeId]/edit/page.tsx` (`isMobile` via `matchMedia('(max-width:768px)')`, `:906/:924/:2316/:2452`) — and is wired into **only that one page**. So the work is:
  - Build the tabbed **Source ⇄ Preview** experience as a **shared page-level pattern**, and **extend it to `/try` and `/workspace/[resumeId]/optimize`**, which currently have no mobile treatment.
  - Add a compile FAB + bottom action bar at the page level.
  - ⟐ **Tokenize `MobileEditor`'s hardcoded colors** (`#09090b`, `#a855f7`, `violet-400` at `:43/:61/:208`).
- **PDF preview**: responsive container, pinch-zoom, fit-to-width default on mobile.
- Panels/modals become **full-height `Sheet`s** on mobile.

### 9.4 Loading & performance
- **Fonts:** `next/font` self-hosted + subset + `display: swap`; **preload** only the above-the-fold face; tune fallback metrics (`size-adjust`) to keep **CLS ≈ 0**.
- **No theme flash:** blocking inline head script sets `data-mode`/`data-aesthetic` from cookie/`prefers-color-scheme` before paint.
- **Code-split** heavy/below-fold pieces (the old 3D hero is removed — it's imported only by `page.tsx:6` via `dynamic()`, so removal is clean and lets us drop `@react-three/fiber`/`drei`/`three` from `package.json`, ~150KB gzip; the live-specimen hero is lazy/`dynamic()` with a static poster as its placeholder so **LCP** is the headline text, not the demo). Heavy editor panels stay `dynamic()`. ⟐ **Fix the `/try` LCP path:** `try/page.tsx:12` currently imports `LaTeXEditor` (Monaco) **statically** — convert it to `dynamic()` like the other panels so the public Studio's first paint isn't blocked by the editor bundle.
- **Images:** `next/image`, AVIF/WebP, explicit dimensions, lazy below-fold.
- **Skeletons** for async data (dashboard, lists) instead of layout-shifting spinners.
- **Targets:** Lighthouse mobile Performance ≥ 90 on marketing pages; LCP < 2.5s, CLS < 0.1, INP < 200ms. Marketing pages ship minimal JS (motion via CSS where possible; framer-motion only where it earns it).

### 9.5 Motion & accessibility
- `prefers-reduced-motion: reduce` disables non-essential motion (hero loop → static, transitions → instant).
- Visible `:focus-visible` rings (token `--accent`) on every interactive element; full keyboard nav; semantic landmarks; `aria-*` on menus/dialogs/toggles.
- Color contrast AA per variant (§5.3); never encode state in color alone (pair with icon/label — the `ok/warn/err` badges already do).

### 9.6 Test matrix
Verify all four theme variants on: iPhone SE (375) / iPhone 14 Pro / Pixel / iPad / 13" laptop / 27" desktop / ultrawide; Safari, Chrome, Firefox; light & dark OS; reduced-motion on/off; keyboard-only; a slow-3G/CPU-throttle pass on marketing. Automated: Playwright viewport snapshots + an axe accessibility pass.

## 10. Full-surface scope

**Marketing (11):** `/`, `/platform`, `/pricing`, `/templates`, `/resources`, `/faq`, `/updates`, `/developer`, `/try`, `/u/[username]`, `/r/[token]`.
**Auth (5):** login, signup, forgot-password, reset-password, verify-email.
**App (18+):** dashboard, billing, settings, byok, tracker; workspace (list, new, history, merge, cover-letters), workspace/[id]/{edit, optimize, cover-letter, career, batch-tailor}, builder/{new,[id]}, workspaces/** ⟐ **including the distinct `/workspaces/[workspaceId]/recruiter` view**; admin (2).
**Shared chrome & the ~100-component library** (editors, ATS suite, 40+ `*Panel`, ~20 `*Modal`, builder, billing, byok, auth, analytics/charts) — migrated to tokens + primitives.
⟐ **Missing framework files to ADD** (none exist today): a global `not-found.tsx`, an `error.tsx` boundary (+ per-group boundaries), and route-level `loading.tsx` files to host the skeletons §9.4 calls for. `/pricing` gets its own marketing component (§6).

## 11. Execution plan (workflow-driven, whole-project)

Sequenced phases; each is a workflow/subagent fan-out with a spec-compliance + quality review gate, and each ends green (typecheck + lint + tests + build) before the next. **No functional regressions** is verified per phase.

- **Phase 0 — Foundation:** route-group restructure (⟐ chrome moves, providers stay at root); `next/font` faces + fallback-metric tuning; token layer (all 4 variants incl. AA contrast verification); `tailwind.config` extended with token colors + ⟐ `darkMode: ['selector','[data-mode="dark"]']` (⟐ legacy ramp NOT yet deleted — only 0-usage gradient presets); ⟐ `ThemeProvider` + new `latexy-theme` cookie + SSR `cookies()` read + no-flash inline script + mode-aware `themeColor`; ⟐ reconcile `TenantThemeSync` (`--tenant-primary` → `--accent`, fix `document.title`); ⟐ own `/pricing` marketing component. Ship one reference page (landing hero) as the pattern.
- **Phase 1 — Primitives:** ⟐ **land the CI lint guard first** (blocks new hand-rolled buttons, raw accent hex, orphaned `primary-\d`, emoji-icons); build the full `ui/` library on tokens; begin the **semi-manual** button/card/badge conversion (~610 sites, per-file, not a blind codemod); remove legacy `Header.tsx`; ⟐ **migrate the 29 `primary-\d`/`secondary-\d`/`blue-50` consumers, THEN delete the blue ramp** with the guard proving zero orphans; retire `.surface-*`/`.btn-*` globals as surfaces convert.
- **Phase 2 — Marketing:** landing (living-specimen hero) + platform/templates/resources/faq/updates/developer + header/footer, per §8; responsive + perf budget met.
- **Phase 3 — Auth:** 5 pages, high-polish, Typeset.
- **Phase 4 — App shell + lists:** app header/nav/sheet, dashboard, workspace/workspaces lists, billing/settings/byok/tracker — Compiler, purge violet/rainbow.
- **Phase 5 — Editor & heavy ecosystem:** editor chrome, ATS suite, all `*Panel`/`*Modal`, builder, charts; mobile editor; purge emoji-icons. The bulk.
- **Phase 6 — Polish & QA:** ⟐ add the global `not-found.tsx` / `error.tsx` / route `loading.tsx` skeletons; cross-device/theme matrix (§9.6), a11y (axe), performance (Lighthouse), visual-regression snapshots, and a final review pass.

Each phase = its own PR(s) following the repo commit procedure (issues first, one-file-per-commit, sub-branch PRs, no self-mentions), CI-green, then merged + deployed.

## 12. Success metrics
- **Zero** feature regressions (full backend+frontend suites stay green; manual smoke of critical flows).
- Lighthouse mobile Perf ≥ 90 and a11y ≥ 95 on marketing; CLS < 0.1; LCP < 2.5s.
- Design-consistency: 0 raw accent hex / non-token accent literals in app code (lint-enforced); one primitive library used everywhere (`ui/Button` import count ≫ hand-rolled buttons, which trend to ~0).
- All four theme variants pass AA contrast on the test matrix.

## 13. Decisions (resolved 2026-08-03)
1. ✅ **Compiler body font: Geist Sans** (OSS, dev-native) + JetBrains Mono.
2. ✅ **Typeset display: Fraunces** (variable, OFL — self-host a subset with the `opsz` axis; display uses large optical size, body uses text optical size).
3. ✅ **`/try` aesthetic: Compiler** (it is the product editor surface); its public header stays auth-aware for CTAs.
4. ✅ **Hero v1: scoped & nudgeable** — a canned `.tex → .pdf` loop the visitor can nudge (tap a JD chip to re-tailor); a fully-live in-hero compile is a fast-follow.
5. ✅ **Mode default: honor OS `prefers-color-scheme`** on both surfaces, with a persisted toggle. All four variants reachable.
6. ✅ **Testimonials: omit until real** — no fabricated social proof; the block ships when we have genuine quotes.
7. ✅ **Copy: replace only slop/placeholder + emoji** for this redesign (a fuller marketing copy pass is out of scope).
