# Hero document scene QA

Scope: homepage hero/gallery only. Isolated worktree, branch `codex/hero-document-scene`, based on merged main `596927a1`.

## Production finding

Current-run in-app browser inspection of https://latexy.xyz/ confirms that the résumé demonstration is a raster image with baked-in text. The loaded image is 960 x 374 pixels, rendered approximately 1265 x 499 CSS pixels in the inspected desktop viewport. The displayed text is visibly soft. The earlier hero visual acceptance is withdrawn.

## Replacement

- Real HTML résumé papers for Classic, Modern and Minimal. Text, headings, dates, rules and layout are native elements, not a document screenshot or texture.
- Classic first/default; selection moves the actual chosen paper to centre. Keyboard arrows/Home/End and touch controls remain supported.
- Existing installed React Three Fiber/Three.js dependencies draw lit podium geometry. Bounded pointer response, on-demand rendering, capped DPR and no perpetual animation.
- Server-rendered documents remain visible without JavaScript. No-WebGL devices retain readable, selectable documents; context failure cannot remove the HTML.
- Reduced motion resets pointer transforms and disables movement. Native theme tokens and high contrast remain supported.
- Removed both gallery raster assets and image crop/zoom rules. Added scoped marketing instructions prohibiting screenshot-based hero demonstrations.

## Guidance

Installed personal skills: `threejs-fundamentals` and `threejs-interaction` from [CloudAI-X/threejs-skills](https://github.com/CloudAI-X/threejs-skills). Reviewed scene/camera/input/resource guidance and [React Three Fiber on-demand rendering](https://r3f.docs.pmnd.rs/advanced/scaling-performance). No new dependencies were required.

## Verification status

TypeScript passed. Scoped lint and nine relevant marketing unit tests passed. The origin/SSR test is unchanged and passes after removing the new provider dependency.

New browser regression rejects hero images, disables WebGL, verifies keyboard selection, all three readable native layouts at 320px, overflow and reduced motion. Existing full-page light/dark, five-engine/profile, long-content and interaction tests remain intact. Required exact-head CI and new visual review are pending.

The screenshots in `docs/design/landing/` currently describe the earlier merged design. They are historical evidence and will be refreshed from the new committed component before completion.

final result: blocked — fresh component renders and exact-head checks pending.
