# Landing-page design QA

Source `bd989cdf2ee653aa748e2617e685dab24fecadaa` · frontend tree `f9cc96f30f5f01162619fc2cb5c325daaa627a73` · [CI run 38955373292](https://github.com/sanskarpan/Latexy/actions/runs/38955373292).

## Implemented design

The opening now pairs a direct résumé message with a native HTML document workbench. Visitors can edit an unsaved sample heading and compare three layouts. Classic stays first and selected by default. The phone preview is compact and expands through a disclosure; the desktop frame grows with long names and roles.

A five-chapter index connects the interactive builder, ATS, tailoring, application tracking and LaTeX demonstrations. Glass remains in controls and navigation. Existing optional sound, reduced motion, no-WebGL behavior, capability gates and the approved mark remain supported. No UI dependency was added.

## Visual review

Reviewed actual desktop and phone captures in both themes, including the first screen, document, ATS chart, tailoring controls, application board, LaTeX sample, FAQ and footer. The first iterations exposed excessive phone height, paper bounds outside the scene and tight tablet equation space; the UI was corrected without relaxing those contracts.

The selected reading surface stays in normal layout flow, and long unbroken name and role inputs are checked for containment and page overflow. Screenshot review uses native-resolution details: a scaled dark preview appeared blank, but the original PNG and a pixel comparison confirmed its text. The phone contract records its text region before capture and checks the actual heading color on light paper.

The final WebKit diagnostic compared offscreen button boxes immediately after a viewport resize. That check now scrolls the controls into view, settles layout and reads both rectangles in one frame; its alignment tolerance and overflow limits remain unchanged. The failed run is retained in CI rather than replaced by a retry.

## Verification

Browser report: `{"total": 210, "expected": 200, "unexpected": 0, "flaky": 0, "skipped": 10, "ok": true}`. The source is also covered by the PR's production build, lint, security and real compile/preview checks. TypeScript and scoped ESLint passed locally. The screenshot extractor was verified against a completed Playwright report and publishes unchanged PNGs with hashes.

The local Windows bundle compiled, passed type validation and generated all pages. Standalone packaging encountered Windows symlink restrictions, and automatic approval review blocked launching the local production listener, including a loopback-only attempt. The final visual and packaging evidence therefore comes from CI's clean environment.

## Limits

The reviewed contracts cover representative sizes and states, not every possible device setting. Sample edits are local marketing-demo state and reset on a new visit. Controlled browser fixtures do not establish live backend availability.
