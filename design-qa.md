# Review Desk visual QA — 17 October 2026

## Result and scope

The selected second direction is implemented as native, interactive UI. No actionable P0, P1 or P2 visual finding remains in the reviewed homepage states. This is visual acceptance of the marketing page, not a claim that the entire product has no bugs. Production CI is reported separately in PR #1923.

Product source: `32fdea72078c5a3824570fdba89bed582c47f044`, rebased on main `fc3e3df9`. The primary checkout was not edited. Only the homepage, its header/footer and relevant marketing contracts were changed.

## Visual truth and captures

- Selected direction: option 2, The Review Desk. User authorised new fonts and more useful copy.
- Revised source: `docs/design/review-desk-target.png`. Original generated reference: `C:/Users/Sansk/.codex/generated_images/01a111a6-7bd6-7a81-9f26-b61e551a5767/exec-88ae5791-aebc-4bb3-a083-0df0ec05b49f.png`.
- Actual captures: `docs/qa/review-desk-2026-10-17/desktop-{light,dark}-full.png` and `mobile-{light,dark}-full.png`. Hero files are native-density top crops of those screenshots.
- Route/state: `/`, signed out, Review selected, original sample wording, Classic layout, normal contrast, reduced motion for stable capture. Existing quality API fixtures enable normal public guest features. These are actual local development renders from the committed source, not generated mockups or production-site screenshots.
- Desktop: Chromium, 1440×1000 CSS viewport, DPR 1; full page 1440×4454 pixels.
- Phone: WebKit iPhone profile, 390×1000 CSS viewport, DPR 3; full page 1170×16434 pixels. Additional checks cover 320, 360, 430, 768, 1024 and 1101 CSS pixels in both themes.
- The source board is 1536×1024 pixels. Desktop crop: `(22,59)-(964,970)`; light phone: `(976,59)-(1237,970)`; dark phone: `(1252,59)-(1518,970)`. The board does not specify a CSS viewport or DPR. Comparison copies normalise width only: desktop 1440, phone 390; aspect ratio is preserved. The phone reference is taller than the actual viewport. These comparisons establish composition and fidelity, not a misleading pixel-perfect score.
- The small circular N in local captures is Next development chrome, not product UI. Screenshots are not masked. Full images are untouched; section and hero images are crops. `capture.json` records source and capture details.

## Combined comparisons inspected

Reference and actual were composed into the same image before judgment:

- `comparison-desktop-light.png`: complete desktop source and corresponding implementation region.
- `comparison-mobile-light.png`, `comparison-mobile-dark.png`: phone source and native UI, with density normalised.
- `comparison-detail-type.png`: readable desktop headline, description, actions and guest note.
- `comparison-detail-paper.png`: résumé hierarchy, highlighted sentence, attached review, connector and workflow tabs.

Focused actual section crops were inspected because a whole-page thumbnail cannot establish readability: `section-desktop-{light,dark}-{1,2,3,4}.png` and `section-mobile-{light,dark}-{1,2,3,4}.png`. The source board ends after the next-steps overview; lower sections are original extensions of its visual language, not claimed replicas of an unseen reference.

## Findings and comparison history

1. **[P1, resolved] WebKit rendered variable display/body fonts too thin.**
   Evidence: `iteration-variable-font.png` and the first WebKit comparison. Correct computed weights did not produce the intended optical weight. This weakened hierarchy on phone. Replaced variable delivery with static instances, then captured WebKit again. The final combined phone comparisons show the intended solid headline and readable body. Derivative names, attribution and OFL notices are included in `fonts/FONTLOG.md`.
2. **[P2, resolved] Phone sample type was too small and the review controls needed larger targets.**
   Raised document text to 14px, note body to 13px, quotation to 14px and phone buttons to 44px minimum. Final phone hero comparisons show clear text, adjacent primary actions and separate, usable review actions. Long role/contribution values wrap without horizontal overflow.
3. **[P2, resolved] Desktop document and annotation were undersized next to the display heading.**
   Evidence: `iteration-small-desktop.png`. Raised document body 12→14px, annotation body 11→13px, quotation 12→14px and relevant small labels. Eased headline tracking. Final `comparison-detail-paper.png` and desktop hero show the corrected density; the annotation remains anchored after reflow.
4. **[P2, resolved] Hiding the overview line break joined “next” and “steps” on phone.**
   Added an explicit word space before the responsive break. Final `section-mobile-light-1.png` shows “Keep the next steps in view.” The browser contract now asserts the complete accessible heading at every tested width/theme.
5. **[P2, resolved] Review undo could restore an unfinished Write draft instead of the previous applied wording.**
   Separated the undo snapshot from the unsaved draft and tracked dirty edits. Regression coverage verifies Undo and Keep original preserve unfinished input and restore the correct paper text on desktop Chromium and mobile WebKit.
6. **[P2, resolved] Menu could accept an early tap before its parent was hydrated.**
   Keep it disabled until the parent handler is ready. Appearance/menu keyboard contracts remain enabled.

## Required fidelity surfaces

### Fonts and typography

