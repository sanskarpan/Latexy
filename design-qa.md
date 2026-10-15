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

## First capture review

Source `613efd59`, artifact `11982286315` from run `38749680730`, archive SHA256 `e9fb92b75f50d9b833419d7f8cd6f582aafd08f531d11921934300ccb0bd5a65`, was downloaded, verified and inspected. Native 320/390/430px first screens, light/dark gallery, builder editor/preview, ATS/keywords, applications, tailoring, LaTeX and footer were opened at full resolution. Desktop gallery remained intact.

The new mobile interaction cases passed in Chromium and WebKit, as did all no-WebGL and public fallback cases (175 passed, 10 skipped). Five representative cases failed on changed UI assumptions: a hidden fallback anchor was included in geometry, and mobile footer motion was checked on the intentionally hidden illustration. The checks now require two visible actions, restore the original device viewport for motion checks, retain desktop paper motion, and verify the visible phone brand reveal plus zero animations under reduced motion. No unrelated functional test was patched.

Visual review identified a duplicate mobile document caption caused by CSS ordering, a list marker against its container border, extra analysis switch padding, and inconsistent Source/PDF control styling. These are corrected together with header label sizing and readable rewrite inputs. The mobile browser contract now covers caption suppression and a full rewrite edit/accept flow.

Fresh renders and required checks for the corrected source remain pending. No visual acceptance is claimed from source code or build output.

final result: blocked — corrected phone renders and required checks pending.
