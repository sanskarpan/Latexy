# Hero document scene QA

## Scope and production diagnosis

Homepage hero/gallery only, in the isolated `codex/hero-document-scene` worktree. Current main `24278325` is integrated; the primary checkout is untouched.

Production browser inspection confirmed that the old demonstration enlarged a 960 x 374 raster to approximately 1265 x 499 CSS pixels. Its document text was baked in and visibly soft. The previous hero visual acceptance is withdrawn.

## Implementation

- Native HTML Classic, Modern and Minimal resumes with selectable text, headings, dates and complete sample content. Classic is first/default. Keyboard arrows/Home/End and touch controls move the chosen document to centre.
- Optional direct Three.js podium geometry, bounded pointer response, capped DPR, on-demand frames, offscreen/hidden-page suspension and resource cleanup. The selected reading surface stays flat.
- Server-rendered documents remain visible without JavaScript. Missing WebGL, failed graphics imports, renderer failure and context loss retain native content. Reduced motion and high contrast are supported.
- Removed both hero raster assets and crop/zoom rules. Scoped marketing instructions require native hero demonstrations and actual visual inspection.
- Installed and applied `threejs-fundamentals` and `threejs-interaction` from CloudAI-X/threejs-skills. No dependency or React package changes.

## Findings resolved

An initial React Three Fiber v8 integration failed under Next App Router's bundled React 19 runtime. The browser run caught the 500 fallback; no assertion was relaxed. Graphics now mount through a caught, isolated direct Three.js import.

Actual renders then revealed clipped side-frame edges, tablet occlusion and crowded captions near 1101px. Side papers moved up, widths up to 1000px show only the selected document, and compact card sizing extends through 1200px. Native and graphics breakpoints agree.

One earlier unchanged backend launcher test exceeded its existing 10-second setup budget. It was not patched. Backend tests passed unchanged on both subsequent source revisions after current main was integrated.

## Final evidence

- Captured source: `5f6803960196da3241a202842dff71698695d6af`.
- [CI run 38694684031](https://github.com/sanskarpan/Latexy/actions/runs/38694684031): all source checks passed, including backend, build, lint, full-stack smoke, isolated real compile, browser quality and Vercel.
- Browser quality: 173 passed, 7 skipped, 0 failed, 0 flaky across desktop Chromium/Firefox/WebKit and mobile Chromium/WebKit profiles.
- Artifact `11955036885`, SHA256 `d391c4269146b54ba0453f83093ead85c570397cc68e25325612a70eeb778024`, downloaded and verified before extraction.
- Inspected full-resolution light/dark gallery renders, Firefox/WebKit native text, 768/1024/1101px layouts and all three 320px no-WebGL layouts. Text and frame edges are complete; final caption spacing is clear. Existing full-page/section, keyboard, overflow, long-content and reduced-motion coverage remains intact.
- `docs/design/landing/` contains actual unchanged browser PNGs from that artifact. `capture.json` records source/frontend tree, dimensions and file hashes. The screenshot publication commit preserves the captured frontend tree; its required exact-head checks remain a merge gate.
- Public CI captures use isolated anonymous-session/allowed-feature fixtures. They do not claim live production backend contact. Production deployment is verified separately after merge.

final result: passed
