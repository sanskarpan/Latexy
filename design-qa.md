# Landing page visual QA — mobile typography and copy

## Target and scope

Baseline: the previous PR #1899 production captures from source `5bbf7fa80dd4f924c392fc0c75768f81e07a6715`, CI run 38783439606. The latest request approves the desktop composition but explicitly replaces the typography, vague copy and mobile presentation. The baseline is a composition reference, not a requirement to retain its rejected text or fonts.

Source visual truth: `C:/Users/Sansk/.codex/visualizations/2026/10/15/hero-art-direction/hero-production/`.

Implementation: source `46e0b5c94f55643d677a04eb8b0ac55abf75fbe8`, production captures from CI run `38855173196`, extracted into `C:/Users/Sansk/.codex/visualizations/2026/10/16/mobile-copy/mobile-production/`. Public copies and image hashes are in `docs/design/landing-art-direction/provenance.json` on this evidence branch.

## Capture states and normalization

- Desktop: 1440 × 1000 CSS pixels, DPR 1, light and dark, Classic selected. Full page and each section captured separately.
- Phone: first-screen captures at 320, 390 and 430 × 844 CSS pixels, DPR 2.625, light and dark, default compact sample. Source and current 390px captures are both 1024 × 2216 pixels, so no density correction is needed for that pair. Focused section comparisons normalize both sides to a 390px image width; desktop pairs remain at 1x. Original capture dimensions are recorded in provenance.
- Full phone pages and section crops use the device project's original 412 × 839 CSS viewport and DPR 2.625; they are not labeled as the separate 390px first-screen captures.
- Reduced-motion baseline; separate checks exercise normal motion, then verify animations stop when reduced motion is enabled.
- Public, allowed feature fixture; no account data. Browser review also covered the real unresolved-capability state and public fallback links.

## Comparison evidence

Local iteration comparisons are in `C:/Users/Sansk/.codex/visualizations/2026/10/16/mobile-copy/review-final/`. Final production comparisons are in the adjacent `mobile-production/` directory.

- `comparison-desktop-light.png`, `comparison-desktop-dark.png`: baseline and implementation together at identical CSS size; check the retained document composition and updated headline proportions.
- `comparison-mobile-light.png`, `comparison-mobile-dark.png`: matched 390px first screens together, with device density normalized equally.
- `comparison-lp-builder-section-light.png`, `comparison-lp-analysis-section-dark.png`, `comparison-lp-tailoring-section-light.png`, `comparison-lp-applications-section-dark.png`, `comparison-lp-latex-section-light.png`, `comparison-lp-faq-light.png`, `comparison-lp-footer-light.png`: readable focused comparisons, not only long downscaled page strips.

## Iteration history

1. **P2 — vague headline and inconsistent type hierarchy.** The baseline combines a compressed display face, italic serif slogan and small explanatory text. Replace the slogan with a concrete résumé-building headline, scope Geist to homepage headings, and increase explanatory and FAQ text to 16px. Rechecked both themes and all phone widths.
2. **P2 — mobile hero places interaction after the document.** Move the layout selector before the sample, expose adjacent native paper layouts, retain the expandable selected document, and keep the gallery compact. Existing containment, no-WebGL and touch-target checks pass.
3. **P2 — words join when desktop line breaks are hidden on phones.** The first revised capture showed “résumé.See” and “gapsbefore”. Add explicit text spaces around those line breaks. The final focused builder/analysis/LaTeX comparisons show correct spacing and wrapping.
4. **P2 — footer becomes only text on phones.** Restore the existing paper illustration in the mobile composition, with a constrained width and its existing reduced-motion behavior. Require a loaded, visible image in the visual contract; do not relax application behavior tests.
5. **P3 — narrow hero description ends with a single-word line.** Shorten the description to name the guided builder and LaTeX editor directly, and enable improved paragraph wrapping. Recheck 320px in both themes; the PDF phrase remains together in the reviewed captures.

## Required fidelity surfaces

- **Typography:** self-hosted Geist Sans is used for homepage headings and readable body copy; document templates retain their own typography. The mixed italic slogan treatment is intentionally removed. Heading wraps and labels remain legible at 320px. The approved logo is unchanged.
- **Spacing and layout:** desktop hero/document arrangement is retained. Mobile selects a layout before the layered sample, keeps CTAs adjacent, and uses distinct feature labels and consistent section spacing. Demos retain focused phone views instead of stacking entire desktop workspaces.
- **Colors and tokens:** existing light navy/off-white and dark charcoal/brass tokens remain. The mobile paper stage uses the existing soft surface so the documents remain the visual focus. No extra contrast switch is added to the header.
- **Image quality:** hero content is selectable HTML, not a pasted image. Optional Three.js supplies depth; layout controls and content work without WebGL. Footer artwork is the existing high-resolution decorative asset. The generated social preview was opened and inspected for text fit.
- **Copy and content:** headline, feature explanations, footer, social metadata and social preview are consistent. Claims describe existing capabilities. ATS feedback is guidance; suggested experience must remain accurate. Guest limits and account requirements are visible. FAQ schema is generated from the same visible answers. Research rationale and sources are in `docs/design/landing-copy-and-type.md`.

## Interaction and verification

- Classic is first/default; layout controls work with pointer and keyboard.
- Compact/full sample toggles; selected document stays within its scene at narrow widths.
- Builder edits persist across edit, preview and authoring modes.
- ATS categories, tailoring edits/acceptance, board menus and compiler/PDF tabs retain their behavior.
- One visible theme control; contrast remains inside the keyboard-accessible menu.
- No horizontal page overflow or undersized primary controls in the existing phone checks.
- No landing hydration errors in the screenshot contract.
- Local TypeScript and scoped ESLint pass. Initial landing run: 9 passed, 3 device-inapplicable skips. Final screenshot/mobile run: 3 passed, 1 skip.
- Final CI results: {"total": 200, "expected": 190, "unexpected": 0, "flaky": 0, "skipped": 10, "ok": true}.

## Findings and limits

No remaining actionable P0/P1/P2 findings in the reviewed states. This is a technical visual QA result for the requested direction; aesthetic approval of the new typography and copy remains with the user. It does not claim a search ranking or conversion improvement. No merge was performed.

**Final result: passed**
