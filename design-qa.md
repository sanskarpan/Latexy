# Mobile landing-page QA

Scope: mobile homepage, keeping the approved logo, native document hero and desktop composition. Isolated worktree, branch `codex/mobile-landing`, started at `253c5f63` and integrated current main `2e77a1ca` without conflicts. That main update changed documentation only.

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

## Corrected capture review

Source `4996cff1`, artifact `11982989437` from run `38753709994`, archive SHA256 `ed07495127e9cc7ec815f606127e5842ec75b81aac29de65c4e8074be43b6d71`, was verified and opened. Both phone engines passed the representative evidence, new six-width/theme combinations, touch-target, edit-preservation, rewrite and public fallback contracts. Full quality result: 178 passed, 2 failed, 10 skipped, no flaky cases.

1. Header and hero: 390/430px composition is readable; CTAs share a row. Chromium at 320px exposed doubled header gutters that wrapped utilities. Source `393214f5` removes the extra inset, retains 44px targets and asserts the brand/utilities share a horizontal center line in all six phone combinations. Fresh confirmation is pending.
2. Document gallery: duplicate caption removed; Classic remains first/default. Classic, Modern and Minimal have readable native text and a reachable full-sample expansion, including without WebGL. No clipping observed in opened gallery captures.
3. Builder: the editor and preview are distinct focused views in both themes. The edited synthetic bullet appears in the actual preview and survives return to the editor/source. No second full document underneath the editor.
4. ATS: overview and keyword panels use consistent selection controls and full panel width. Chart labels, metric controls and keyword results are readable in both themes.
5. Tailoring and applications: list markers sit inside their container; rewrite editing uses 16px text and passes the edit/accept flow. The board shows one stage plus the next-stage edge; menus remain reachable by horizontal scrolling.
6. LaTeX: Source/PDF controls match the other secondary views; readable source, 44px compile action and no duplicate PDF panel on phones. The native PDF tab works.
7. FAQ and footer: legible disclosures, large link targets, compact three-column directory and approved brand signature. Both theme footer captures were inspected. Desktop retains its illustration.

The two failures are desktop motion checks introduced by the additional target scroll. The Chromium trace records that scrolling the animated image waited 4,640ms for stable geometry, consuming the 4,500ms float before testing whether it was running. The test now scrolls the static footer on desktop (as before) and only scrolls the phone signature. The animation-running assertion and reduced-motion zero-animation assertion remain. No production motion code was changed to address this test issue.

## Final capture acceptance

Source `393214f5957c68fac7fda8d5fb96326934587a9e`, artifact `11985179689` from [run `38757881363`](https://github.com/sanskarpan/Latexy/actions/runs/38757881363), archive SHA256 `5269682dba8b78af5cd8e3c72f20de4c74202bba230cc40c602a6aeb33da9869`, was downloaded and verified. Quality report: **180 passed, 10 intentionally skipped, 0 failed, 0 flaky** across five profiles. Every reported source CI check passed, including build, lint/unit, backend, full-stack smoke, isolated real compilation and browser quality. CodeRabbit's draft status is a skipped review, not a code-review approval.

The six Chromium first screens and WebKit 320px dark first screen were opened. The header now stays on one row with aligned controls in both themes. Fresh section captures were compared with the inspected `4996cff1` captures: gallery, builder, ATS, applications, FAQ and footer have identical pixels. The changed tailoring/LaTeX captures and interactive builder/keyword states were opened again and accepted. Desktop rendering and all three no-WebGL layouts retain their earlier composition and passed their browser contracts.

Seven steps above are healthy within the inspected scope. Remaining evidence limits: screenshots use anonymous-session and feature fixtures; they do not establish production service health or full accessibility conformance. Production verification and the final publication revision's required CI are recorded in the PR before merge.

Twenty-two actual PNGs are copied unchanged to [the capture directory](docs/design/landing-mobile/README.md). [Capture metadata](docs/design/landing-mobile/capture.json) records source, archive digest, original attachment names, dimensions and image hashes. The publication commit retains source frontend tree `f003165b661e39f7170cb8b4b39679452c8d3f9d`; only documentation and captures are added after visual acceptance.

Before final verification, main advanced to `482a9b17` with the multilingual renderer VM memory reservation and its backend contract test. That update was integrated without conflicts. The captured frontend tree remains identical; the combined revision runs the required CI before merge.

Main subsequently advanced to `a03ca9de` with the multilingual LaTeX language/font setup and backend tests. It was also integrated without conflicts or frontend changes; required checks run on that latest combined revision.

final result: passed — mobile composition and interactions accepted in both themes, with source CI green and evidence saved.
