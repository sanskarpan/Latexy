# Landing page visual QA — glass, motion and sound

## Target and scope

Baseline source `46e0b5c94f55643d677a04eb8b0ac55abf75fbe8`, CI run 38855173196. Source visual truth: `C:/Users/Sansk/.codex/visualizations/2026/10/16/mobile-copy/mobile-production/`.

The requested revision intentionally adds a glass control layer, motion and optional sound to this composition. The reference examples and implementation decisions are documented in `docs/design/landing-glass-and-motion.md`. This is a refinement of the existing homepage, not a clone of the unrelated reference sites.

Implementation source: `136eb5a95bac7558ae4d3ab78432f415781c1f0b`. Production captures: CI run `38895240269`, extracted into `C:/Users/Sansk/.codex/visualizations/2026/10/16/liquid-glass/glass-final/`. Published copies and hashes: `docs/design/landing-art-direction/provenance.json` on this evidence branch. Its frontend tree is identical to the PR source tree.

## Capture states and normalization

- Desktop: 1440 × 1000 CSS pixels, DPR 1, light/dark, Classic selected. Full page and individual sections.
- Phone first screens: 320/390/430 × 844 CSS pixels, DPR 2.625, light/dark. The baseline and implementation 390px captures both measure 1024 × 2216 pixels. Pair these originals without unequal density scaling.
- Full phone pages and section captures: 412 × 839 CSS pixels, DPR 2.625. Focused paired section images normalize both sources to 390px image width for reading.
- Preferences screenshots use the browser projects' 1280 × 720 desktop and 412 × 839 phone viewports. Their menu is open with sound explicitly enabled.
- Screenshot fixtures use reduced motion, allowed public product capabilities, no private document content and default sample data. Other functional checks exercise normal motion, no-WebGL, keyboard/touch controls and feature-unavailable states.
- Local review also covered a 320px light phone, 390px dark phone, 1440px desktop, scrolled sticky navigation and an 844 × 390 landscape menu. The local unresolved-capability banner is expected without the backend and is not present in the allowed production screenshot fixture.

## Comparison evidence

Baseline and implementation are placed together in every comparison input. Local iteration comparisons: `C:/Users/Sansk/.codex/visualizations/2026/10/16/liquid-glass/review-final/`. Final production comparisons: adjacent `glass-final/`.

- `comparison-desktop-light.png` and `comparison-desktop-dark.png`: matched top-of-page composition, native documents and navigation.
- `comparison-mobile-light.png` and `comparison-mobile-dark.png`: matched 390px first screens.
- Focused pairs for `lp-builder-section`, `lp-analysis-section`, `lp-tailoring-section`, `lp-applications-section`, `lp-latex-section`, `lp-faq` and `lp-footer` in both themes.
- Original phone captures at 320/390/430px, gallery and preferences screenshots provide readable control detail. Section element screenshots can include the sticky header over the scrolled content; the full-page screenshot is used to assess unobscured section composition.

## Iteration history

1. **P2 — contrast mode retains the blur.** Initial integration checks showed the emitted CSS had lost the backdrop-filter reset even though the source declaration existed. Reverse the prefixed/standard reset order. The final browser contract requires the actual computed filter to be `none`, after the root contrast state changes. Both local desktop and phone checks pass; existing tests were not weakened.
2. **P2 — sticky menu in a short viewport.** Constrain its maximum height to the viewport and allow internal scrolling. At 844 × 390 the measured menu remains inside the viewport while all preferences and links remain scrollable. Add anchor scroll margins so the sticky header does not cover target headings.
3. **P2 — sound preference stacks into a tall block.** The first production menu capture exposed the missing flex row. Give both preference controls the same row alignment/radius and remove the redundant waveform. Keep the dropdown reading surface opaque with its material rim. The initial dark capture also caught an opening animation; final captures now wait for opacity 1 and height auto before visual assessment. Recheck enabled sound in both themes on desktop and phone, with a maximum 52px row-height regression guard.
4. **P2 — enabled sound needs a visible keyboard focus ring.** The active control uses the accent fill, so its inset accent outline did not remain visible. Move the outline 2px outside the button. The final source commit contains this correction; the tested menu captures show its ordinary enabled state.
5. The paired visual review confirms the intended changes: floating header, shallow document rim, coherent sliding selector and tactile secondary CTA. Existing section composition, brand, text and document content are retained.

## Required fidelity surfaces

- **Typography:** existing self-hosted Geist hierarchy is retained. Native résumé templates keep their typography. Headline, explanatory text and selector labels are readable in the narrow phone captures. No typeface download was added.
- **Spacing and layout:** the floating header adds a small intentional vertical offset. Phone CTAs remain beside each other, Classic remains first/default, demos stay in focused phone views, and the footer keeps its visible paper illustration. Menu controls remain available in short windows.
- **Colors and tokens:** navy/off-white light and brass/charcoal dark palettes remain. Glass has a restrained rim/highlight; reading surfaces remain opaque. High contrast and reduced transparency remove navigation blur. Only one theme control is visible; contrast and sound are inside Preferences.
- **Image quality:** hero documents remain real selectable HTML, with optional existing Three.js depth. No raster hero, stock background or generated full-page image was introduced. Logo and existing decorative footer artwork remain sharp and unchanged.
- **Copy and content:** the existing product-specific copy and metadata are retained. No fabricated features, testimonials, conversion claims or phrases from the reference sites were added. The only new product text is the explicit sound preference and Preferences label.

## Interaction and performance verification

- Six local sound unit tests pass. Local TypeScript and scoped ESLint pass.
- The earlier implementation commit passed the full frontend unit suite: 2,891 tests across 293 files. The final source commit's quality job ran its applicable browser suites, including the sound contract.
- Local landing browser checks: 13 passed, 3 device-specific skips, no failures/flaky tests.
- Browser sound contract: no AudioContext from load or scroll, opt-in creates one, selecting a layout reuses it, mute closes it, no media requests, high contrast computes no blur.
- Existing builder edits, authoring modes, ATS controls, tailoring actions, application menus, compiler/PDF tabs, public feature gates, keyboard menu dismissal and theme controls remain covered.
- Reduced motion, no-WebGL and narrow-screen containment retain their existing checks. No landing hydration errors in the visual contract.
- No dependency or audio file added. Native CSS scroll timelines provide progressive enhancement without a new JavaScript scroll loop. Blur is limited to navigation surfaces; there is still a small compositing cost.
- Production CI quality results: {"total": 205, "expected": 195, "unexpected": 0, "flaky": 0, "skipped": 10, "ok": true}.

## Findings and limits

The final production captures were reviewed at 320, 390 and 430 CSS pixels and at desktop size in both themes. The open Preferences menu remains readable and compact in both themes on phone and desktop. No remaining P0, P1 or P2 issue was found in those captures or the applicable browser checks. The final source still needs the user's aesthetic review before this draft PR is merged.

The Vercel deployment check passed, but its preview URL required login in the available browser. Visual acceptance is based on the actual local page and production-bundle CI renders rather than a claim of inspecting that protected deployment.

**Final result: passed for the tested source and production captures; draft visual review remains open.**