Latexy Display is a static Hubot-derived display subset; Latexy Reading is a Mona-derived body subset. The user explicitly requested a font change, so exact reproduction of the generated typeface is not a goal. Static weights avoid the observed WebKit variation. Tinos distinguishes typeset documents from the marketing voice. Headline hierarchy, two-line hero, wrapping, label weights and quote readability were inspected in combined comparisons and native renders. No rasterised text is used. The existing brand wordmark is retained.

### Spacing and layout rhythm

Desktop preserves the asymmetric copy/document composition, attached annotation and lower workflow. Phone has its own sequence: introduction, adjacent actions, workflow, readable excerpt and review. Secondary desktop history is omitted from the phone excerpt. Long sample text, all four modes and layout changes were checked. The overview remains a compact pair; supporting sections use consistent dividers and aligned columns. No page overflow at tested widths. Width-normalised concept-board proportions differ from a specified CSS design; the compact 48px phone actions and shorter document are deliberate usable UI choices.

### Colors and visual tokens

Ivory/navy in light mode; deep navy, pale blue and light text in dark mode. Existing semantic color and high-contrast tokens are retained. Highlight, selected step, focus and primary actions share the accent. The source's pale feedback treatment maps to the existing semantic highlight rather than introducing a second palette. Borders and surfaces remain visible in both modes. High contrast stays inside Menu; one theme control remains in the header.

### Image quality, assets and icons

The hero is selectable HTML, inputs, radios and semantic tabs. No image/canvas, blurred screenshot, WebGL requirement, fake avatar or stock decoration. The visual reference describes editable document UI, so code-native rendering follows the user's explicit requirement. The approved Baseline SVG is reused, with Tabler icons for interface controls; no substitute logo or bespoke illustration was drawn. The source's invented percentage and profile URL are omitted. Full-density mobile captures show sharp document text.

### Copy and content

Hero copy states the actual tasks: build without code, check structure, tailor to a job and export a LaTeX PDF. Sections separately explain ATS guidance, application organisation and non-résumé LaTeX work. Samples are labelled illustrative. No customer numbers, invented hiring results, universal ATS guarantees or fabricated testimonials. Guest limits and account requirements are visible. Metadata, canonical, application schema, ownership verification and visible FAQ/schema agreement are retained. Research and official references are in `docs/design/landing-review-desk.md`; no ranking or AI-search guarantee is claimed.

## Interactions, accessibility and verification

- Edit role and contribution; apply/undo/decline suggestion; retain saved and unfinished text across stages; select target-role guidance; change Classic/Modern/Minimal layouts; reset on reload.
- Radix keyboard tabs, labelled fields/radios, live status feedback, native text selection and touch controls. Classic is first and selected by default.
- Supporting ATS tabs, application stage selectors, source/PDF tabs, FAQ disclosure, theme, contrast menu, opt-in sound, navigation and capability fallback.
- Reduced motion disables animation; no sound before explicit opt-in; hero works without WebGL. Runtime-error collection in final capture tests is empty.
- Final focused run: native hero and capture contracts in desktop Chromium/mobile WebKit. Four tests passed. Phone long-text/mode contracts passed in both themes. Earlier full marketing contracts passed on desktop/mobile Chromium; core native/keyboard/gates contracts also passed on desktop WebKit.
- Relevant unit tests: 14 passed across five files. Targeted ESLint passed. Production build passed before final naming-only font change; current production build and all-engine browser checks run in CI.
- Broader Windows unit run: 290 files passed, five files failed (five assertions plus one Monaco suite setup error). All failures reproduce in an untouched main worktree with the same dependencies. They concern CRLF/source-string and local patch/tooling assumptions; no unrelated assertions or product code were patched. Linux CI on the preceding source revision passed the complete unit suite after the missing metadata-test font mock was added.
- Local Firefox launch fails with Windows `spawn UNKNOWN`; Linux CI covers it. Existing Windows WebKit keyboard/sound assumptions are not reported as full-suite success.
- Automatic approval review blocked a local production-preview launch. Visual work continued in the already-running development preview; CI exercises the production bundle. No workaround server was launched.

## Expected differences and follow-up polish

- Font/copy changes were explicitly authorised. Product truth takes priority over generated example claims.
- The concept board does not define supporting sections, interaction states or every breakpoint. These are implemented as coherent extensions using real product routes and existing permission gates.
- Whole-app JavaScript-disabled operation is outside this homepage redesign: the shared Next streaming/loading shell still needs framework bootstrap. Native sample/copy are delivered in response HTML, but this is not a full no-JavaScript website guarantee.
- [P3] A future review could tune the exact display tracking or expand the illustrative sample. No extra decorative effects are needed to complete the selected direction.
- Deployment remains held; Vercel rate limiting is the user-approved deferral. This report does not claim production deployment.

## Implementation checklist

- [x] Resolve option 2 and inspect the exact revised reference.
- [x] Build real interactive hero with no raster product preview.
- [x] Check phone light/dark and narrow widths separately.
- [x] Fix and recapture every P1/P2 visual/state finding above.
- [x] Inspect combined comparisons and readable section details.
- [x] Preserve brand, product entry gates, truthful copy and search metadata.
- [x] Capture committed page screenshots for PR review.

final result: passed
