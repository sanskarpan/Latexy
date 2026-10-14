# Hero document scene QA

Scope: homepage hero/gallery only. Isolated worktree, branch `codex/hero-document-scene`, based on merged main `596927a1`.

## Production finding

Current-run in-app browser inspection of https://latexy.xyz/ confirms that the résumé demonstration is a raster image with baked-in text. The loaded image is 960 x 374 pixels, rendered approximately 1265 x 499 CSS pixels in the inspected desktop viewport. The displayed text is visibly soft. The earlier hero visual acceptance is withdrawn.

## Replacement

- Real HTML résumé papers for Classic, Modern and Minimal. Text, headings, dates, rules and layout are native elements, not a document screenshot or texture.
- Classic first/default; selection moves the actual chosen paper to centre. Keyboard arrows/Home/End and touch controls remain supported.
- The existing Three.js dependency draws lit podium geometry, isolated from React rendering. Bounded pointer response, on-demand rendering, capped DPR and no perpetual animation.
- Server-rendered documents remain visible without JavaScript. No-WebGL devices retain readable, selectable documents; context failure cannot remove the HTML.
- Reduced motion resets pointer transforms and disables movement. Native theme tokens and high contrast remain supported.
- Removed both gallery raster assets and image crop/zoom rules. Added scoped marketing instructions prohibiting screenshot-based hero demonstrations.

## Guidance

Installed personal skills: `threejs-fundamentals` and `threejs-interaction` from [CloudAI-X/threejs-skills](https://github.com/CloudAI-X/threejs-skills). Reviewed scene/camera/input/resource guidance and demand-driven rendering guidance. The scene uses direct Three.js with explicit frame scheduling and cleanup. No new dependencies were required.

## Verification status

TypeScript passed. Scoped lint and nine relevant marketing unit tests passed. The origin/SSR test is unchanged and passes after removing the new provider dependency.

New browser regression rejects hero images, disables WebGL, verifies keyboard selection, all three readable native layouts at 320px, overflow and reduced motion. Existing full-page light/dark, five-engine/profile, long-content and interaction tests remain intact. Required exact-head CI and new visual review are pending.

The screenshots in `docs/design/landing/` currently describe the earlier merged design. They are historical evidence and will be refreshed from the new committed component before completion.

final result: blocked — fresh component renders and exact-head checks pending.

## Browser failure diagnosis

The `b9c2495d` run exposed a real integration failure before deployment: the optional graphics module threw `ReactCurrentBatchConfig` while loading React Three Fiber v8 against Next App Router's bundled React 19. The route fell back to the existing 500 page, causing 16 landing control/visual cases to fail. Artifact `11906457370` archive SHA256 `f4b2c5b796f6d606ef38f31664f4a17d3ade7b21289a99eb45f298e1873ba7c3` was verified and its screenshot/trace inspected. No failed assertion was relaxed.

The graphics integration now uses direct Three.js, mounted after hydration through a caught dynamic import. Native HTML remains independent of renderer creation, shader/context failure and graphics loading. The controller pauses offscreen/hidden, renders on demand, and disposes geometry, materials, renderer, observers and frame callbacks on unmount. Application React packages were not changed. Fresh browser renders are required before acceptance.

## First native render review

Source `66e24986` passed 173 quality cases across five profiles, 86 editor/owner cases and both hydration proofs. Artifact `11909447669` from run `38591600500` was downloaded and verified: SHA256 `705ad061044c5756d1809c01cbad158a4dd72477bf2ee4aee0080868faf3151e`. Actual full-resolution light/dark gallery images and all three 320px no-WebGL layouts were opened. Native text is clear and complete.

The review identified P2 side-frame cropping at desktop and excessive card occlusion at 768px. Side papers move up 36px to clear the scene edge; widths at or below 1000px show the selected paper. The Three.js podium visibility follows that breakpoint. Browser assertions now cover complete visible-card bounds at desktop, mobile and 768/1024/1101px. Fresh captures are required for these corrections.

A separate backend environment-isolation test timed out during four unchanged Node launcher setup commands under its 10-second budget. No backend files or test assertions were changed by this hero work; the same backend passed the prior run. Main advanced to `24278325` and was integrated without conflicts. Final checks will run again on that baseline, retaining the launcher test unchanged.
