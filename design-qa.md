# Landing art direction review

Scope: homepage marketing surface only. Source commit: `5bbf7fa80dd4f924c392fc0c75768f81e07a6715`; frontend tree: `de1c3ded008dd226dfb446322068e4563166e575`.

## Target and state

The previously selected Document House light/dark references are the target. The later user corrections take precedence: Classic first/default, real interactive HTML documents, a dedicated phone composition, one exposed theme control, contrast inside the menu, and the subsequently approved editorial footer.

The desktop source images are 1440 CSS pixels wide at 1x. Browser comparisons use the same width, light/dark theme, anonymous fixture session, and initial sample state. Classic replaces the mockup's Modern selection by explicit user request. The references contain no phone target; phone review therefore evaluates the same art direction and the user's responsive requirements rather than claiming a nonexistent pixel match.

## Evidence and iterations

1. Fresh live review found the shallow plinth and framed side papers had lost the approved tall folded surround. Restored six Three.js folded surfaces and unframed native papers; retained pointer response, touch/keyboard layout selection and a CSS fallback when WebGL fails.
2. The first local render exposed clipped side papers and labels crossing the stage edge. Corrected the stage bounds and label backgrounds. The existing bounds checks were retained.
3. Same-width source/render comparisons found overly bright gold and flat side papers under reduced motion. Changed the dark surround to restrained brass/charcoal and retained the authored static paper angles while disabling motion.
4. The 320px capture showed role dates touching the title. Dates now occupy their own line below 380px. Recaptured both themes after the commit.
5. Console inspection identified an existing chart hydration warning: server/browser trig results differed at the final floating point digits. Rounded the marketing SVG coordinates to three decimals and added a hydration-error assertion. Fresh capture and console review confirm the warning is gone; no tests were relaxed.

Full-view comparisons and focused hero, builder, ATS, tailoring, board, LaTeX, FAQ and footer renders were opened. This includes phone previews at 320/390/430 CSS pixels and tablet compositions at 768/1024/1101. Mobile screenshot pixel dimensions reflect the Pixel 7 device scale factor; compare geometry in CSS pixels rather than interpreting 1024px raster width as a desktop viewport.

## Interaction and accessibility review

- One visible light/dark button. Contrast is in the desktop and mobile navigation; toggle, Escape and focus return were exercised.
- Classic is the first/default selection. Pointer, keyboard, repeated arrow navigation, and no-WebGL sample selection were checked.
- HTML papers remain selectable; the hero contains no image elements. Three.js renders only the surround, with capped pixel density and demand rendering.
- Reduced motion retains the static composition; offscreen/hidden scenes stop rendering.
- Phone CTAs remain adjacent. Phone sample expansion, builder edits/preview, ATS overview/keywords and compiler/source/PDF controls retain their existing behavior.
- Existing overflow, document containment, minimum tap target and public-navigation fallback checks remain enabled.

## Verification

Local ESLint and TypeScript checks pass. The final targeted browser run reports 9 passed, 3 device-inapplicable skips, 0 failed, 0 flaky. Linux CI run `38783439606` passes the production build, lint, cross-browser quality, real compile/preview and security checks for source commit `5bbf7fa80dd4f924c392fc0c75768f81e07a6715`. The quality report records 195 total: 185 passed, 10 device-inapplicable skips, 0 failed and 0 flaky. Vercel also deployed that revision successfully. Windows local standalone packaging is limited by unavailable symlink permissions; no packaging or test gate was changed to work around it.

## Remaining review notes

The native scene has simpler paper shadows than the photographic reference (P3). Resume text and layout details are genuine HTML and differ from the raster mockup. The previously approved footer remains intentionally larger than the original reference footer. These are disclosed differences, not a claim of pixel-identical reproduction or user aesthetic approval.

Production screenshots were downloaded from the completed source CI run, verified against artifact SHA-256 `1ae9b190e4296aae195440c2a8a212c63b4703bd943c56b7e3bcddaed3b75327`, and inspected in both themes. Fresh 1440px source/production comparisons were opened together; phone 320px Chromium and 390px WebKit renders and the WebKit builder were also inspected at full resolution. The corrected document bounds, narrow date line, reduced-motion angles and restrained dark palette remain intact.

## Saved evidence

See [screenshots](docs/design/landing-art-direction/README.md) and [provenance](docs/design/landing-art-direction/provenance.json). The twelve post-commit screenshots are actual production-bundle renders from source CI; they supersede the earlier development captures. Hero crops are documented derivatives of full-page screenshots; the other images are unchanged extracted PNGs. This evidence branch has exactly the same frontend tree as the tested PR: `de1c3ded008dd226dfb446322068e4563166e575`. The QA pass assesses visual/interaction readiness for user review, not user aesthetic approval or permission to merge.

final result: passed

