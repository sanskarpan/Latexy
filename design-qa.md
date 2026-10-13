# Landing page design QA

Date: 2026-10-13. Selected target: the third displayed concept from the second ideation set (Document House). Implementation branch: `codex/landing-document-house`, based on `7d1365bc` from `origin/main`.

## Visual truth and evidence

- Source: `C:/Users/Sansk/.codex/generated_images/01a111a6-7bd6-7a81-9f26-b61e551a5767/exec-5ebff909-b113-416f-a1dd-3dfcc450d4dc.png`.
- Browser evidence directory: `C:/Users/Sansk/.codex/visualizations/2026/10/06/01a111a6-7bd6-7a81-9f26-b61e551a5767/landing-qa/`.
- Full views: `desktop-light.png`, `desktop-dark.png`, `mobile-light.png`, `mobile-dark.png`.
- Focused dark views: `dark-builder-focused.png`, `dark-compiler-focused.png`.
- Interaction evidence: `interactive-desktop.png`, `gallery-classic-focused.png`.
- Normalized source views: `reference-light-normalized.png`, `reference-dark-normalized.png`.

The source is a 1341 × 1173 paired theme image. Each half was cropped and proportionally resized to 1440 pixels wide: light 1440 × 2521, dark 1440 × 2517. Desktop captures use a 1440 × 1000 CSS viewport, device scale factor 1, with full-page height approximately 2767. Mobile uses 390 × 844 at scale factor 1. Default state is Modern gallery, guided authoring, collapsed personal details, expanded experience, and illustrative ATS findings. The source and rendered views were inspected together, then checked by a separate visual reviewer.

Full-page Chromium capture occasionally omitted off-screen text immediately after changing themes. Focused screenshots taken after scrolling into each preview prove all document text renders. Image completion, font readiness, two animation frames, and descendant color/visibility checks precede captures. White papers have RGB 255/255/255 backgrounds and RGB 32/35/41 text in dark mode.

## Required fidelity surfaces

- **Typography:** Bricolage display headline, serif italic emphasis, bold editorial section headings, Geist interface/body copy. Heading wrapping and weight were corrected to match the selected composition. Existing Imprint logo is reused.
- **Layout:** preserved hero → gallery → authoring → ATS → tailoring → applications → LaTeX → FAQ → centered closing action → footer. The first implementation was 4008px tall; repeated revisions reduced it to approximately 2767px. The remaining height difference accommodates working controls, clearly labelled sample disclosures, and one additional LaTeX FAQ, without changing the principal composition.
- **Colors:** paper/ink/navy in light mode; neutral charcoal, warm white headings, amber actions in dark mode. Gallery assets preserve white document paper. Semantic tokens support the existing high-contrast preference; reduced-motion CSS disables gallery transitions.
- **Imagery:** optimized 1440 × 580 WebP gallery assets, approximately 82KB each. Source gallery geometry and pale steel blue center panel retained. Assets are illustrative samples, not actual customer documents. Product demos are editable interface content, not raster screenshots of controls.
- **Copy:** selected headline and section framing retained. Removed invented metrics and unsupported rewrite claims; all samples and analysis are labelled. Compiler action opens the actual studio instead of presenting simulated compilation success. Guest limits/account requirements and ATS limitations remain explicit.

## Comparison history

1. P1: excessive vertical density, centered section headings, thin typography, amber dark headings, exposed status selects. Fixed compact spacing, top alignment, bold headings, separate dark heading token, collapsed disclosures, and accessible overflow menus.
2. P2: saturated gallery center, missing builder rail, unstyled source commands, loose FAQ/footer, missing footer CTA. Fixed pale steel gallery, functional icon rail, source syntax colors, compact FAQ/footer, centered final action, and gated footer CTA.
3. Apparent P1: missing dark preview text in full-page capture. Verified complete visible text with scrolled focused captures and computed descendant styles; no application CSS workaround was necessary.
4. P2: gallery selection changed only labels and implied a filtered destination. Fixed real selected-layout focus transform and a plainly named template-library link. Browser verification exercises both selected state and rendered transform.
5. CI/review found optional entry links missing capability gates and the application schema resolving its origin too early. Restored template/builder/studio gates, render-time schema origin, and the unchanged generic footer. All 23 existing tests covering these contracts pass without test edits.
6. The generated capability audit required six additional frontend control-path entries after the refactor. Regenerated the matrix using its existing script; its existing contract passes. No backend policy or tests changed. Linux CI on `8f5498e2` passed all 2197 frontend unit tests and ESLint.

## Interaction verification

Playwright was authorized after the app browser automation retry timed out. Verification uses an isolated anonymous-session fixture and explicit allowed feature grants; application access policy is unchanged. It checks:

- Gallery selection changes preview focus; library link remains truthful.
- Builder input changes appear in the document; tabs support keyboard Home navigation.
- ATS category controls change the displayed explanation.
- Tailoring edits, approval, and keeping the original work locally.
- Application menu moves a card between stages, retaining keyboard focus.
- Compiler selection changes its explanation; actual compilation remains in the studio.
- FAQ expansion, canonical URL, FAQ JSON-LD, and the primary studio navigation.
- No horizontal overflow at 1440px and 390px; no browser page errors during these checks.
- Tablet 768px/high-contrast capture and denied capability fixtures confirm no overflow and no optional template, builder, or studio entry actions when access is denied.

TypeScript and scoped ESLint pass. Production compilation and all 44 static routes succeeded; Windows standalone packaging failed with EPERM creating dependency symlinks. Linux CI remains the release packaging gate. Local source and tests were not changed to bypass that failure. The installed Next hydration patch was repaired only in this worktree's node_modules after proving normalized files exactly matched the existing integrity hashes.

## Follow-up polish and limits

- P3: tiny text in gallery documents is illustrative raster microcopy; editable sample content and accessible descriptions are provided separately.
- Backend authentication, compilation, billing, and persistence are existing product behavior and were not reimplemented by the landing-page samples. Visual checks with service fixtures do not establish backend availability.
- CI and code review must pass before the draft is considered ready for merge.

## Mobile navigation regression follow-up

Cross-browser CI exposed the missing homepage menu after sign-out. The homepage now consumes the existing GlobalHeader mobile panel, session handling, capability filtering, focus trap, Escape behavior, and sign-out logic. Only its trigger is styled for the selected landing design. Desktop composition is unchanged. Existing tests remain unchanged. On `6d5fc743`, all 21 CI checks passed, CodeQL completed neutral, Vercel deployed, and no checks failed. The cross-browser job passed all five configurations, including authenticated sign-out to the homepage guest menu, plus builder/editor/source-PDF and hydration regressions. Real native compilation and full-stack smoke also passed.

Fresh screenshots were recovered through GitHub workflow artifact `11835391088` for run `38437552149`, with archive SHA256 `c3d1112e20b161e98342245589935250b7ce6a0189e285e2dd27e1f9cb81de4b` verified locally. Evidence: `ci-desktop-chromium-6d5fc743.png`, `ci-mobile-chromium-6d5fc743.png`, and `ci-mobile-webkit-6d5fc743.png` in the evidence directory above. Chromium and WebKit mobile headers fit the logo, theme controls, sign-in, and Menu without crowding. All document and equation previews remain visible. Independent visual review found no new P0/P1/P2 issues. Closed-menu visual evidence is separate from the passing menu behavior tests. The prior full light/dark and high-contrast comparisons remain applicable to the unchanged page composition; the trigger uses the existing theme foreground and border tokens.

The final documentation commit changes this report only; application code and assets remain exactly those tested on `6d5fc743`.

final result: passed
