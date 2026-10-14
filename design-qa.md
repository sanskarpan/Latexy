# Landing page design QA

Reviewed: 2026-10-14. Scope: homepage marketing surface only, in the isolated landing-redesign worktree. Base: main `7cb1c8b7c58a3b4227c2d7a3a344c6300397a82f`. Existing pricing-navigation and interaction updates on the PR branch were preserved.

## Reference and actual evidence

The selected third Document House image remains the body reference. Its paired 1341 x 1173 light/dark image was proportionally normalized to 1440px for section comparisons, without vertical stretching. Earlier section corrections and full-gallery overview were reviewed in source `036eed8e`; fresh integrated-source full-page and footer captures confirm those details remain intact.

The user explicitly amended the design: adjacent mobile hero actions, consistent header utilities, Classic first/default, interactive visualizations, and a stronger footer inspired by [Footer.design](https://www.footer.design/). Browser inspection covered Trove, Aperios, Nothin and Decimals. The footer adapts their large brand-signature and restrained navigation patterns; external images/code were not copied into the product. The approved Imprint mark and Latexy wordmark are unchanged.

Captured source: `2e77fe739cf99ea808acc2e94a0841055ba7a6a7`.
Frontend tree: `d01ba777b9aa7efb92b677ffb0034528824dd9cb`.
[CI capture run](https://github.com/sanskarpan/Latexy/actions/runs/38551530713), artifact `11887583747`.
Verified archive SHA256: `989136f6e9be0bf1db7908fbfd08307d31887e69509659ce81b33fc1a15c1a15`.

Actual post-commit captures are published in `docs/design/landing/`: desktop light/dark (1440 x 3420), mobile light/dark (1082 x 14792), and focused footer light/dark (1440 x 934). Exact file hashes and provenance are recorded in `capture.json`. These are browser renders, not generated mockups. Synthetic anonymous-session and feature fixtures isolate CI from personal data; screenshots do not imply production backend availability.

## Section review

| Region | Actual review result |
| --- | --- |
| Header and hero | Approved logo, two-line hierarchy, coherent borderless utility controls; mobile actions share a row at 412px and 320px. |
| Gallery | Classic is first and selected by default; the initial complete overview remains visible. Selection and keyboard interaction are covered. |
| Guided builder | Existing visual/source/studio tabs, sample preview, date and semantic bullets retained; long content captured. |
| ATS and keywords | Chart and keyword cards remain legible in both themes; metric selection exposes the sample score/explanation with a live region. Scores remain explicitly illustrative. |
| Tailoring | Existing content and actions retained; accept, edit and keep-original interaction sequences covered by focused browser cases. |
| Applications | Three stages retain readable cards; stage-menu interactions covered. |
| General LaTeX | Source/PDF/compiler composition retained, including equation and action bounds at 768/1024/1101px. |
| FAQ | Existing question hierarchy and collapsed/expanded disclosures retained. |
| Closing action | Integrated editorial footer heading and guarded build action; paper imagery supports the call to action. |
| Footer | Oversized approved brand signature, three compact link columns and legal row checked in both themes. At 320px, longer links wrap naturally without overlap; wordmark fits inside the container. |

The full light/dark pages, focused footer captures, mobile top/bottom inspection boards and narrow-mobile footer were opened and inspected. No actionable P0/P1/P2 issue remains in these states. The taller footer is an intentional user-authorized departure from the original compact reference.

## Verification

- All CI checks passed on the captured source: production build, frontend/backend lint, backend tests, cross-browser quality, real compile/preview, full-stack smoke, contracts and security checks. Vercel deployment also succeeded.
- Representative visual evidence passed in desktop Chromium, Firefox and WebKit, and mobile Chromium/WebKit, in both themes.
- Browser assertions cover mobile action placement, header borders, default layout, pricing flags, gallery keys, tabs, metric selection, tailoring/application interactions, overflow, long input and FAQ states.
- Motion uses finite paper movement and brief section entrances. Browser checks verify motion starts when visible and stops under reduced motion. Content remains visible without animation.
- Nine focused marketing contract tests passed locally after the footer revision, including pricing-navigation tests. No unrelated functional tests were patched.
- The screenshot publication changes only documentation and image evidence; its frontend tree must equal the captured tree above.

## Accepted minor differences

P3: browser font rasterization, tiny chart/icon differences from the raster reference, and natural text wrapping at narrow widths. The source reference supplies desktop states; mobile adapts the composition for readability. No additional fidelity loop is justified by these differences.

This remains a draft PR for user review and has not been merged. CodeRabbit skips draft review; its status is not a code-review approval.

final result: passed
