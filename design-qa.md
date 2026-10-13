# Landing page design QA

Reviewed: 2026-10-14. Scope: homepage marketing surface only. Branch: `codex/landing-document-house`, rebased onto main `d22998e0f45d55fd0a675e4cc622ab603c612d23` in the isolated worktree.

## Evidence and comparison method

Selected target: the third displayed Document House reference, `exec-5ebff909-b113-416f-a1dd-3dfcc450d4dc.png` in the task's generated_images directory. The 1341 x 1173 paired image is split into light/dark halves and proportionally normalized to 1440px wide (2521/2517px tall). No vertical stretching is used.

Final actual source: `acc6c07f0ed3f706e832560040047b23597f6da7`. [Capture run](https://github.com/sanskarpan/Latexy/actions/runs/38476370222), artifact `11856236842`, archive SHA256 `5864b030dfae07febe48ea78022ce7d7680c7b3c32398741a94a4d06e8b66cf2` verified on download. Captured frontend tree: `3f47e634e3aea80e41a7aafd4e0d9a41c2c87a18`.

The source and latest actual renders were opened together in full-page comparison boards and focused section boards. The comparison directory is `C:/Users/Sansk/.codex/visualizations/2026/10/06/01a111a6-7bd6-7a81-9f26-b61e551a5767/landing-qa/current-acc/`. Focused captures cover all ten regions below in both themes, after loading fonts/images and scrolling each region into view. Their layout JSON uses document coordinates. Default state: Modern gallery, guided Visual builder, expanded experience, neutral illustrative keyword status, Source compiler view, collapsed FAQ.

The committed raw captures are [desktop light](docs/design/landing/desktop-light.png), [desktop dark](docs/design/landing/desktop-dark.png), [mobile light](docs/design/landing/mobile-light.png) and [mobile dark](docs/design/landing/mobile-dark.png). Desktop is 1440 x 2553 pixels from a 1440 x 1000 CSS viewport at scale 1. Mobile is 1082 x 13170 pixels from the Pixel 7 profile, approximately 412 x 5015 CSS pixels. Mobile inspection boards normalize density to 412px. Exact hashes and provenance are in [capture metadata](docs/design/landing/capture.json).

## Findings, corrections and post-fix review

The earlier broad sign-off was withdrawn after user feedback. Fresh renders were used to identify and fix remaining differences; build success was never substituted for visual acceptance.

| Region | Corrected detail | Final visual evidence / result |
| --- | --- | --- |
| Hero and header | Two-line headline, chapter/emphasis proportions and baselines, copy position, navy/amber actions, approved Imprint logo | Full boards and `*-lp-hero-comparison.png`; both themes preserve the selected hierarchy and wrapping. |
| Gallery | Exact supplied gallery crop, paper dimensions, pale steel/gold palette, three selectors and selection border | `*-lp-gallery-comparison.png`; Modern now aligns beneath the center paper. Offset applies above 700px; mobile stays centered. |
| Guided builder | Serif heading scale, rail, toolbar tabs, neutral/slate selection, preview proportions, role/company/date and three semantic bullets | `*-lp-builder-section-comparison.png`; final date/list fix is visible in both themes. Editor, source and preview share three bullets. No resize handle remains. |
| ATS and keywords | Separate equal cards, chart scale/labels/fill, status icons and counts, dark recommendation bulb, neutral initial filters | `*-lp-analysis-section-comparison.png`; content is legible, theme contrast and card split match the composition. |
| Tailoring | Inset cells, connector dots, bullet treatment, compact actions | `*-lp-tailoring-section-comparison.png`; no invented achievement is added by the suggested rewrite. |
| Applications | Heading and three columns, count placement, stage symbols, document icons, softened nested borders | `*-lp-applications-section-comparison.png`; titles and dates fit at desktop and wrap on smaller widths. |
| General LaTeX | Source/PDF/Compiler widths, syntax colors, Gaussian equation, actual PDF tab behavior and compile route | `*-lp-latex-section-comparison.png`; current Source boundary is within a few pixels of target. An older claimed 38px offset was rejected against current evidence. |
| FAQ | Four source questions, heading and question column, rule spacing, right-hand plus/minus | `*-lp-faq-comparison.png`; collapsed and expanded states render correctly. |
| Closing action | Compact heading, explanatory copy and primary action | `*-lp-closing-comparison.png`; desktop composition retained; mobile stacks controls. |
| Footer | Brand/tagline group, navigation, sign-in, final action and legal row | `*-lp-footer-comparison.png`; logo and links are visible in both themes. Copyright correctly uses 2026. |

No actionable P0/P1/P2 finding remains in the inspected final states. Independent focused review of the final gallery/builder captures also passed and found no new regression.

## Required fidelity surfaces

- Typography: matched bold sans hero, self-hosted Tinos serif emphasis and section headings, interface/body hierarchy. Font readiness is awaited. Small raster-source glyph/antialiasing differences remain acceptable.
- Spacing/layout: all ten sections retain their order, relative widths and compact vertical rhythm. Final desktop height differs from normalized reference by 32-36px; functioning controls and readable sample content account for the small difference.
- Colors/tokens: navy/paper light mode, charcoal/warm-white/amber dark mode, restrained dividers, neutral/slate builder selection and white document papers checked in actual renders. Existing high-contrast and reduced-motion preferences remain supported.
- Image quality: the supplied gallery art is reused as lossless 1440 x 561 WebP crops, without replacing editable UI with a screenshot. Mobile uses an intentional centered gallery crop. No generic substitute imagery or emoji is used.
- Copy/content: resume-led framing includes guided building, ATS/keywords, tailoring, applications and general LaTeX. Examples are labelled; the rewrite preserves stated experience. Guest/account limits and actual guarded destinations remain truthful.

## Responsive and interaction verification

CI uses isolated synthetic anonymous-session and feature-grant fixtures, not personal browser data or a claim of production backend availability. Chromium, Firefox and WebKit desktop plus mobile Chromium/WebKit all passed the representative visual case. Both themes and long name/role/bullet input were captured. Tablet widths 768, 1024 and 1101px exercise Source and PDF states, expanded FAQ and long input, with document overflow, equation bounds and Compile action bounds assertions. Latest mobile sections and tablet compiler/FAQ/footer renders were visually inspected.

Existing browser contracts cover gallery selection, builder editing and keyboard tabs, analysis filters, rewrite edit/accept/keep-original, application-stage menus, compiler tabs/actual studio destination, FAQ, navigation and access-denied states. No assertion was relaxed or unrelated failing test patched.

All required CI checks passed on the captured source, including production build, frontend/backend lint, backend tests, cross-browser quality, real compile/preview, full-stack smoke and security checks. Local TypeScript, formatting and 23 unchanged relevant contract tests passed. Frozen dependency installation and Next hydration integrity verification passed after rebasing. CodeRabbit skips draft reviews; that status is not a code review approval.

## Acceptable differences and follow-up polish

P3 only: browser glyph rasterization, reference microcopy artifacts, tiny chart-grid/icon-shape differences, and tablet closing-heading wrapping. The reference supplies desktop theme states only; mobile/tablet adaptations are checked for readable layout and working controls rather than an invented pixel-perfect mobile reference. These do not justify another fidelity loop.

The publication commit changes only this report and screenshot documentation; its frontend tree must remain identical to the captured tree. This remains a draft PR for user review and has not been merged.

## Implementation checklist

- [x] Exact selected reference resolved and paired with current actual captures.
- [x] All ten sections checked in light and dark mode, with focused evidence.
- [x] Earlier actionable findings corrected and freshly recaptured.
- [x] Mobile/tablet, long input, disclosures and key interactions verified.
- [x] Actual post-commit page screenshots published in the PR with provenance.
- [x] Main checkout left untouched; captured source CI passed.

final result: passed
