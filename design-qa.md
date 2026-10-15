# Mobile landing-page QA

Scope: mobile homepage, keeping the approved logo, native document hero and desktop composition. Isolated worktree, branch `codex/mobile-landing`, based on current main `253c5f63`.

## Current-run audit

The live homepage was inspected through the in-app browser at a requested 390 x 844 phone viewport (375px content width with its scrollbar). Fresh light/dark screenshots were opened for the hero, builder, analysis and footer. The authenticated browser also showed a feature-access recovery banner; public PR screenshots will use isolated anonymous fixtures and will not publish account state.

Findings:

1. Hero: headline line breaks and a nearly 700px document gallery dominate the first screens. Product CTAs disappear while capability access cannot resolve. Severity P1 for the missing marketing path, P2 for composition.
2. Builder: editor and full paper stack to over 1,000px. The miniature desktop rail adds controls without labels. P2.
3. Analysis: two stacked panels consume about 775px; keyword content is squeezed into narrow columns and metrics wrap awkwardly. P2.
4. Applications and LaTeX: the board stacks to about 706px, and the code/equation workspace takes about 590px. P2.
5. Footer: about 925px, with a large decorative illustration and small links. Header utility controls also crowd account navigation. P2.

Screenshot inspection alone does not establish accessibility compliance. Keyboard, state preservation, overflow, capability handling and browser behavior require the tests below.

## Changes

- Two-line mobile heading, consistent margins, side-by-side conversion actions and larger touch controls. Public platform/demo links remain available when product-entry gates are closed; all existing product capability gates stay intact.
- Native compact resume preview with layout controls above it and an explicit full-sample expansion. No raster documents or clipped content. The full resume stays available on demand.
- Edit/preview controls preserve builder state and eliminate the stacked full document; Visual/Source/Studio modes remain available. Mobile rail is removed from display.
- ATS overview and keyword report switch between focused panels. Keyword filters use the full panel width and metric controls remain reachable.
- Horizontally scrollable application stages with the next stage visible; existing card menus remain functional. LaTeX uses its existing Source/PDF selection without a duplicated second preview.
- Consistent section spacing, readable light/dark surfaces, larger controls and a shorter footer with the approved logo. The decorative footer illustration remains on desktop.

## Verification

Existing marketing unit tests: 9 passed. Scoped ESLint and TypeScript passed. No existing unit-test assertions were changed; implementation preserved the existing CTA contract after the local checks identified an API/fixture mismatch.

New browser coverage exercises 320/390/430px in both themes, compact/full samples, edit/preview state preservation, analysis views, horizontally reachable card menus, native PDF tabs and public navigation when capabilities are unavailable. Existing five-profile, desktop keyboard, long-content, no-WebGL and reduced-motion assertions are retained. Fresh screenshots are captured per section on mobile as well as desktop.

Browser checks, actual final render inspection and PR screenshots are pending. No visual acceptance is claimed from source code or build output.

final result: blocked — fresh phone renders and required checks pending.
